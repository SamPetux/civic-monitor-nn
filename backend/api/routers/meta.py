"""Справочные эндпоинты: период данных в БД и список районов."""
from __future__ import annotations

from fastapi import APIRouter

from modules import data_repo
from modules.districts import DISTRICTS

from ..schemas import DataPeriodOut, DistrictRefOut


router = APIRouter(prefix="/api/meta", tags=["meta"])


@router.get("/period", response_model=DataPeriodOut, summary="Период данных в БД")
def data_period() -> DataPeriodOut:
    """
    Возвращает min и max дату из таблиц posts/comments плюс флаг пустоты БД.
    Фронт использует это, чтобы инициализировать пикер периода (по умолчанию
    — последние 7 дней, но не ранее start и не позже end).
    """
    period = data_repo.get_data_period()
    is_empty = data_repo.is_db_empty()
    if period is None:
        return DataPeriodOut(start=None, end=None, is_db_empty=is_empty)
    start, end = period
    return DataPeriodOut(start=start, end=end, is_db_empty=is_empty)


@router.get("/districts", response_model=list[DistrictRefOut], summary="Справочник районов")
def districts_ref() -> list[DistrictRefOut]:
    """Каноничный порядок 8 районов НН — используется для меню и легенды."""
    return [DistrictRefOut(**d) for d in DISTRICTS]