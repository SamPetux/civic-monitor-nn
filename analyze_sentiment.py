"""
Прогон sentiment-анализа по непомеченным записям в БД.

По умолчанию обрабатывает И посты, И комментарии. Можно ограничить
через --target.

Логика для каждого типа записи:
  1) Берём только записи с sentiment IS NULL (повторный запуск дешёвый).
  2) Чистим текст через text_cleaner.clean_for_sentiment().
  3) Спам/шум помечаем neutral / score=0 без вызова модели.
  4) Остальное батчами кормим в RuBERT.
  5) Сохраняем sentiment + sentiment_score обратно.

Запуск:
    # Всё подряд (посты + комментарии):
    python analyze_sentiment.py

    # Только посты:
    python analyze_sentiment.py --target posts

    # Только комментарии:
    python analyze_sentiment.py --target comments

    # Smoke-test:
    python analyze_sentiment.py --limit 200

    # Перепрогнать всё (например, если сменили модель):
    python analyze_sentiment.py --reset
"""
from __future__ import annotations

import argparse
import logging
import time
from typing import Type

from sqlalchemy import select, update
from tqdm import tqdm

from modules.database import Comment, Post, get_session, init_db
from modules.sentiment import DEFAULT_MODEL, HEAVY_MODEL, SentimentAnalyzer
from modules.text_cleaner import clean_for_sentiment, is_spam


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("transformers").setLevel(logging.ERROR)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def _process_table(
    session,
    model: SentimentAnalyzer,
    record_class: Type,
    label: str,
    limit: int | None,
    batch: int,
    commit_every: int,
) -> dict[str, int]:
    """Универсальная обработка таблицы Post или Comment."""
    stmt = select(record_class.id, record_class.text).where(
        record_class.sentiment.is_(None)
    ).order_by(record_class.id)
    if limit:
        stmt = stmt.limit(limit)

    rows = session.execute(stmt).all()
    if not rows:
        print(f"[{label}] нечего обрабатывать")
        return {"total": 0, "scored": 0, "spam": 0}

    logging.info("[%s] К обработке: %d", label, len(rows))

    pending: list[dict] = []
    infer_ids: list[int] = []
    infer_texts: list[str] = []
    spam_count = 0
    scored = 0

    def flush_inference():
        nonlocal scored
        if not infer_ids:
            return
        results = model.predict_batch(infer_texts, batch_size=batch)
        for rid, (sent, score) in zip(infer_ids, results):
            pending.append({"id": rid, "sentiment": sent, "sentiment_score": score})
        scored += len(infer_ids)
        infer_ids.clear()
        infer_texts.clear()

    def flush_pending():
        if not pending:
            return
        session.execute(update(record_class), pending)
        session.commit()
        pending.clear()

    for rid, text in tqdm(rows, desc=label, unit="rec"):
        cleaned = clean_for_sentiment(text or "")
        if is_spam(text or "", cleaned):
            pending.append({"id": rid, "sentiment": "neutral", "sentiment_score": 0.0})
            spam_count += 1
        else:
            infer_ids.append(rid)
            infer_texts.append(cleaned)
            if len(infer_ids) >= batch:
                flush_inference()
        if len(pending) >= commit_every:
            flush_pending()

    flush_inference()
    flush_pending()

    return {"total": len(rows), "scored": scored, "spam": spam_count}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--target", choices=["all", "posts", "comments"], default="all")
    p.add_argument("--limit", type=int, default=None,
                   help="Не больше N записей на каждую таблицу (smoke-тест).")
    p.add_argument("--batch", type=int, default=32,
                   help="Размер батча модели (default: 32).")
    p.add_argument("--commit-every", type=int, default=512,
                   help="Через сколько обработанных писать в БД (default: 512).")
    p.add_argument("--model", choices=["tiny", "heavy"], default="tiny")
    p.add_argument("--reset", action="store_true",
                   help="Сбросить sentiment у выбранных таблиц и перепрогнать.")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    setup_logging(args.verbose)
    init_db()

    targets = []
    if args.target in ("all", "posts"):
        targets.append((Post, "posts"))
    if args.target in ("all", "comments"):
        targets.append((Comment, "comments"))

    model_name = HEAVY_MODEL if args.model == "heavy" else DEFAULT_MODEL

    with get_session() as session:
        if args.reset:
            for cls, name in targets:
                n = session.execute(
                    update(cls).values(sentiment=None, sentiment_score=None)
                ).rowcount
                logging.info("[%s] сброшено %d", name, n)
            session.commit()

        analyzer = SentimentAnalyzer(model_name=model_name)
        t_start = time.monotonic()
        totals = {"total": 0, "scored": 0, "spam": 0}

        for cls, label in targets:
            stats = _process_table(
                session, analyzer, cls, label,
                args.limit, args.batch, args.commit_every,
            )
            print(f"  [{label}] всего={stats['total']} "
                  f"через модель={stats['scored']} спам={stats['spam']}")
            for k in totals:
                totals[k] += stats[k]

        elapsed = time.monotonic() - t_start
        rate = totals["total"] / elapsed if elapsed else 0
        print(f"\nГотово за {elapsed:.1f} с ({rate:.1f} rec/sec). Всего: {totals}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
