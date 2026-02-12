"""
Геокодинг постов и комментариев — определение района по тексту.

Логика:
  1) Берутся посты с district_id IS NULL — это посты из общегородских
     пабликов (для локальных групп район унаследован при парсинге).
  2) Каждый пост прогоняется через classify_district().
  3) Если район определился — записывается в posts.district_id и
     posts.district_confidence.
  4) Затем район поста пробрасывается на все его комментарии,
     у которых district_id IS NULL: комментарии под общегородским
     постом обычно обсуждают то же место.
  5) Доп. шаг: для комментариев, оставшихся без района (пост тоже
     не определился), пробуем геокодить сам комментарий — иногда
     адрес упомянут только в обсуждении.

Запуск:
    python geocode_posts.py
    python geocode_posts.py --reset       # сбросить и перепрогнать всё
    python geocode_posts.py --debug 30    # показать 30 результатов с матчами
"""
from __future__ import annotations

import argparse
import logging
from collections import Counter

from sqlalchemy import case, func, select, update
from tqdm import tqdm

from modules.database import Comment, Group, Post, get_session, init_db
from modules.districts import DISTRICT_BY_ID
from modules.geocoder import classify_district


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def reset_geocoding(session) -> int:
    """
    Сбросить районы у постов из общегородских пабликов
    и у их комментариев. Локальные группы не трогаем —
    у них район унаследован от группы.
    """
    # Подзапрос: id постов из city-групп (group.district_id IS NULL)
    city_post_ids = select(Post.id).join(Group).where(Group.district_id.is_(None))

    n_comments = session.execute(
        update(Comment).where(Comment.post_id.in_(city_post_ids))
        .values(district_id=None, district_confidence=None)
    ).rowcount

    n_posts = session.execute(
        update(Post).where(Post.group_id.in_(
            select(Group.id).where(Group.district_id.is_(None))
        )).values(district_id=None, district_confidence=None)
    ).rowcount

    session.commit()
    return n_posts + n_comments


def geocode_posts(session, debug_limit: int = 0) -> dict[str, int]:
    """
    Прогон по постам с пустым district_id.
    Возвращает счётчики результатов.
    """
    rows = session.execute(
        select(Post.id, Post.text).where(Post.district_id.is_(None))
    ).all()

    if not rows:
        return {"total": 0, "matched": 0, "skipped": 0}

    logging.info("Геокодинг %d постов...", len(rows))
    counters = Counter()
    debug_shown = 0

    for post_id, text in tqdm(rows, desc="posts", unit="post"):
        result = classify_district(text or "")
        if result.district_id is None:
            counters["skipped"] += 1
            continue
        session.execute(
            update(Post).where(Post.id == post_id).values(
                district_id=result.district_id,
                district_confidence=result.confidence,
            )
        )
        counters[result.district_id] += 1

        if debug_shown < debug_limit:
            preview = (text or "")[:80].replace("\n", " ")
            print(f"  [{result.district_id} {result.confidence:.2f}] "
                  f"{result.matched[:3]} | {preview}")
            debug_shown += 1

    session.commit()
    return {
        "total": len(rows),
        "matched": sum(v for k, v in counters.items() if k != "skipped"),
        "skipped": counters["skipped"],
        "by_district": {k: v for k, v in counters.items() if k != "skipped"},
    }


def propagate_to_comments(session) -> int:
    """
    Пробросить district_id с поста на его комментарии,
    у которых district_id ещё пустой.
    """
    # SQLite поддерживает UPDATE FROM начиная с 3.33; для совместимости
    # с более старыми версиями делаем через коррелированный подзапрос.
    result = session.execute(
        update(Comment)
        .where(Comment.district_id.is_(None))
        .values(
            district_id=select(Post.district_id)
                .where(Post.id == Comment.post_id)
                .where(Post.district_id.is_not(None))
                .scalar_subquery()
        )
    )
    session.commit()
    return result.rowcount


def geocode_orphan_comments(session) -> dict[str, int]:
    """
    Комментарии, у которых даже после propagate район не появился
    (пост тоже без района), пробуем геокодить по их собственному тексту.
    """
    rows = session.execute(
        select(Comment.id, Comment.text).where(Comment.district_id.is_(None))
    ).all()

    if not rows:
        return {"total": 0, "matched": 0, "skipped": 0}

    logging.info("Геокодинг %d 'осиротевших' комментариев...", len(rows))
    counters = Counter()
    for cid, text in tqdm(rows, desc="orphan comments", unit="comm"):
        result = classify_district(text or "")
        if result.district_id is None:
            counters["skipped"] += 1
            continue
        session.execute(
            update(Comment).where(Comment.id == cid).values(
                district_id=result.district_id,
                district_confidence=result.confidence,
            )
        )
        counters[result.district_id] += 1
    session.commit()
    return {
        "total": len(rows),
        "matched": sum(v for k, v in counters.items() if k != "skipped"),
        "skipped": counters["skipped"],
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--reset", action="store_true",
                   help="Сбросить район у общегородских постов и их комментариев "
                        "и перепрогнать заново.")
    p.add_argument("--debug", type=int, default=0,
                   help="Показать N успешных матчей с найденными ключами.")
    p.add_argument("--no-orphans", action="store_true",
                   help="Не запускать геокодинг по тексту самих комментариев.")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    setup_logging(args.verbose)
    init_db()

    with get_session() as session:
        if args.reset:
            n = reset_geocoding(session)
            logging.info("Сброшено %d записей.", n)

        # 1. посты
        post_stats = geocode_posts(session, debug_limit=args.debug)
        print()
        print(f"Посты: {post_stats['matched']}/{post_stats['total']} "
              f"размечено, {post_stats['skipped']} без района")
        if post_stats.get("by_district"):
            for d_id, n in sorted(post_stats["by_district"].items(),
                                  key=lambda kv: -kv[1]):
                name = DISTRICT_BY_ID[d_id]["name_ru"]
                print(f"  {name:18s} {n}")

        # 2. проброс на комментарии
        n_propagated = propagate_to_comments(session)
        print(f"\nКомментариям проброшен район с поста: {n_propagated}")

        # 3. оставшиеся без района — пробуем по их тексту
        if not args.no_orphans:
            orphan_stats = geocode_orphan_comments(session)
            if orphan_stats["total"]:
                print(f"\nОсиротевшие комментарии: "
                      f"{orphan_stats['matched']}/{orphan_stats['total']} "
                      f"размечено")

        # финальная сводка
        total = session.scalar(select(func.count()).select_from(Comment)) or 0
        with_district = session.scalar(
            select(func.count()).select_from(Comment)
            .where(Comment.district_id.is_not(None))
        ) or 0
        print(f"\nИтого комментариев с районом: "
              f"{with_district}/{total} ({with_district * 100 // max(total, 1)}%)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
