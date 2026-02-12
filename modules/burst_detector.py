"""
Детектор всплесков обсуждений по парам (тема × район).

Алгоритм:
  Для каждого временного ряда volume_t (число сообщений в день):
    1) Считаем скользящие μ и σ по предыдущим WINDOW дням
       (текущий день не входит в окно, чтобы не размывать всплеск).
    2) z_t = (volume_t - μ) / max(σ, MIN_STD)
       MIN_STD защищает от деления на ~0 для редко обсуждаемых пар.
    3) День считается всплеском, если:
         z_t >= Z_THRESHOLD И volume_t >= MIN_VOLUME
       MIN_VOLUME отсекает шум "обычно 0, сегодня 1 = z=∞".
    4) Интенсивность кодируется по порогам Z_LOW/MED/HIGH.

Возвращается список объектов BurstCandidate. Запись в БД — задача CLI.

Параметры подобраны под 30-дневную выборку. Для более длинных периодов
WINDOW можно увеличить до 21-28 дней.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date, timedelta
from typing import Iterable

import numpy as np

_ONE_DAY = timedelta(days=1)

# --- параметры по умолчанию ---
WINDOW = 14            # длина базисного окна, дни
Z_THRESHOLD = 2.5      # минимальный z-score для всплеска
MIN_VOLUME = 5         # минимум сообщений в день — защита от низкочастотных шумов
MIN_STD = 1.0          # пол для σ — иначе z взрывается
Z_LOW, Z_MED, Z_HIGH = 2.5, 4.0, 6.0


@dataclass
class BurstCandidate:
    topic_id: int
    district_id: str | None
    day: _date
    volume: int
    baseline_mean: float
    baseline_std: float
    z_score: float
    intensity: str
    neg_share: float | None  # доля negative-сообщений в этот день, если есть


def _intensity_label(z: float) -> str:
    if z >= Z_HIGH:
        return "high"
    if z >= Z_MED:
        return "medium"
    return "low"


def detect_bursts_in_series(
    topic_id: int,
    district_id: str | None,
    series: list[tuple[_date, int, float | None]],
    *,
    window: int = WINDOW,
    z_threshold: float = Z_THRESHOLD,
    min_volume: int = MIN_VOLUME,
) -> list[BurstCandidate]:
    """
    Найти всплески в одном временном ряду.
    series — список (день, объём, доля_негатива). Должен идти в
    хронологическом порядке без пропусков (нулевые дни должны
    присутствовать как (day, 0, None)).
    """
    if len(series) < window + 1:
        return []

    days     = [s[0] for s in series]
    volumes  = np.array([s[1] for s in series], dtype=float)
    neg_share = [s[2] for s in series]

    out: list[BurstCandidate] = []
    for i in range(window, len(volumes)):
        baseline = volumes[i - window:i]
        mu = float(baseline.mean())
        sd = max(float(baseline.std(ddof=0)), MIN_STD)
        z = (volumes[i] - mu) / sd
        if z >= z_threshold and volumes[i] >= min_volume:
            out.append(BurstCandidate(
                topic_id=topic_id,
                district_id=district_id,
                day=days[i],
                volume=int(volumes[i]),
                baseline_mean=round(mu, 2),
                baseline_std=round(sd, 2),
                z_score=round(z, 2),
                intensity=_intensity_label(z),
                neg_share=neg_share[i],
            ))
    return out


def fill_daily_gaps(
    rows: Iterable[tuple[_date, int, float | None]],
    start: _date,
    end: _date,
) -> list[tuple[_date, int, float | None]]:
    """
    Дополнить временной ряд нулевыми днями.
    Без этого алгоритм недооценивает всплески: пропущенные дни
    означают volume=0, а если их пропустить, базисное окно сдвинется
    и μ окажется завышенным.
    """
    by_day = {d: (v, n) for d, v, n in rows}
    out: list[tuple[_date, int, float | None]] = []
    cur = start
    while cur <= end:
        if cur in by_day:
            v, n = by_day[cur]
            out.append((cur, v, n))
        else:
            out.append((cur, 0, None))
        cur += _ONE_DAY
    return out
