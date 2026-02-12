"""
Сводка по содержимому БД.

Запуск:
    python db_stats.py

Печатает:
  - общие счётчики (groups / posts / comments / users)
  - покрытие sentiment по постам и комментариям
  - покрытие географии (district_id)
  - распределение по тонам в разрезе район × тип записи
  - топ групп по объёму контента
  - примеры свежих записей
"""
from __future__ import annotations

from sqlalchemy import case, func, select

from modules.database import Burst, Comment, Group, Post, Topic, User, get_session
from modules.districts import DISTRICT_BY_ID


def fmt_dt(dt) -> str:
    return dt.strftime("%Y-%m-%d %H:%M") if dt else "—"


def pct(part: int, total: int) -> str:
    return f"{part * 100 // max(total, 1)}%" if total else "—"


def main() -> None:
    with get_session() as s:

        n_groups   = s.scalar(select(func.count()).select_from(Group)) or 0
        n_posts    = s.scalar(select(func.count()).select_from(Post)) or 0
        n_comments = s.scalar(select(func.count()).select_from(Comment)) or 0
        n_users    = s.scalar(select(func.count()).select_from(User)) or 0

        print("=" * 64)
        print(f"  Групп:        {n_groups}")
        print(f"  Постов:       {n_posts}")
        print(f"  Комментариев: {n_comments}")
        print(f"  Юзеров:       {n_users}")
        print("=" * 64)

        if n_posts == 0 and n_comments == 0:
            print("\nБД пустая. Запустите парсер.")
            return

        # ----- покрытие sentiment -----
        posts_sent = s.scalar(
            select(func.count()).select_from(Post)
            .where(Post.sentiment.is_not(None))
        ) or 0
        comm_sent = s.scalar(
            select(func.count()).select_from(Comment)
            .where(Comment.sentiment.is_not(None))
        ) or 0

        # ----- покрытие географии -----
        posts_geo = s.scalar(
            select(func.count()).select_from(Post)
            .where(Post.district_id.is_not(None))
        ) or 0
        comm_geo = s.scalar(
            select(func.count()).select_from(Comment)
            .where(Comment.district_id.is_not(None))
        ) or 0

        # ----- покрытие topic -----
        posts_topic = s.scalar(
            select(func.count()).select_from(Post)
            .where(Post.topic_id.is_not(None))
        ) or 0
        comm_topic = s.scalar(
            select(func.count()).select_from(Comment)
            .where(Comment.topic_id.is_not(None))
        ) or 0

        print("\nПокрытие аналитики:")
        print(f"  {'':14s}{'sentiment':>14s}{'район':>14s}{'topic':>14s}")
        print(f"  {'посты':14s}"
              f"{posts_sent:>7d} ({pct(posts_sent, n_posts):>3s})"
              f"  {posts_geo:>7d} ({pct(posts_geo, n_posts):>3s})"
              f"  {posts_topic:>7d} ({pct(posts_topic, n_posts):>3s})")
        print(f"  {'комментарии':14s}"
              f"{comm_sent:>7d} ({pct(comm_sent, n_comments):>3s})"
              f"  {comm_geo:>7d} ({pct(comm_geo, n_comments):>3s})"
              f"  {comm_topic:>7d} ({pct(comm_topic, n_comments):>3s})")

        # ----- распределение тонов: посты vs комменты -----
        if posts_sent or comm_sent:
            print("\nРаспределение тональности:")
            print(f"  {'':14s}{'negative':>10s}{'neutral':>10s}{'positive':>10s}")
            for cls, label, total_with_sent in [
                (Post, "посты", posts_sent),
                (Comment, "комментарии", comm_sent),
            ]:
                if total_with_sent == 0:
                    continue
                rows = dict(s.execute(
                    select(cls.sentiment, func.count())
                    .where(cls.sentiment.is_not(None))
                    .group_by(cls.sentiment)
                ).all())
                print(f"  {label:14s}"
                      f"{rows.get('negative', 0):>10d}"
                      f"{rows.get('neutral', 0):>10d}"
                      f"{rows.get('positive', 0):>10d}")

        # ----- по районам с разбивкой постов и комментариев -----
        print("\nЗаписей по районам (посты / комментарии / % негатива среди комментариев):")
        # одним запросом — посты по районам
        posts_by_district = dict(s.execute(
            select(Post.district_id, func.count())
            .group_by(Post.district_id)
        ).all())
        # комментарии и доля негатива
        neg_case = case((Comment.sentiment == "negative", 1), else_=0)
        comm_rows = s.execute(
            select(Comment.district_id,
                   func.count(),
                   func.sum(neg_case))
            .group_by(Comment.district_id)
        ).all()
        comm_total_by_d  = {r[0]: r[1] for r in comm_rows}
        comm_neg_by_d    = {r[0]: (r[2] or 0) for r in comm_rows}

        all_district_ids = set(posts_by_district) | set(comm_total_by_d)
        # сортируем: сначала именованные районы по убыванию комментариев, потом None
        named = [d for d in all_district_ids if d is not None]
        named.sort(key=lambda d: comm_total_by_d.get(d, 0), reverse=True)
        ordered = named + ([None] if None in all_district_ids else [])

        for d_id in ordered:
            label = DISTRICT_BY_ID.get(d_id, {}).get("name_ru", "—") \
                if d_id else "(не назначен)"
            p_n = posts_by_district.get(d_id, 0)
            c_n = comm_total_by_d.get(d_id, 0)
            c_neg = comm_neg_by_d.get(d_id, 0)
            neg_share = f"{c_neg * 100 // c_n}%" if c_n else "—"
            print(f"  {label:18s}"
                  f"posts={p_n:>4d}  comments={c_n:>5d}  neg={neg_share:>4s}")

        # ----- топ групп -----
        print("\nТоп групп по числу постов:")
        rows = s.execute(
            select(
                Group.screen_name, Group.district_id,
                func.count(Post.id).label("posts"),
                Group.last_parsed_at,
            )
            .join(Post, Post.group_id == Group.id, isouter=True)
            .group_by(Group.id)
            .order_by(func.count(Post.id).desc())
            .limit(10)
        ).all()
        for r in rows:
            district = DISTRICT_BY_ID.get(r.district_id, {}).get("name_ru", "—") \
                if r.district_id else "(город)"
            print(f"  {r.screen_name:30s} {district:15s} "
                  f"posts={r.posts:>4d}  upd={fmt_dt(r.last_parsed_at)}")

        # ----- темы -----
        n_topics = s.scalar(select(func.count()).select_from(Topic)) or 0
        if n_topics:
            print(f"\nТоп-15 тем (всего {n_topics}):")
            rows = s.execute(
                select(Topic.id, Topic.size, Topic.label)
                .order_by(Topic.size.desc())
                .limit(15)
            ).all()
            for tid, size, label in rows:
                print(f"  #{tid:>3d}  size={size:>5d}  {label}")

        # ----- всплески -----
        n_bursts = s.scalar(select(func.count()).select_from(Burst)) or 0
        if n_bursts:
            by_int = dict(s.execute(
                select(Burst.intensity, func.count())
                .group_by(Burst.intensity)
            ).all())
            print(f"\nВсплесков всего: {n_bursts} "
                  f"(high={by_int.get('high', 0)}, "
                  f"medium={by_int.get('medium', 0)}, "
                  f"low={by_int.get('low', 0)})")
            print("Топ-10 по z-score:")
            rows = s.execute(
                select(Burst.date, Burst.district_id,
                       Burst.volume, Burst.z_score, Topic.label)
                .join(Topic, Topic.id == Burst.topic_id)
                .order_by(Burst.z_score.desc())
                .limit(10)
            ).all()
            for d, did, vol, z, label in rows:
                district = DISTRICT_BY_ID.get(did, {}).get("name_ru", "—") \
                    if did else "(весь город)"
                print(f"  {d.strftime('%Y-%m-%d')}  {district:18s}"
                      f"vol={vol:>3d}  z={z:>4.1f}  {label}")


if __name__ == "__main__":
    main()
