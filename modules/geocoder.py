"""
Классификатор: текст -> id_района.

API:
    classify_district(text) -> (district_id | None, confidence, debug_info)

Алгоритм:
    1) Текст приводится к нижнему регистру.
    2) Для каждого района считается сумма весов по всем найденным
       подстрокам из словаря district_keywords.
    3) Берётся район с максимальной суммой; если она >= MIN_SCORE
       и опережает второе место в RATIO раз — район присваивается.
    4) Иначе возвращается None (лучше пропустить, чем привязать неверно).

Параметры порогов подобраны эмпирически: при низких порогах ловится
больше комментариев, но растёт доля ошибок; при высоких — наоборот.
Их можно вынести в CLI-флаги при необходимости.
"""
from __future__ import annotations

from dataclasses import dataclass

from modules.district_keywords import DISTRICT_KEYWORDS

# Веса по уровням уверенности
WEIGHTS = {"strong": 3.0, "medium": 1.5, "weak": 0.5}

# Минимальный балл, чтобы вообще присвоить район
MIN_SCORE = 1.0

# Во сколько раз лидер должен опережать второе место
TIEBREAK_RATIO = 1.3


@dataclass
class ClassifyResult:
    district_id: str | None
    confidence: float       # 0..1, нормированная уверенность
    raw_score: float        # абсолютная сумма весов лидера
    matched: list[str]      # какие подстроки сматчились (для отладки)


def classify_district(text: str) -> ClassifyResult:
    """Определить район по тексту."""
    if not text:
        return ClassifyResult(None, 0.0, 0.0, [])

    t = text.lower()
    scores: dict[str, float] = {}
    matched_per_district: dict[str, list[str]] = {}

    for d_id, levels in DISTRICT_KEYWORDS.items():
        s = 0.0
        hits: list[str] = []
        for level, keywords in levels.items():
            w = WEIGHTS[level]
            for kw in keywords:
                if kw in t:
                    s += w
                    hits.append(kw)
        if s > 0:
            scores[d_id] = s
            matched_per_district[d_id] = hits

    if not scores:
        return ClassifyResult(None, 0.0, 0.0, [])

    # сортируем по убыванию
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    leader_id, leader_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0

    if leader_score < MIN_SCORE:
        return ClassifyResult(None, 0.0, leader_score,
                              matched_per_district.get(leader_id, []))

    # Если второй слишком близко — отказываемся (неоднозначно)
    if second_score > 0 and (leader_score / second_score) < TIEBREAK_RATIO:
        return ClassifyResult(None, 0.0, leader_score,
                              matched_per_district.get(leader_id, []))

    # confidence = доля от суммарного веса всех попаданий, ограничена 1.0
    total = sum(scores.values())
    confidence = min(leader_score / total, 1.0)

    return ClassifyResult(
        district_id=leader_id,
        confidence=round(confidence, 3),
        raw_score=leader_score,
        matched=matched_per_district[leader_id],
    )
