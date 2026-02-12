"""
Бенчмарк качества модели sentiment и тем.

Что делает:
  1) sentiment — предлагает разметить вручную случайную выборку
     комментариев из БД. Сохраняет в data/benchmark_labels.csv.
     Затем считает precision / recall / F1 / accuracy и confusion-matrix.

  2) topics — считает coherence (c_v) и diversity для текущих тем.
     Coherence — мера согласованности слов внутри темы;
     diversity — насколько темы отличаются друг от друга.

Использование:
    # Шаг 1: создать пустой шаблон для разметки (200 случайных комментов)
    python benchmark.py sentiment-template --n 200

    # Шаг 2: открыть data/benchmark_labels.csv в Excel/LibreOffice,
    # заполнить колонку true_label значениями negative/neutral/positive.
    # Если согласны с предсказанием модели — оставьте колонку пустой
    # (она автоматически "не учитывается"); чтобы переразметить,
    # впишите вручную.

    # Шаг 3: посчитать метрики
    python benchmark.py sentiment

    # Темы — без ручной разметки, чисто автоматически
    python benchmark.py topics
"""
from __future__ import annotations

import argparse
import csv
import logging
import random
import sys
from collections import Counter
from pathlib import Path

from sqlalchemy import select

from modules.config import DATA_DIR
from modules.database import Comment, Topic, get_session
from modules.text_cleaner import clean_for_sentiment

LABELS_PATH = DATA_DIR / "benchmark_labels.csv"
LABELS = ("negative", "neutral", "positive")


# ----------------------------------------------------------------------
# Sentiment
# ----------------------------------------------------------------------
def make_template(n: int, seed: int = 42) -> int:
    """
    Создать CSV-шаблон для ручной разметки.
    Содержит случайную выборку из БД с предсказанной меткой и пустым
    столбцом true_label — пользователь его заполнит.
    """
    with get_session() as s:
        rows = s.execute(
            select(Comment.id, Comment.text, Comment.sentiment,
                   Comment.sentiment_score)
            .where(Comment.sentiment.is_not(None))
        ).all()

    if not rows:
        print("В БД нет комментариев с разметкой sentiment.")
        return 1

    random.Random(seed).shuffle(rows)
    sample = rows[:n]

    LABELS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LABELS_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["id", "predicted", "score", "true_label", "text"])
        for cid, text, pred, score in sample:
            cleaned = clean_for_sentiment(text or "")
            # обрезаем длинные тексты для удобства разметки в Excel
            short = (cleaned[:200] + "…") if len(cleaned) > 200 else cleaned
            w.writerow([cid, pred, f"{score:.2f}" if score else "",
                        "", short.replace("\n", " ")])

    print(f"Создан шаблон: {LABELS_PATH}")
    print(f"  выборка: {len(sample)} комментариев")
    print(f"  заполните колонку true_label значениями: "
          f"{', '.join(LABELS)}")
    print(f"  пустые строки в true_label считаются согласными "
          f"с предсказанием модели")
    return 0


def _parse_csv() -> list[tuple[int, str, str | None]]:
    """
    Прочитать labels.csv, вернуть список (id, predicted, true_label).
    Если true_label пустой — считаем true_label = predicted (согласие).
    """
    if not LABELS_PATH.exists():
        print(f"Нет файла {LABELS_PATH}. Сначала: "
              f"python benchmark.py sentiment-template")
        sys.exit(1)

    out = []
    with LABELS_PATH.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            try:
                cid = int(row["id"])
            except (KeyError, ValueError):
                continue
            pred = (row.get("predicted") or "").strip().lower()
            true = (row.get("true_label") or "").strip().lower()
            if not true:
                true = pred  # пустая ячейка = согласен с моделью
            if pred not in LABELS or true not in LABELS:
                continue
            out.append((cid, pred, true))
    return out


def _safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def evaluate_sentiment() -> int:
    pairs = _parse_csv()
    if not pairs:
        print("В CSV нет валидных строк.")
        return 1

    total = len(pairs)
    correct = sum(1 for _, p, t in pairs if p == t)
    accuracy = correct / total

    # per-class precision/recall/F1
    print(f"=== Бенчмарк sentiment ({total} записей) ===")
    print(f"Accuracy: {accuracy:.3f} ({correct}/{total})\n")

    print(f"  {'class':<10s} {'precision':>10s} {'recall':>10s} "
          f"{'F1':>10s} {'support':>10s}")
    macro_p = macro_r = macro_f = 0.0
    weighted_f = 0.0
    for cls in LABELS:
        tp = sum(1 for _, p, t in pairs if p == cls and t == cls)
        fp = sum(1 for _, p, t in pairs if p == cls and t != cls)
        fn = sum(1 for _, p, t in pairs if p != cls and t == cls)
        support = tp + fn
        precision = _safe_div(tp, tp + fp)
        recall    = _safe_div(tp, tp + fn)
        f1        = _safe_div(2 * precision * recall, precision + recall)
        macro_p += precision
        macro_r += recall
        macro_f += f1
        weighted_f += f1 * support
        print(f"  {cls:<10s} {precision:>10.3f} {recall:>10.3f} "
              f"{f1:>10.3f} {support:>10d}")

    macro_p /= len(LABELS)
    macro_r /= len(LABELS)
    macro_f /= len(LABELS)
    weighted_f /= total
    print(f"\n  macro avg  {macro_p:>10.3f} {macro_r:>10.3f} "
          f"{macro_f:>10.3f}")
    print(f"  weighted F1: {weighted_f:.3f}")

    # confusion matrix
    print("\nConfusion matrix (rows=true, cols=predicted):")
    print(f"  {'':<10s}" + "".join(f"{c:>10s}" for c in LABELS))
    for true_cls in LABELS:
        row = []
        for pred_cls in LABELS:
            cnt = sum(1 for _, p, t in pairs
                      if t == true_cls and p == pred_cls)
            row.append(cnt)
        print(f"  {true_cls:<10s}" + "".join(f"{v:>10d}" for v in row))

    # сколько было реально размечено руками (отличается от пустых)
    with LABELS_PATH.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        manually = sum(1 for r in reader if (r.get("true_label") or "").strip())
    print(f"\nРучных меток: {manually}/{total} "
          f"(остальные считаются согласием с моделью).")
    if manually < 50:
        print("⚠️  Размечено мало — для надёжных метрик стоит "
              "разметить хотя бы 100-150 комментариев.")
    return 0


# ----------------------------------------------------------------------
# Topics — coherence + diversity
# ----------------------------------------------------------------------
def evaluate_topics(top_k: int = 10) -> int:
    """
    Diversity: доля уникальных слов в объединённых топ-K слов всех тем.
      diversity = |unique_words| / (n_topics * top_k)
    Coherence (c_npmi-light): для каждой темы считаем долю пар слов,
    у которых co-occurrence в комментариях темы выше базового уровня.
    Это упрощённая метрика — без gensim/wikipedia, чтобы не тащить
    тяжёлые зависимости.
    """
    with get_session() as s:
        topics = s.execute(select(Topic.id, Topic.label, Topic.keywords,
                                  Topic.size)
                           .order_by(Topic.size.desc())).all()
        if not topics:
            print("В БД нет тем. Запустите analyze_topics.py.")
            return 1

        # для coherence соберём тексты комментариев по темам
        comm_texts: dict[int, list[set[str]]] = {}
        for tid, _, _, _ in topics:
            rows = s.execute(
                select(Comment.text)
                .where(Comment.topic_id == tid)
                .limit(500)  # хватит для оценки
            ).all()
            comm_texts[int(tid)] = [
                set(clean_for_sentiment((t[0] or "")).lower().split())
                for t in rows if t[0]
            ]

    print(f"=== Бенчмарк тем ({len(topics)} тем) ===\n")

    # diversity
    all_words: list[str] = []
    for tid, _, kws, _ in topics:
        words = [w.strip().lower() for w in (kws or "").split(",")][:top_k]
        all_words.extend(words)
    diversity = len(set(all_words)) / max(len(all_words), 1)
    print(f"Diversity (top-{top_k}): {diversity:.3f}  "
          f"(чем выше, тем меньше тем повторяют слова друг друга)\n")

    # coherence
    print(f"  {'#':>4s} {'size':>6s} {'coherence':>11s}  label")
    coherences = []
    for tid, label, kws, size in topics:
        words = [w.strip().lower() for w in (kws or "").split(",")][:top_k]
        words = [w for w in words if w]
        texts = comm_texts.get(int(tid), [])
        if len(words) < 2 or not texts:
            print(f"  {tid:>4d} {size:>6d} {'—':>11s}  {label}")
            continue
        # для каждой пары слов: доля документов темы, где встречаются ОБА
        n_docs = len(texts)
        pair_scores = []
        for i in range(len(words)):
            for j in range(i + 1, len(words)):
                w1, w2 = words[i], words[j]
                co = sum(1 for doc in texts if w1 in doc and w2 in doc)
                pair_scores.append(co / n_docs)
        coh = sum(pair_scores) / len(pair_scores) if pair_scores else 0
        coherences.append(coh)
        print(f"  {tid:>4d} {size:>6d} {coh:>11.3f}  {label}")

    if coherences:
        print(f"\nMean coherence: {sum(coherences) / len(coherences):.3f}")
    return 0


# ----------------------------------------------------------------------
def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=[
        "sentiment-template", "sentiment", "topics",
    ])
    p.add_argument("--n", type=int, default=200,
                   help="Размер выборки для sentiment-template (default: 200).")
    p.add_argument("--top-k", type=int, default=10,
                   help="Сколько ключевых слов брать на тему (default: 10).")
    args = p.parse_args()

    logging.basicConfig(level=logging.WARNING)

    if args.command == "sentiment-template":
        return make_template(args.n)
    if args.command == "sentiment":
        return evaluate_sentiment()
    if args.command == "topics":
        return evaluate_topics(args.top_k)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
