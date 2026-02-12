"""
Быстрая сводка по содержимому БД.

Запуск:
    python db_stats.py

Печатает:
  - сколько групп, постов, комментариев, юзеров
  - топ-10 групп по количеству распарсенных постов
  - покрытие комментариев по районам
  - примеры свежих комментариев
  - заполненность sentiment/topic (полезно после следующих блоков)
"""
from __future__ import annotations

from sqlalchemy import func, select

from modules.database import Comment, Group, Post, User, get_session
from modules.districts import DISTRICT_BY_ID


def fmt_dt(dt) -> str:
    return dt.strftime("%Y-%m-%d %H:%M") if dt else "—"


def main() -> None:
    with get_session() as s:

        # --- общие счётчики ---
        n_groups   = s.scalar(select(func.count()).select_from(Group)) or 0
        n_posts    = s.scalar(select(func.count()).select_from(Post)) or 0
        n_comments = s.scalar(select(func.count()).select_from(Comment)) or 0
        n_users    = s.scalar(select(func.count()).select_from(User)) or 0

        print("=" * 60)
        print(f"  Групп:        {n_groups}")
        print(f"  Постов:       {n_posts}")
        print(f"  Комментариев: {n_comments}")
        print(f"  Юзеров:       {n_users}")
        print("=" * 60)

        if n_groups == 0:
            print("\nБД пустая. Запустите парсер: python parse.py --group ... ")
            return

        # --- топ групп по постам ---
        print("\nТоп групп по числу постов:")
        rows = s.execute(
            select(
                Group.screen_name,
                Group.district_id,
                func.count(Post.id).label("posts"),
                func.coalesce(func.sum(Post.comments_count), 0).label("comments_estimated"),
                Group.last_parsed_at,
            )
            .join(Post, Post.group_id == Group.id, isouter=True)
            .group_by(Group.id)
            .order_by(func.count(Post.id).desc())
            .limit(10)
        ).all()
        print(f"  {'screen_name':30s} {'район':15s} {'постов':>7s} {'комм*':>7s} обновлено")
        for r in rows:
            district = DISTRICT_BY_ID.get(r.district_id, {}).get("name_ru", "—") \
                if r.district_id else "(город)"
            print(f"  {r.screen_name:30s} {district:15s} "
                  f"{r.posts:>7d} {r.comments_estimated:>7d} {fmt_dt(r.last_parsed_at)}")
        print("  * — счётчик комментариев из API (включая удалённые/нетекстовые)")

        # --- по районам ---
        print("\nКомментарии по районам:")
        by_district = s.execute(
            select(Comment.district_id, func.count(Comment.id))
            .group_by(Comment.district_id)
            .order_by(func.count(Comment.id).desc())
        ).all()
        for d_id, cnt in by_district:
            label = DISTRICT_BY_ID.get(d_id, {}).get("name_ru", "—") \
                if d_id else "(не назначен)"
            print(f"  {label:20s} {cnt}")

        # --- заполненность аналитических полей ---
        with_sentiment = s.scalar(
            select(func.count()).select_from(Comment)
            .where(Comment.sentiment.is_not(None))
        ) or 0
        with_topic = s.scalar(
            select(func.count()).select_from(Comment)
            .where(Comment.topic_id.is_not(None))
        ) or 0
        if n_comments:
            print(f"\nГотовность для аналитики:")
            print(f"  с sentiment: {with_sentiment}/{n_comments} "
                  f"({with_sentiment * 100 // n_comments}%)")
            print(f"  с темой:     {with_topic}/{n_comments} "
                  f"({with_topic * 100 // n_comments}%)")

        # --- примеры ---
        print("\nПоследние 5 комментариев:")
        recent = s.execute(
            select(Comment.date, Comment.district_id, Comment.text)
            .order_by(Comment.date.desc())
            .limit(5)
        ).all()
        for date, d_id, text in recent:
            preview = (text[:90] + "…") if len(text) > 90 else text
            preview = preview.replace("\n", " ")
            label = DISTRICT_BY_ID.get(d_id, {}).get("name_ru", "—") \
                if d_id else "(?)"
            print(f"  [{fmt_dt(date)}] {label}: {preview}")


if __name__ == "__main__":
    main()
