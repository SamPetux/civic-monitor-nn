"""
Парсер VK: выгрузка постов и комментариев из локальных и общегородских
сообществ Нижнего Новгорода.

Архитектура:
    VKParser._call(method, **params)            — низкоуровневая обёртка с
                                                   rate-limit и обработкой ошибок
    VKParser.fetch_posts(group, since_dt, ...)  — генератор постов с пагинацией
    VKParser.fetch_comments(group, post)        — генератор комментариев (вкл. треды)
    VKParser.parse_group(screen_name, ...)      — полный цикл по одной группе
    VKParser.parse_district(district_id, ...)   — все 5 локальных групп района
    VKParser.parse_all(...)                     — всё, плюс общегородские

Запись в БД идёт через INSERT ... ON CONFLICT, поэтому повторный запуск
корректен: новые посты добавятся, у старых обновятся likes/comments_count.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Optional

import vk_api
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from tqdm import tqdm
from vk_api.exceptions import ApiError

from modules.database import Comment, Group, Post, User
from modules.districts import CITY_GROUPS, LOCAL_GROUPS

log = logging.getLogger(__name__)

# Коды ошибок VK API, при которых не нужно ретраить
# (страница удалена / закрыта / нет доступа).
_TERMINAL_CODES = {15, 18, 30, 203, 212}
# Код "Too many requests" — спать и ретраить.
_RATELIMIT_CODE = 6


class VKParser:
    """Парсер с rate-limit, пагинацией и записью в SQLite."""

    def __init__(
        self,
        token: str,
        session: Session,
        *,
        rate_limit_seconds: float = 0.4,
        api_version: str = "5.199",
    ):
        # vk_api оборачивает токен; .get_api() даёт удобный объект,
        # где методы вызываются через точку: api.wall.get(...).
        self._api = vk_api.VkApi(token=token, api_version=api_version).get_api()
        self.session = session
        self.rate_limit = rate_limit_seconds
        self._last_call_at = 0.0
        self.stats = {"posts": 0, "comments": 0, "groups": 0, "errors": 0}

    # ------------------------------------------------------------------
    # Низкоуровневый вызов API
    # ------------------------------------------------------------------
    def _throttle(self) -> None:
        """Пауза между запросами ради соблюдения лимита VK."""
        elapsed = time.monotonic() - self._last_call_at
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)
        self._last_call_at = time.monotonic()

    def _call(self, method: str, **params):
        """
        Универсальная обёртка над VK API.
        method — строка вида 'wall.get', 'groups.getById' и т.п.
        Возвращает None при terminal-ошибках (страница закрыта/удалена),
        чтобы вызывающий код мог пропустить и идти дальше.
        """
        for attempt in range(3):
            self._throttle()
            try:
                target = self._api
                for part in method.split("."):
                    target = getattr(target, part)
                return target(**params)
            except ApiError as e:
                if e.code == _RATELIMIT_CODE:
                    log.warning("VK rate-limit, sleeping 5s")
                    time.sleep(5.0)
                    continue
                if e.code in _TERMINAL_CODES:
                    log.warning("API error %s for %s(%s): %s",
                                e.code, method, params, e)
                    return None
                self.stats["errors"] += 1
                raise
            except Exception as e:  # сеть, JSON и т.п.
                log.warning("Transient error on %s (attempt %d): %s",
                            method, attempt + 1, e)
                time.sleep(2.0 * (attempt + 1))
        self.stats["errors"] += 1
        return None

    # ------------------------------------------------------------------
    # Группы
    # ------------------------------------------------------------------
    def upsert_group(
        self,
        screen_name: str,
        district_id: Optional[str],
    ) -> Optional[Group]:
        """Получить мету группы из VK и записать (или обновить) в БД."""
        info = self._call("groups.getById",
                          group_id=screen_name,
                          fields="members_count")
        if not info:
            log.warning("Группа '%s' не найдена или недоступна", screen_name)
            return None

        # vk_api 5.199: возвращает dict с ключом 'groups' либо просто список.
        if isinstance(info, dict) and "groups" in info:
            info = info["groups"]
        if not info:
            return None
        g = info[0]

        # ищем существующую
        existing = self.session.scalar(
            select(Group).where(Group.screen_name == screen_name)
        )
        if existing:
            existing.name = g.get("name", existing.name)
            existing.members_count = g.get("members_count", existing.members_count)
            existing.last_parsed_at = datetime.utcnow()
            self.session.commit()
            return existing

        group = Group(
            vk_id=g["id"],
            screen_name=screen_name,
            name=g.get("name"),
            district_id=district_id,
            is_local=district_id is not None,
            members_count=g.get("members_count"),
            last_parsed_at=datetime.utcnow(),
        )
        self.session.add(group)
        self.session.commit()
        self.stats["groups"] += 1
        return group

    # ------------------------------------------------------------------
    # Посты — пагинация
    # ------------------------------------------------------------------
    def fetch_posts(
        self,
        group: Group,
        since_dt: datetime,
        max_posts: int = 200,
        page_size: int = 100,
    ) -> Iterator[dict]:
        """
        Генератор постов со стены группы.
        Идёт от свежих к старым; останавливается, когда упёрся в since_dt
        либо набрал max_posts.
        """
        owner_id = -group.vk_id
        offset = 0
        fetched = 0
        while fetched < max_posts:
            response = self._call(
                "wall.get",
                owner_id=owner_id, count=page_size, offset=offset, filter="all",
            )
            if not response or not response.get("items"):
                return
            items = response["items"]
            for post in items:
                post_dt = datetime.fromtimestamp(post["date"])
                if post_dt < since_dt:
                    return
                yield post
                fetched += 1
                if fetched >= max_posts:
                    return
            offset += page_size
            if offset >= response.get("count", 0):
                return

    # ------------------------------------------------------------------
    # Комментарии — пагинация + треды
    # ------------------------------------------------------------------
    def fetch_comments(
        self,
        group: Group,
        post_vk_id: int,
        page_size: int = 100,
        thread_size: int = 10,
    ) -> Iterator[tuple[dict, Optional[int]]]:
        """
        Генератор (comment_dict, parent_comment_vk_id).
        Top-level комментарии идут с parent=None; ответы из тредов —
        с parent = id корневого комментария.
        """
        owner_id = -group.vk_id
        offset = 0
        while True:
            response = self._call(
                "wall.getComments",
                owner_id=owner_id, post_id=post_vk_id,
                count=page_size, offset=offset,
                thread_items_count=thread_size, need_likes=1,
            )
            if not response or not response.get("items"):
                return
            for c in response["items"]:
                yield c, c.get("reply_to_comment")
                # внутри треда — ответы. parent = id корневого.
                thread = c.get("thread", {})
                for nested in thread.get("items", []):
                    yield nested, c["id"]
            offset += page_size
            if offset >= response.get("count", 0):
                return

    # ------------------------------------------------------------------
    # Сохранение в БД (INSERT ... ON CONFLICT)
    # ------------------------------------------------------------------
    def _save_post(self, group: Group, p: dict) -> int:
        """Записать пост, вернуть его внутренний id."""
        values = dict(
            vk_id=p["id"],
            group_id=group.id,
            author_vk_id=p.get("from_id") or p.get("owner_id"),
            text=p.get("text", "") or "",
            date=datetime.fromtimestamp(p["date"]),
            likes=(p.get("likes") or {}).get("count", 0),
            reposts=(p.get("reposts") or {}).get("count", 0),
            comments_count=(p.get("comments") or {}).get("count", 0),
            district_id=group.district_id,
        )
        stmt = sqlite_insert(Post).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["vk_id", "group_id"],
            set_=dict(
                likes=stmt.excluded.likes,
                reposts=stmt.excluded.reposts,
                comments_count=stmt.excluded.comments_count,
            ),
        )
        self.session.execute(stmt)
        # достаём id обратно — нужен для FK комментариев
        post_id = self.session.scalar(
            select(Post.id).where(Post.vk_id == p["id"], Post.group_id == group.id)
        )
        self.stats["posts"] += 1
        return post_id

    def _save_comment(
        self,
        post_db_id: int,
        group: Group,
        c: dict,
        parent_vk_id: Optional[int],
    ) -> None:
        text = c.get("text", "") or ""
        if not text.strip():
            # пустые комментарии (только стикер/фото) для нашей аналитики
            # бесполезны — пропускаем
            return
        values = dict(
            vk_id=c["id"],
            post_id=post_db_id,
            author_vk_id=c.get("from_id"),
            text=text,
            date=datetime.fromtimestamp(c["date"]),
            likes=(c.get("likes") or {}).get("count", 0),
            parent_comment_vk_id=parent_vk_id,
            district_id=group.district_id,  # для local = район группы;
                                            # для city останется None и
                                            # дозаполнится этапом геокодинга
        )
        stmt = sqlite_insert(Comment).values(**values).on_conflict_do_nothing(
            index_elements=["vk_id", "post_id"]
        )
        self.session.execute(stmt)
        self.stats["comments"] += 1

    # ------------------------------------------------------------------
    # Высокоуровневые операции
    # ------------------------------------------------------------------
    def parse_group(
        self,
        screen_name: str,
        district_id: Optional[str],
        since_dt: datetime,
        max_posts: int = 200,
        with_comments: bool = True,
    ) -> None:
        """Полный проход по одной группе: посты + комментарии."""
        group = self.upsert_group(screen_name, district_id)
        if group is None:
            return

        log.info("Парсю '%s' (%s) с %s", group.screen_name, group.name,
                 since_dt.date())
        post_buffer: list[tuple[dict, int]] = []  # (post_data, post_db_id)

        # 1) посты
        for p in self.fetch_posts(group, since_dt, max_posts=max_posts):
            post_db_id = self._save_post(group, p)
            post_buffer.append((p, post_db_id))
        self.session.commit()

        # 2) комментарии — отдельным проходом, чтобы коммитить
        # пост и его комменты пакетно
        if with_comments:
            iterator = tqdm(post_buffer, desc=f"  {screen_name}",
                            unit="post", leave=False)
            for p, post_db_id in iterator:
                if (p.get("comments") or {}).get("count", 0) == 0:
                    continue
                for c, parent_vk_id in self.fetch_comments(group, p["id"]):
                    self._save_comment(post_db_id, group, c, parent_vk_id)
                self.session.commit()

    def parse_district(
        self,
        district_id: str,
        since_dt: datetime,
        max_posts_per_group: int = 100,
    ) -> None:
        """Все локальные группы одного района."""
        groups = LOCAL_GROUPS.get(district_id, [])
        if not groups:
            log.warning("Нет локальных групп для района '%s'", district_id)
            return
        log.info("=== Район %s: %d групп ===", district_id, len(groups))
        for g in groups:
            try:
                self.parse_group(g["screen_name"], district_id,
                                 since_dt, max_posts_per_group)
            except Exception as e:  # noqa: BLE001
                log.exception("Ошибка на группе '%s': %s", g["screen_name"], e)
                self.session.rollback()
                self.stats["errors"] += 1

    def parse_all(
        self,
        since_dt: datetime | None = None,
        max_posts_per_group: int = 100,
        include_city_groups: bool = True,
        days_back: int | None = None,   # legacy, для обратной совместимости
    ) -> None:
        """
        Все локальные группы всех районов + общегородские.

        Граница парсинга задаётся либо явно через since_dt, либо
        legacy-параметром days_back (от текущего момента).
        """
        if since_dt is None:
            if days_back is None:
                days_back = 30
            since_dt = datetime.now() - timedelta(days=days_back)

        for district_id in LOCAL_GROUPS:
            self.parse_district(district_id, since_dt, max_posts_per_group)

        if include_city_groups:
            log.info("=== Общегородские группы: %d ===", len(CITY_GROUPS))
            for g in CITY_GROUPS:
                try:
                    self.parse_group(g["screen_name"], None,
                                     since_dt, max_posts_per_group)
                except Exception as e:  # noqa: BLE001
                    log.exception("Ошибка на группе '%s': %s",
                                  g["screen_name"], e)
                    self.session.rollback()
                    self.stats["errors"] += 1

        log.info("Готово. Статистика: %s", self.stats)

    # ------------------------------------------------------------------
    # Доп: добивка профилей пользователей (батчами по 1000)
    # ------------------------------------------------------------------
    def enrich_users(self, batch_size: int = 1000) -> None:
        """
        Подтянуть имена/screen_name авторов комментариев одним батчем.
        VK users.get принимает до 1000 id за вызов.
        """
        # ids, которых ещё нет в users
        missing_ids = self.session.scalars(
            select(Comment.author_vk_id)
            .where(
                Comment.author_vk_id.is_not(None),
                Comment.author_vk_id > 0,        # отрицательные — это группы
                Comment.author_vk_id.notin_(select(User.vk_id)),
            )
            .distinct()
        ).all()
        if not missing_ids:
            log.info("Все авторы уже подтянуты.")
            return

        log.info("Подтягиваю профили: %d пользователей", len(missing_ids))
        for i in tqdm(range(0, len(missing_ids), batch_size), desc="users.get"):
            batch = missing_ids[i:i + batch_size]
            response = self._call(
                "users.get",
                user_ids=",".join(str(x) for x in batch),
                fields="screen_name",
            )
            if not response:
                continue
            for u in response:
                self.session.execute(
                    sqlite_insert(User).values(
                        vk_id=u["id"],
                        first_name=u.get("first_name"),
                        last_name=u.get("last_name"),
                        screen_name=u.get("screen_name"),
                        is_closed=u.get("is_closed"),
                    ).on_conflict_do_nothing(index_elements=["vk_id"])
                )
            self.session.commit()
