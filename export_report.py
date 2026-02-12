"""
Сгенерировать PDF-отчёт по району/городу за период.

Примеры:
    # Отчёт по Сормовскому за весь имеющийся период
    python export_report.py --district sormovsky -o sormovo.pdf

    # Город целиком за последнюю неделю
    python export_report.py --days 7 -o city_week.pdf

    # Конкретный диапазон
    python export_report.py --district avtozavodsky \\
        --since 2026-04-15 --until 2026-04-22 \\
        -o avtozavod_week.pdf
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta
from pathlib import Path

from modules.config import DATA_DIR
from modules.database import init_db
from modules.districts import DISTRICT_BY_ID
from modules.pdf_report import build_district_report


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--district", type=str, default=None,
                   help="ID района (см. modules/districts.py). "
                        "Если не указан — отчёт по всему городу.")
    p.add_argument("--days", type=int, default=None,
                   help="За последние N дней.")
    p.add_argument("--since", type=str, default=None,
                   help="Начало периода (ISO: 2026-04-15).")
    p.add_argument("--until", type=str, default=None,
                   help="Конец периода (ISO; до начала этой даты).")
    p.add_argument("-o", "--output", type=str, default=None,
                   help="Путь к PDF. По умолчанию: data/report_<id>_<ts>.pdf")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    init_db()

    # период
    if args.since:
        start_dt = datetime.fromisoformat(args.since)
    elif args.days:
        start_dt = datetime.now() - timedelta(days=args.days)
    else:
        # без явных границ — берём весь имеющийся диапазон БД
        from modules.data_repo import get_data_period
        rng = get_data_period()
        if rng is None:
            print("В БД нет данных. Сначала запустите парсер.")
            return 1
        start_dt = rng[0]

    if args.until:
        end_dt = datetime.fromisoformat(args.until)
    else:
        end_dt = datetime.now() + timedelta(minutes=1)

    # путь
    if args.output:
        out = Path(args.output)
    else:
        suffix = args.district or "city"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = DATA_DIR / f"report_{suffix}_{ts}.pdf"

    if args.district and args.district not in DISTRICT_BY_ID:
        print(f"Неизвестный district_id: {args.district}")
        print(f"Доступные: {', '.join(DISTRICT_BY_ID.keys())}")
        return 1

    build_district_report(out, args.district, start_dt, end_dt)
    print(f"PDF сохранён: {out}")
    print(f"  период: {start_dt} → {end_dt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
