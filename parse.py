"""
Запуск парсера VK.

Примеры:
    # Распарсить все локальные группы и общегородские за последние 30 дней,
    # по 100 постов на группу:
    python parse.py

    # Только один район:
    python parse.py --district sormovsky

    # Иначе временной охват и лимит постов:
    python parse.py --days 2 --max-posts 200

    # Без общегородских (быстрее):
    python parse.py --no-city

    # Только одна группа (полезно для теста токена):
    python parse.py --group podsluh_sormovo --district sormovsky

    # Подтянуть имена авторов комментариев после парсинга:
    python parse.py --enrich-users
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta

from modules.config import require_token
from modules.database import init_db, get_session
from modules.vk_parser import VKParser


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    # vk_api ругается под INFO про каждый вызов — приглушаем
    logging.getLogger("vk_api").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def main() -> int:
    p = argparse.ArgumentParser(description="VK-парсер для мониторинга НН")
    p.add_argument("--days", type=int, default=None,
                   help="Сколько дней назад брать посты (взаимоисключаемо с --since и --hours).")
    p.add_argument("--hours", type=int, default=None,
                   help="Сколько последних часов парсить.")
    p.add_argument("--since", type=str, default=None,
                   help="ISO-дата нижней границы (например 2026-04-26 "
                        "или 2026-04-26T08:00:00). Перекрывает --days/--hours.")
    p.add_argument("--max-posts", type=int, default=100,
                   help="Максимум постов на группу (default: 100)")
    p.add_argument("--district", type=str,
                   help="Парсить только указанный район (id из districts.py)")
    p.add_argument("--group", type=str,
                   help="Парсить только одну группу по screen_name "
                        "(требует --district или работает как city-группа)")
    p.add_argument("--no-city", action="store_true",
                   help="Пропустить общегородские паблики")
    p.add_argument("--no-comments", action="store_true",
                   help="Только посты, без комментариев (быстро для теста)")
    p.add_argument("--enrich-users", action="store_true",
                   help="После парсинга подтянуть имена авторов комментариев")
    p.add_argument("--rate", type=float, default=0.4,
                   help="Пауза между запросами VK API в сек (default: 0.4)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    setup_logging(args.verbose)

    # Самый первый print, до любого импорта VK API:
    # помогает увидеть в логах refresh-runner, какие именно
    # параметры реально дошли до парсера.
    print(f">>> parse.py: args={vars(args)}", flush=True)

    token = require_token()
    init_db()

    with get_session() as session:
        parser = VKParser(token, session, rate_limit_seconds=args.rate)

        # Определяем since_dt по приоритету: --since > --hours > --days
        if args.since:
            since_dt = datetime.fromisoformat(args.since)
        elif args.hours is not None:
            since_dt = datetime.now() - timedelta(hours=args.hours)
        elif args.days is not None:
            since_dt = datetime.now() - timedelta(days=args.days)
        elif args.enrich_users and not (args.group or args.district):
            # режим только enrich-users — парсинг не нужен
            since_dt = None
        else:
            print(
                "ОШИБКА: укажите --since / --hours / --days, иначе непонятно "
                "откуда парсить. Например: python parse.py --hours 24",
                flush=True,
            )
            return 2

        if since_dt is not None:
            logging.info("Будет парситься: с %s",
                          since_dt.strftime("%Y-%m-%d %H:%M"))

        if since_dt is not None:
            if args.group:
                parser.parse_group(
                    args.group,
                    district_id=args.district,
                    since_dt=since_dt,
                    max_posts=args.max_posts,
                    with_comments=not args.no_comments,
                )
            elif args.district:
                parser.parse_district(
                    args.district, since_dt, args.max_posts
                )
            else:
                parser.parse_all(
                    since_dt=since_dt,
                    max_posts_per_group=args.max_posts,
                    include_city_groups=not args.no_city,
                )

        if args.enrich_users:
            parser.enrich_users()

        print(f"\nИтоги: {parser.stats}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
