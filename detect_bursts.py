"""
Детектор всплесков обсуждений.

Что делает:
  1) Для каждой пары (тема × район) собирает временной ряд:
     сколько сообщений (постов + комментариев) в день, какая
     доля негатива.
  2) Прогоняет detect_bursts_in_series() — находит дни,
     где объём резко превысил скользящее среднее за предыдущие
     WINDOW дней.
  3) Сохраняет результаты в таблицу bursts. Повторный запуск
     не дублирует — INSERT ... ON CONFLICT DO UPDATE.

Также строит ряды без разреза по району (district_id=NULL) —
это всплески «по всему городу», полезно для тем-универсалий.

Запуск:
    python detect_bursts.py
    python detect_bursts.py --window 14 --z 2.5 --min-volume 5
    python detect_bursts.py --reset
    python detect_bursts.py --top 30           # после прогона печатает топ-N
"""
from __future__ import annotations

import argparse
import logging
from collections import defaultdict
from datetime import date, datetime
from typing import Iterable

from sqlalchemy import case, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from tqdm import tqdm

from modules.burst_detector import (
    BurstCandidate, detect_bursts_in_series, fill_daily_gaps,
)
from modules.config import IS_POSTGRES
from modules.database import (
    Burst, Comment, Post, Topic, get_session, init_db,
)
from modules.districts import DISTRICT_BY_ID


def _upsert(table):
    """Правильный диалект INSERT ... ON CONFLICT для текущей БД."""
    return pg_insert(table) if IS_POSTGRES else sqlite_insert(table)


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def _date_range(session) -> tuple[date, date] | None:
    """
    Минимум/максимум по датам сообщений в БД.

    Два отдельных запроса вместо одного с декартовым произведением:
    SELECT min/max на несвязанных таблицах в одном FROM порождает
    SAWarning (cartesian product) и неверный результат на Postgres.
    """
    post_row = session.execute(
        select(func.min(Post.date), func.max(Post.date))
    ).one()
    comment_row = session.execute(
        select(func.min(Comment.date), func.max(Comment.date))
    ).one()

    candidates = [d for d in (*post_row, *comment_row) if d is not None]
    if not candidates:
        return None
    return min(candidates).date(), max(candidates).date()


def _collect_series(
    session, start: date, end: date,
) -> dict[tuple[int, str | None], list[tuple[date, int, float | None]]]:
    """
    Собрать временные ряды для всех пар (topic_id, district_id).
    Дополнительно строит ряды (topic_id, None) — агрегация по всему городу.

    Каждый день представлен один раз; нулевые дни добавляются
    fill_daily_gaps в самом конце, по запросу.
    """
    neg_case_p = case((Post.sentiment == "negative", 1), else_=0)
    neg_case_c = case((Comment.sentiment == "negative", 1), else_=0)

    posts = session.execute(
        select(
            Post.topic_id,
            Post.district_id,
            func.date(Post.date).label("d"),
            func.count().label("vol"),
            func.sum(neg_case_p).label("neg"),
        )
        .where(Post.topic_id.is_not(None))
        .group_by(Post.topic_id, Post.district_id, "d")
    ).all()

    comments = session.execute(
        select(
            Comment.topic_id,
            Comment.district_id,
            func.date(Comment.date).label("d"),
            func.count().label("vol"),
            func.sum(neg_case_c).label("neg"),
        )
        .where(Comment.topic_id.is_not(None))
        .group_by(Comment.topic_id, Comment.district_id, "d")
    ).all()

    # агрегатор: (topic, district, day) -> [vol, neg]
    bucket: dict[tuple[int, str | None, date], list[int]] = defaultdict(
        lambda: [0, 0]
    )
    for tid, did, d, vol, neg in list(posts) + list(comments):
        if d is None:
            continue
        d_obj = d if isinstance(d, date) else date.fromisoformat(str(d))
        bucket[(tid, did, d_obj)][0] += int(vol or 0)
        bucket[(tid, did, d_obj)][1] += int(neg or 0)

    raw_series: dict[tuple[int, str | None], dict[date, list[int]]] = defaultdict(
        lambda: defaultdict(lambda: [0, 0])
    )
    for (tid, did, d), (vol, neg) in bucket.items():
        raw_series[(tid, did)][d][0] += vol
        raw_series[(tid, did)][d][1] += neg
        # агрегация без района — всплески уровня всего города
        raw_series[(tid, None)][d][0] += vol
        raw_series[(tid, None)][d][1] += neg

    out: dict[tuple[int, str | None], list[tuple[date, int, float | None]]] = {}
    for key, by_day in raw_series.items():
        rows = []
        for d, (vol, neg) in by_day.items():
            rows.append((d, vol, (neg / vol) if vol else None))
        rows.sort(key=lambda r: r[0])
        out[key] = fill_daily_gaps(rows, start, end)
    return out


def _save_bursts(session, bursts: Iterable[BurstCandidate]) -> int:
    """INSERT ... ON CONFLICT DO UPDATE для всплесков."""
    rows = list(bursts)
    if not rows:
        return 0
    payload = [{
        "topic_id":      b.topic_id,
        "district_id":   b.district_id,
        "date":          datetime.combine(b.day, datetime.min.time()),
        "volume":        int(b.volume),
        "baseline_mean": float(b.baseline_mean),
        "baseline_std":  float(b.baseline_std),
        "z_score":       float(b.z_score),
        "intensity":     b.intensity,
        "neg_share":     float(b.neg_share) if b.neg_share is not None else None,
    } for b in rows]

    stmt = _upsert(Burst).values(payload)
    stmt = stmt.on_conflict_do_update(
        index_elements=["topic_id", "district_id", "date"],
        set_={
            "volume":        stmt.excluded.volume,
            "baseline_mean": stmt.excluded.baseline_mean,
            "baseline_std":  stmt.excluded.baseline_std,
            "z_score":       stmt.excluded.z_score,
            "intensity":     stmt.excluded.intensity,
            "neg_share":     stmt.excluded.neg_share,
        },
    )
    session.execute(stmt)
    session.commit()
    return len(rows)


def _print_top(session, n: int) -> None:
    rows = session.execute(
        select(
            Burst.date, Burst.district_id, Burst.volume,
            Burst.z_score, Burst.intensity, Burst.neg_share,
            Topic.label,
        )
        .join(Topic, Topic.id == Burst.topic_id)
        .order_by(Burst.z_score.desc())
        .limit(n)
    ).all()
    if not rows:
        print("Всплесков не найдено.")
        return
    print(f"\nТоп-{len(rows)} всплесков по z-score:")
    print(f"  {'дата':<11s}{'район':<18s}{'vol':>4s}{'z':>6s}{'int':>7s}"
          f"{'neg%':>6s}  тема")
    for d, did, vol, z, intensity, neg, label in rows:
        district = DISTRICT_BY_ID.get(did, {}).get("name_ru", "—") \
            if did else "(весь город)"
        neg_pct = f"{int(neg * 100)}" if neg is not None else "—"
        print(f"  {d.strftime('%Y-%m-%d'):<11s}{district:<18s}"
              f"{vol:>4d}{z:>6.1f}{intensity:>7s}{neg_pct:>5s}%  {label}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--window", type=int, default=14,
                   help="Длина базисного окна в днях (default: 14).")
    p.add_argument("--z", type=float, default=2.5,
                   help="Минимальный z-score для всплеска (default: 2.5).")
    p.add_argument("--min-volume", type=int, default=5,
                   help="Минимум сообщений в день (default: 5).")
    p.add_argument("--reset", action="store_true",
                   help="Очистить таблицу bursts перед прогоном.")
    p.add_argument("--top", type=int, default=20,
                   help="Сколько всплесков показать после прогона.")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    setup_logging(args.verbose)
    init_db()

    with get_session() as session:
        if args.reset:
            n = session.execute(delete(Burst)).rowcount
            session.commit()
            logging.info("Сброшено всплесков: %d", n)

        rng = _date_range(session)
        if rng is None:
            print("В БД нет сообщений с датами — нечего анализировать.")
            return 1
        start, end = rng
        logging.info("Период данных: %s .. %s (%d дней)",
                     start, end, (end - start).days + 1)

        if (end - start).days + 1 < args.window + 2:
            print(f"Период слишком короткий для окна {args.window} дней. "
                  f"Уменьшите --window.")
            return 1

        logging.info("Собираю временные ряды...")
        series_by_key = _collect_series(session, start, end)
        logging.info("Рядов: %d", len(series_by_key))

        all_bursts: list[BurstCandidate] = []
        for (topic_id, district_id), series in tqdm(
            series_by_key.items(), desc="series", unit="series"
        ):
            bursts = detect_bursts_in_series(
                topic_id, district_id, series,
                window=args.window,
                z_threshold=args.z,
                min_volume=args.min_volume,
            )
            all_bursts.extend(bursts)

        n_saved = _save_bursts(session, all_bursts)
        print(f"\nНайдено всплесков: {n_saved}")

        rows = session.execute(
            select(Burst.intensity, func.count())
            .group_by(Burst.intensity)
        ).all()
        for label, cnt in rows:
            print(f"  {label:8s} {cnt}")

        if args.top:
            _print_top(session, args.top)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
