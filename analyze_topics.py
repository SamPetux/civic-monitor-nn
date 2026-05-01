"""
Тематическое моделирование по постам и комментариям.

Логика:
  1) Берём все тексты (посты + комментарии), кроме помеченных спамом
     (sentiment=neutral со score=0 — это рекламный мусор, см.
     text_cleaner.is_spam — он зашумляет темы).
  2) Чистим тексты тем же препроцессором, что используется для sentiment.
  3) Отбираем только сообщения длиной >= MIN_CHARS (короткие реплики
     'согласен' / 'спасибо' тем не образуют — они шумят).
  4) Запускаем BERTopic.
  5) Сохраняем topic_id обратно в posts/comments, темы — в таблицу topics.

Запуск:
    python analyze_topics.py
    python analyze_topics.py --min-topic-size 20      # крупнее темы
    python analyze_topics.py --district sormovsky     # темы по одному району
    python analyze_topics.py --reset                  # сбросить и перепрогнать
    python analyze_topics.py --top 20                 # после прогона показать топ-20
"""
from __future__ import annotations

import argparse
import logging
import time
from typing import Iterable

from sqlalchemy import delete, select, update
from tqdm import tqdm

from modules.database import (
    Burst, Comment, Post, Topic, get_session, init_db,
)
from modules.text_cleaner import clean_for_sentiment

# Минимальная длина текста после очистки.
MIN_CHARS = 20


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("transformers", "sentence_transformers", "urllib3",
                  "numba", "matplotlib", "umap"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _is_spam(sentiment: str | None, score: float | None) -> bool:
    """Эвристика text_cleaner: спам — neutral со score=0."""
    return sentiment == "neutral" and (score == 0.0 or score is None and False)


def collect_corpus(session, district_id: str | None) -> list[tuple[str, int, int, str]]:
    """
    Вернуть список (cleaned_text, record_id, kind, original_text).
    kind ∈ {'post', 'comment'} — нужен, чтобы потом записать topic_id
    обратно в правильную таблицу.
    """
    out: list[tuple[str, int, int, str]] = []

    # посты
    stmt_p = select(Post.id, Post.text, Post.sentiment, Post.sentiment_score)
    if district_id:
        stmt_p = stmt_p.where(Post.district_id == district_id)
    for pid, text, sent, score in session.execute(stmt_p).all():
        if _is_spam(sent, score):
            continue
        cleaned = clean_for_sentiment(text or "")
        if len(cleaned) >= MIN_CHARS:
            out.append((cleaned, pid, 0, text or ""))  # 0 = post

    # комментарии
    stmt_c = select(Comment.id, Comment.text, Comment.sentiment, Comment.sentiment_score)
    if district_id:
        stmt_c = stmt_c.where(Comment.district_id == district_id)
    for cid, text, sent, score in session.execute(stmt_c).all():
        if _is_spam(sent, score):
            continue
        cleaned = clean_for_sentiment(text or "")
        if len(cleaned) >= MIN_CHARS:
            out.append((cleaned, cid, 1, text or ""))  # 1 = comment

    return out


def write_back(session, modeler, corpus, topics: list[int]) -> dict:
    """
    Сохранить topic_id обратно в posts/comments.
    Создать/перезаписать таблицу topics.
    """
    # 1) словарь тем
    info = modeler.get_topic_info()
    # info: DataFrame с колонками Topic, Count, Name, Representation, ...
    counts = {int(row.Topic): int(row.Count) for _, row in info.iterrows()}

    # очищаем старые темы (сначала bursts — они ссылаются на topics через FK)
    session.execute(delete(Burst))
    session.execute(delete(Topic))
    session.commit()

    written_topics = 0
    for topic_id, size in counts.items():
        if topic_id < 0:
            continue  # шум
        keywords = modeler.get_topic_words(topic_id, top_n=10)
        label = ", ".join(keywords[:3]) if keywords else f"topic_{topic_id}"
        session.add(Topic(
            id=topic_id,
            label=label,
            keywords=", ".join(keywords),
            size=size,
        ))
        written_topics += 1
    session.commit()

    # 2) topic_id обратно в записи. Батчим updates по таблице.
    post_updates: list[dict] = []
    comm_updates: list[dict] = []
    for (cleaned, rid, kind, _orig), tid in zip(corpus, topics):
        # шум (-1) тоже записываем — это валидное "темы нет"
        target = post_updates if kind == 0 else comm_updates
        target.append({
            "id": rid,
            "topic_id": tid if tid >= 0 else None,
        })

    if post_updates:
        session.execute(update(Post), post_updates)
    if comm_updates:
        session.execute(update(Comment), comm_updates)
    session.commit()

    return {
        "topics_written": written_topics,
        "posts_tagged":   len([p for p in post_updates if p["topic_id"] is not None]),
        "comments_tagged": len([c for c in comm_updates if c["topic_id"] is not None]),
        "noise":          sum(1 for t in topics if t < 0),
    }


def show_top_topics(modeler, n: int) -> None:
    info = modeler.get_topic_info()
    info = info[info.Topic >= 0].head(n)
    print(f"\nТоп-{len(info)} тем:")
    for _, row in info.iterrows():
        words = modeler.get_topic_words(int(row.Topic), top_n=8)
        print(f"  #{int(row.Topic):>3d}  size={int(row.Count):>5d}  {', '.join(words)}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--min-topic-size", type=int, default=15,
                   help="Минимальный размер темы (default: 15).")
    p.add_argument("--nr-topics", default="auto",
                   help="Сколько тем оставить: 'auto' или число (default: auto).")
    p.add_argument("--district", type=str, default=None,
                   help="Прогнать только по одному району (id из districts.py).")
    p.add_argument("--limit", type=int, default=None,
                   help="Использовать не более N текстов (для smoke-теста).")
    p.add_argument("--top", type=int, default=15,
                   help="Сколько тем показать после прогона (default: 15).")
    p.add_argument("--heavy", action="store_true",
                   help="Использовать sbert_large_nlu_ru (точнее, медленнее).")
    p.add_argument("--reset", action="store_true",
                   help="Сбросить topic_id у всех записей и перепрогнать.")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    setup_logging(args.verbose)
    init_db()

    # bertopic тяжёлый импорт — делаем после init_db / парсинга args
    from modules.topics import HEAVY_EMB_MODEL, LIGHT_EMB_MODEL, TopicModeler
    embed_model = HEAVY_EMB_MODEL if args.heavy else LIGHT_EMB_MODEL

    nr_topics: int | str = args.nr_topics
    if isinstance(nr_topics, str) and nr_topics.isdigit():
        nr_topics = int(nr_topics)

    with get_session() as session:
        if args.reset:
            n_p = session.execute(update(Post).values(topic_id=None)).rowcount
            n_c = session.execute(update(Comment).values(topic_id=None)).rowcount
            # bursts ссылаются на topics через FK — удаляем сначала их
            session.execute(delete(Burst))
            session.execute(delete(Topic))
            session.commit()
            logging.info("Сброшено: posts=%d, comments=%d, topics и bursts очищены",
                         n_p, n_c)

        logging.info("Собираю корпус...")
        corpus = collect_corpus(session, args.district)
        if args.limit:
            corpus = corpus[:args.limit]
        logging.info("Корпус: %d текстов (%d постов + %d комментариев)",
                     len(corpus),
                     sum(1 for c in corpus if c[2] == 0),
                     sum(1 for c in corpus if c[2] == 1))

        if not corpus:
            print("Пусто. Сначала запустите парсер и/или sentiment.")
            return 1

        modeler = TopicModeler(
            embedding_model_name=embed_model,
            min_topic_size=args.min_topic_size,
            nr_topics=nr_topics,
        )

        t0 = time.monotonic()
        texts = [row[0] for row in corpus]
        topics = modeler.fit_transform(texts)
        elapsed = time.monotonic() - t0
        logging.info("BERTopic отработал за %.1f с", elapsed)

        stats = write_back(session, modeler, corpus, topics)
        print(f"\nГотово.")
        print(f"  Тем сохранено:     {stats['topics_written']}")
        print(f"  Постов с темой:    {stats['posts_tagged']}")
        print(f"  Коммент. с темой:  {stats['comments_tagged']}")
        print(f"  Помечены шумом:    {stats['noise']}")

        if args.top:
            show_top_topics(modeler, args.top)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
