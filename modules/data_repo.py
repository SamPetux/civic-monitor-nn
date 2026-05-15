"""
Слой данных для UI: запросы к БД с фильтром по периоду.

Изменения:
  • CommentRow и TopUserRow теперь несут vk_id-поля для ссылок.
  • DistrictMetrics.negativity_score — это z-score отклонения доли
    негатива от средней по городу. Так районы с заметным локальным
    всплеском подсвечиваются красным, даже если абсолютная доля
    негатива в обоих районах ~20%.
  • Поддержка блок-листа topic_id (TOPIC_BLOCKLIST_KEYWORDS) — темы,
    у которых ключевые слова матчатся, исключаются из аналитики.
  • Все функции принимают datetime с точностью до часа/минуты —
    фильтр "последние N часов" работает без изменений в схеме.
"""

# Маппинг полей БД → модель SQLAlchemy:
# comments.from_id          ← (было author_vk_id в старой схеме)
# comments.vk_comment_id    ← (было vk_id)
# comments.parent_id        ← (было parent_comment_vk_id)
# users.vk_user_id          ← (было vk_id)
# posts.vk_post_id          ← (было vk_id)


from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import case, func, not_, select

from modules.database import (
    Burst, Comment, Group, Post, Topic, User, get_session,
)
from modules.districts import DISTRICT_BY_ID, DISTRICTS

from modules.config import IS_POSTGRES


# ----------------------------------------------------------------------
# Темы-шум: ключевые слова, по которым выкидываем "общеновостные"
# темы, не несущие информации о районной повестке.
# Тема исключается, если хотя бы одно её ключевое слово совпадает
# (полное равенство токена) с этим списком.
# ----------------------------------------------------------------------
TOPIC_BLOCKLIST_KEYWORDS = {
    # шум новостных рассылок и подписок
    "max", "макс", "мах", "alex",
    "канале", "канал", "канала",
    "подпис", "подписаться", "подписывайтесь", "подписка",
    "новостей", "новости", "источник",
    "россии", "россия", "рф", "россию",
    #"телеграм", "телеграмм", "tg",
    "ссылка", "ссылку", "сайт",
    "вопрос", "добрый", "больше", "лет",
    #"вопрос",

    "erid", "инн", "студии", "com", "реклама", # реклама
    #"владимирович", "алексеевич", "ульянова", имена из рекламных текстов
    #"мужское", "женское",
}


# ----------------------------------------------------------------------
# Структуры
# ----------------------------------------------------------------------
@dataclass
class DistrictMetrics:
    district_id: str
    name_ru: str
    total_posts: int
    negative: int
    neutral: int
    positive: int
    activity: int
    negativity_score: float       # 0..1 — итоговый "градус" района
    neg_share: float              # абсолютная доля негатива (для подписей)
    delta_vs_city: float          # (district_neg - city_neg), +/-
    # Новые поля для UI:
    unique_authors: int = 0       # уникальные авторы за период
    prev_total_posts: int = 0     # объём за предыдущий равный период (для дельты)
    prev_unique_authors: int = 0
    prev_neg_share: float = 0.0

    @property
    def neg_share_legacy(self) -> float:
        return self.negative / max(self.total_posts, 1)

    @property
    def delta_activity(self) -> float:
        """Изменение активности vs предыдущий период, доля (-1..+inf)."""
        if self.prev_total_posts == 0:
            return 0.0
        return (self.total_posts - self.prev_total_posts) / self.prev_total_posts

    @property
    def delta_neg_share(self) -> float:
        """Изменение доли негатива vs предыдущий период, в п.п."""
        return self.neg_share - self.prev_neg_share


@dataclass
class CommentRow:
    author: str
    user_id: int
    user_url: str | None       # ссылка на профиль VK
    group: str
    group_url: str | None
    text: str
    sentiment: str
    score: float
    created_at: datetime
    district_id: str | None
    comment_url: str | None    # ссылка прямо на комментарий


@dataclass
class TopicRow:
    topic_id: int
    label: str
    keywords: str
    count: int
    neg_share: float


@dataclass
class BurstRow:
    date: datetime
    topic_label: str
    volume: int
    z_score: float
    intensity: str
    neg_share: float | None


@dataclass
class TopUserRow:
    user_id: int
    name: str
    user_url: str
    comments_in_period: int
    avg_sentiment: float
    districts: list[str]
    suspected_bot: bool


# ----------------------------------------------------------------------
# Утилиты
# ----------------------------------------------------------------------
def _period_filter(column, start_dt: datetime | None, end_dt: datetime | None):
    conds = []
    if start_dt is not None:
        conds.append(column >= start_dt)
    if end_dt is not None:
        conds.append(column < end_dt)
    return conds


def _vk_user_url(user_id: int | None) -> str | None:
    if not user_id or user_id <= 0:
        return None
    return f"https://vk.com/id{user_id}"


def _vk_post_url(group_vk_id: int | None, post_vk_id: int | None) -> str | None:
    if not group_vk_id or not post_vk_id:
        return None
    return f"https://vk.com/wall-{group_vk_id}_{post_vk_id}"


def _vk_comment_url(
    group_vk_id: int | None,
    post_vk_id: int | None,
    comment_vk_id: int | None,
) -> str | None:
    base = _vk_post_url(group_vk_id, post_vk_id)
    if not base or not comment_vk_id:
        return base
    return f"{base}?reply={comment_vk_id}"


def _vk_group_url(screen_name: str | None) -> str | None:
    if not screen_name:
        return None
    return f"https://vk.com/{screen_name}"


def _blocked_topic_ids(session) -> set[int]:
    """ID тем, ключевые слова которых матчатся с TOPIC_BLOCKLIST_KEYWORDS."""
    out: set[int] = set()
    for tid, kws in session.execute(select(Topic.id, Topic.keywords)).all():
        if not kws:
            continue
        # keywords хранятся как "слово1, слово2, слово3" — режем
        tokens = {t.strip().lower() for t in kws.split(",") if t.strip()}
        if tokens & TOPIC_BLOCKLIST_KEYWORDS:
            out.add(int(tid))
    return out


def get_data_period() -> tuple[datetime, datetime] | None:
    with get_session() as s:
        row = s.execute(select(
            func.min(Post.date), func.max(Post.date),
            func.min(Comment.date), func.max(Comment.date),
        )).one()
    candidates = [d for d in row if d is not None]
    if not candidates:
        return None
    return min(candidates), max(candidates)


def is_db_empty() -> bool:
    with get_session() as s:
        n = s.scalar(select(func.count()).select_from(Comment)) or 0
    return n == 0


# ----------------------------------------------------------------------
# Метрики по районам
# ----------------------------------------------------------------------
def _sentiment_aggs(sent_col):
    return [
        func.count().label("total"),
        func.sum(case((sent_col == "negative", 1), else_=0)).label("neg"),
        func.sum(case((sent_col == "neutral",  1), else_=0)).label("neu"),
        func.sum(case((sent_col == "positive", 1), else_=0)).label("pos"),
    ]


def get_district_metrics(
    start_dt: datetime | None = None,
    end_dt: datetime | None = None,
) -> list[DistrictMetrics]:
    """
    Сводка по каждому району. См. DistrictMetrics для описания полей.
    Дополнительно считает уникальных авторов и метрики предыдущего равного
    периода (для дельт). Если start_dt/end_dt не заданы — prev-блок остаётся нулевым.
    """
    # Длина периода для prev-расчёта
    prev_start = prev_end = None
    if start_dt and end_dt:
        delta = end_dt - start_dt
        prev_end = start_dt
        prev_start = start_dt - delta

    def _aggregate(s_start, s_end):
        """Возвращает {district_id: (total, neg, neu, pos, authors)}."""
        out: dict[str, dict] = {}

        # Посты
        conds_p = []
        conds_p += _period_filter(Post.date, s_start, s_end)
        conds_p.append(Post.district_id.is_not(None))

        with get_session() as s:
            p_rows = s.execute(
                select(
                    Post.district_id,
                    func.count().label("total"),
                    func.sum(case((Post.sentiment == "negative", 1), else_=0)).label("neg"),
                    func.sum(case((Post.sentiment == "neutral",  1), else_=0)).label("neu"),
                    func.sum(case((Post.sentiment == "positive", 1), else_=0)).label("pos"),
                ).where(*conds_p).group_by(Post.district_id)
            ).all()

            conds_c = []
            conds_c += _period_filter(Comment.date, s_start, s_end)
            conds_c.append(Comment.district_id.is_not(None))
            c_rows = s.execute(
                select(
                    Comment.district_id,
                    func.count().label("total"),
                    func.sum(case((Comment.sentiment == "negative", 1), else_=0)).label("neg"),
                    func.sum(case((Comment.sentiment == "neutral",  1), else_=0)).label("neu"),
                    func.sum(case((Comment.sentiment == "positive", 1), else_=0)).label("pos"),
                ).where(*conds_c).group_by(Comment.district_id)
            ).all()

            # Уникальные авторы (по комментариям — основной сигнал активности)
            a_rows = s.execute(
                select(
                    Comment.district_id,
                    func.count(func.distinct(Comment.from_id)).label("authors"),
                ).where(*conds_c).group_by(Comment.district_id)
            ).all()

        for did, total, neg, neu, pos in p_rows:
            d = out.setdefault(did, {"total": 0, "neg": 0, "neu": 0, "pos": 0, "authors": 0})
            d["total"] += int(total or 0); d["neg"] += int(neg or 0)
            d["neu"]   += int(neu or 0);   d["pos"] += int(pos or 0)
        for did, total, neg, neu, pos in c_rows:
            d = out.setdefault(did, {"total": 0, "neg": 0, "neu": 0, "pos": 0, "authors": 0})
            d["total"] += int(total or 0); d["neg"] += int(neg or 0)
            d["neu"]   += int(neu or 0);   d["pos"] += int(pos or 0)
        for did, authors in a_rows:
            d = out.setdefault(did, {"total": 0, "neg": 0, "neu": 0, "pos": 0, "authors": 0})
            d["authors"] = int(authors or 0)

        return out

    cur = _aggregate(start_dt, end_dt)
    prev = _aggregate(prev_start, prev_end) if prev_start else {}

    # Считаем z-score окраски (как раньше)
    neg_shares = []
    for did in DISTRICT_BY_ID:
        d = cur.get(did, {"total": 0, "neg": 0})
        if d["total"] >= 5:
            neg_shares.append(d["neg"] / max(d["total"], 1))
    if neg_shares:
        city_neg = sum(neg_shares) / len(neg_shares)
        var = sum((x - city_neg) ** 2 for x in neg_shares) / len(neg_shares)
        sigma = math.sqrt(var) or 1.0
    else:
        city_neg, sigma = 0.0, 1.0

    result: list[DistrictMetrics] = []
    for did, info in DISTRICT_BY_ID.items():
        d = cur.get(did, {"total": 0, "neg": 0, "neu": 0, "pos": 0, "authors": 0})
        p = prev.get(did, {"total": 0, "neg": 0, "authors": 0})
        total = d["total"]
        neg_share = d["neg"] / max(total, 1)
        # Сглаживание малых выборок к city_neg (Лаплас)
        smoothed = (d["neg"] + city_neg * 10) / max(total + 10, 1)
        z = (smoothed - city_neg) / sigma if total else 0.0
        score = 1 / (1 + math.exp(-z))

        prev_total = p["total"]
        prev_neg_share = (p["neg"] / prev_total) if prev_total else 0.0

        result.append(DistrictMetrics(
            district_id=did,
            name_ru=info["name_ru"],
            total_posts=total,
            negative=d["neg"],
            neutral=d["neu"],
            positive=d["pos"],
            activity=total,
            negativity_score=round(score, 3),
            neg_share=round(neg_share, 3),
            delta_vs_city=round(neg_share - city_neg, 3),
            unique_authors=d["authors"],
            prev_total_posts=prev_total,
            prev_unique_authors=p["authors"],
            prev_neg_share=round(prev_neg_share, 3),
        ))
    return result


# ----------------------------------------------------------------------
# Комментарии в районе — теперь со ссылками
# ----------------------------------------------------------------------
def get_recent_comments(
    district_id: str,
    start_dt: datetime | None = None,
    end_dt: datetime | None = None,
    limit: int = 50,
    offset: int = 0,                          # NEW: для пагинации
    sentiment: str | None = None,
    excluded_user_ids: set[int] | None = None,
    group_ids: set[int] | None = None,        # NEW: фильтр по группам (Group.id)
) -> list[CommentRow]:
    excluded_user_ids = excluded_user_ids or set()
    conds = [Comment.district_id == district_id]
    conds += _period_filter(Comment.date, start_dt, end_dt)
    if sentiment:
        conds.append(Comment.sentiment == sentiment)
    if group_ids:
        conds.append(Group.id.in_(group_ids))

    with get_session() as s:
        rows = s.execute(
            select(
                Comment.from_id,
                Comment.vk_comment_id, Comment.text, Comment.sentiment,
                Comment.sentiment_score, Comment.date, Comment.district_id,
                User.first_name, User.last_name,
                Group.name, Group.screen_name, Group.vk_id.label("group_vk_id"),
                Post.vk_post_id.label("post_vk_id"),
            )
            .join(Post, Post.id == Comment.post_id)
            .join(Group, Group.id == Post.group_id)
            .join(User, User.vk_user_id == Comment.from_id, isouter=True)
            .where(*conds)
            .order_by(Comment.date.desc())
            .offset(offset)
            .limit(limit * 2)
        ).all()

    out: list[CommentRow] = []
    for r in rows:
        uid = r.from_id
        if uid in excluded_user_ids:
            continue
        author = f"{r.first_name or ''} {r.last_name or ''}".strip()
        if not author:
            author = f"id{uid}" if uid else "—"
        group_name = r.name or r.screen_name or "—"
        out.append(CommentRow(
            author=author,
            user_id=int(uid or 0),
            user_url=_vk_user_url(uid),
            group=group_name,
            group_url=_vk_group_url(r.screen_name),
            text=r.text or "",
            sentiment=r.sentiment or "neutral",
            score=float(r.sentiment_score or 0),
            created_at=r.date,
            district_id=r.district_id,
            comment_url=_vk_comment_url(r.group_vk_id, r.post_vk_id, r.vk_comment_id),
        ))
        if len(out) >= limit:
            break
    return out


# ----------------------------------------------------------------------
# Динамика по тонам
# ----------------------------------------------------------------------
def get_sentiment_timeseries(
    district_id: str,
    start_dt: datetime | None = None,
    end_dt: datetime | None = None,
    bucket: str = "day",  # "day" или "hour"
) -> list[dict]:
    """[{date, negative, neutral, positive}] по бакетам."""
    if bucket == "hour":
        if IS_POSTGRES:
            # PostgreSQL: date_trunc возвращает timestamp с обнулёнными мин/сек
            date_p = func.date_trunc("hour", Post.date)
            date_c = func.date_trunc("hour", Comment.date)
        else:
            date_p = func.strftime("%Y-%m-%d %H:00", Post.date)
            date_c = func.strftime("%Y-%m-%d %H:00", Comment.date)
    else:
        # func.date работает и в PG, и в SQLite
        date_p = func.date(Post.date)
        date_c = func.date(Comment.date)

    conds_p = [Post.district_id == district_id]
    conds_p += _period_filter(Post.date, start_dt, end_dt)
    conds_c = [Comment.district_id == district_id]
    conds_c += _period_filter(Comment.date, start_dt, end_dt)

    by_bucket: dict[str, dict[str, int]] = {}

    def upsert(key: str, sent: str, n: int):
        d = by_bucket.setdefault(key, {"negative": 0, "neutral": 0, "positive": 0})
        d[sent or "neutral"] = d.get(sent or "neutral", 0) + int(n or 0)

    with get_session() as s:
        p_rows = s.execute(
            select(date_p, Post.sentiment, func.count())
            .where(*conds_p).group_by(date_p, Post.sentiment)
        ).all()
        c_rows = s.execute(
            select(date_c, Comment.sentiment, func.count())
            .where(*conds_c).group_by(date_c, Comment.sentiment)
        ).all()

    for d, sent, n in list(p_rows) + list(c_rows):
        if d is None:
            continue
        upsert(str(d), sent, n)

    return [{"date": d, **counts} for d, counts in sorted(by_bucket.items())]


# ----------------------------------------------------------------------
# Топ тем — с фильтром блок-листа
# ----------------------------------------------------------------------
def get_top_topics(
    district_id: str | None,
    start_dt: datetime | None = None,
    end_dt: datetime | None = None,
    limit: int = 5,
) -> list[TopicRow]:
    neg_case = case((Comment.sentiment == "negative", 1), else_=0)

    with get_session() as s:
        blocked = _blocked_topic_ids(s)

        conds = [Comment.topic_id.is_not(None)]
        if blocked:
            conds.append(not_(Comment.topic_id.in_(blocked)))
        if district_id:
            conds.append(Comment.district_id == district_id)
        conds += _period_filter(Comment.date, start_dt, end_dt)

        rows = s.execute(
            select(
                Comment.topic_id,
                func.count().label("n"),
                func.sum(neg_case).label("neg"),
                Topic.label, Topic.keywords,
            )
            .join(Topic, Topic.id == Comment.topic_id)
            .where(*conds)
            .group_by(Comment.topic_id, Topic.label, Topic.keywords)  # ← добавили label и keywords
            .order_by(func.count().desc())
            .limit(limit)
        ).all()

    return [
        TopicRow(
            topic_id=int(tid), label=label or "", keywords=keywords or "",
            count=int(n),
            neg_share=round(float(neg or 0) / max(int(n), 1), 3),
        )
        for tid, n, neg, label, keywords in rows
    ]


# ----------------------------------------------------------------------
# Всплески — с фильтром блок-листа
# ----------------------------------------------------------------------
def get_bursts(
    district_id: str | None,
    start_dt: datetime | None = None,
    end_dt: datetime | None = None,
    limit: int = 10,
    citywide_if_none: bool = True,
) -> list[BurstRow]:
    if district_id is None and not citywide_if_none:
        return []

    with get_session() as s:
        blocked = _blocked_topic_ids(s)

        conds = []
        if district_id is None:
            conds.append(Burst.district_id.is_(None))
        else:
            conds.append(Burst.district_id == district_id)
        if blocked:
            conds.append(not_(Burst.topic_id.in_(blocked)))
        conds += _period_filter(Burst.date, start_dt, end_dt)

        rows = s.execute(
            select(
                Burst.date, Topic.label,
                Burst.volume, Burst.z_score, Burst.intensity, Burst.neg_share,
            )
            .join(Topic, Topic.id == Burst.topic_id)
            .where(*conds)
            .order_by(Burst.z_score.desc())
            .limit(limit)
        ).all()

    return [
        BurstRow(
            date=d, topic_label=label or "—",
            volume=int(vol), z_score=float(z),
            intensity=intensity or "low",
            neg_share=float(neg) if neg is not None else None,
        )
        for d, label, vol, z, intensity, neg in rows
    ]


# ----------------------------------------------------------------------
# Топ авторов — с user_url
# ----------------------------------------------------------------------
def get_top_users(
    start_dt: datetime | None = None,
    end_dt: datetime | None = None,
    limit: int = 30,
) -> list[TopUserRow]:
    pos_case = case((Comment.sentiment == "positive", 1), else_=0)
    neg_case = case((Comment.sentiment == "negative", 1), else_=0)

    conds = [Comment.from_id.is_not(None), Comment.from_id > 0]
    conds += _period_filter(Comment.date, start_dt, end_dt)

    with get_session() as s:
        rows = s.execute(
            select(
                Comment.from_id,
                func.count().label("n"),
                func.sum(pos_case).label("pos"),
                func.sum(neg_case).label("neg"),
                User.first_name, User.last_name, User.screen_name,
            )
            .join(User, User.vk_user_id == Comment.from_id, isouter=True)
            .where(*conds)
            .group_by(Comment.from_id, User.first_name, User.last_name, User.screen_name)
            .order_by(func.count().desc())
            .limit(limit)
        ).all()

        user_districts: dict[int, set[str]] = {}
        if rows:
            user_ids = [r[0] for r in rows]
            d_rows = s.execute(
                select(Comment.from_id, Comment.district_id)
                .where(
                    Comment.from_id.in_(user_ids),
                    Comment.district_id.is_not(None),
                    *_period_filter(Comment.date, start_dt, end_dt),
                )
                .distinct()
            ).all()
            for uid, did in d_rows:
                user_districts.setdefault(int(uid), set()).add(did)

    out: list[TopUserRow] = []
    for uid, n, pos, neg, fn, ln, sn in rows:
        n = int(n)
        avg = (int(pos or 0) - int(neg or 0)) / max(n, 1)
        suspected = (n >= 30 and abs(avg) >= 0.7)
        # имя: либо first+last, либо screen_name, либо id
        name = f"{fn or ''} {ln or ''}".strip()
        if not name:
            name = sn or f"id{uid}"
        # url: всегда через id, это надёжнее чем screen_name
        url = _vk_user_url(uid) or f"https://vk.com/id{uid}"
        out.append(TopUserRow(
            user_id=int(uid),
            name=name,
            user_url=url,
            comments_in_period=n,
            avg_sentiment=round(avg, 2),
            districts=sorted(user_districts.get(int(uid), set())),
            suspected_bot=suspected,
        ))
    return out


# ----------------------------------------------------------------------
# Heatmap "темы x время"
# ----------------------------------------------------------------------
def get_topic_day_heatmap(
    district_id: str | None,
    start_dt: datetime | None = None,
    end_dt: datetime | None = None,
    top_n_topics: int = 8,
) -> tuple[list[str], list[str], list[list[int]]]:
    top = get_top_topics(district_id, start_dt, end_dt, limit=top_n_topics)
    if not top:
        return [], [], []
    topic_ids = [t.topic_id for t in top]
    topic_labels = [t.label for t in top]

    conds = [Comment.topic_id.in_(topic_ids)]
    if district_id:
        conds.append(Comment.district_id == district_id)
    conds += _period_filter(Comment.date, start_dt, end_dt)

    with get_session() as s:
        rows = s.execute(
            select(func.date(Comment.date), Comment.topic_id, func.count())
            .where(*conds).group_by(func.date(Comment.date), Comment.topic_id)
        ).all()

    all_days = sorted({str(r[0]) for r in rows})
    day_idx = {d: i for i, d in enumerate(all_days)}
    topic_idx = {t: i for i, t in enumerate(topic_ids)}

    matrix = [[0] * len(all_days) for _ in topic_ids]
    for d, tid, n in rows:
        matrix[topic_idx[int(tid)]][day_idx[str(d)]] = int(n)
    return all_days, topic_labels, matrix


# ----------------------------------------------------------------------
# Функция для списка групп
# ----------------------------------------------------------------------
@dataclass
class GroupRow:
    id: int
    name: str
    screen_name: str
    district_id: str | None
    is_citywide: bool


def get_groups(district_id: str | None = None) -> list[GroupRow]:
    """Список всех VK-групп, опционально фильтр по району."""
    with get_session() as s:
        q = select(Group.id, Group.name, Group.screen_name,
                   Group.district_id, Group.is_local)
        if district_id:
            q = q.where(Group.district_id == district_id)
        rows = s.execute(q.order_by(Group.name)).all()
    return [
        GroupRow(
            id=int(r.id),
            name=r.name or r.screen_name or "—",
            screen_name=r.screen_name or "",
            district_id=r.district_id,
            is_citywide=not bool(r.is_local),  # is_local=False → общегородская
        ) for r in rows
    ]