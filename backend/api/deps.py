"""
FastAPI-зависимости. Пока — единственная: парсинг периода ?start=&end=.

Семантика интервала повторяет data_repo: start включительно, end исключительно.
Обе границы опциональны — None означает «без ограничения».
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fastapi import Query


@dataclass(frozen=True)
class Period:
    start_dt: datetime | None
    end_dt: datetime | None


def get_period(
    start: datetime | None = Query(
        None,
        description="Нижняя граница периода (ISO 8601), включительно.",
        examples=["2026-04-01T00:00:00"],
    ),
    end: datetime | None = Query(
        None,
        description="Верхняя граница периода (ISO 8601), исключительно.",
        examples=["2026-05-01T00:00:00"],
    ),
) -> Period:
    return Period(start_dt=start, end_dt=end)