"""Справочные эндпоинты: период данных, список районов, список групп."""
from __future__ import annotations

from fastapi import APIRouter, Query

from modules import data_repo
from modules.districts import DISTRICTS

from ..schemas import DataPeriodOut, DistrictRefOut, GroupOut


router = APIRouter(prefix="/api/meta", tags=["meta"])


@router.get("/period", response_model=DataPeriodOut)
def data_period() -> DataPeriodOut:
    period = data_repo.get_data_period()
    is_empty = data_repo.is_db_empty()
    if period is None:
        return DataPeriodOut(start=None, end=None, is_db_empty=is_empty)
    start, end = period
    return DataPeriodOut(start=start, end=end, is_db_empty=is_empty)


@router.get("/districts", response_model=list[DistrictRefOut])
def districts_ref() -> list[DistrictRefOut]:
    return [DistrictRefOut(**d) for d in DISTRICTS]


@router.get("/groups", response_model=list[GroupOut])
def groups_list(
    district_id: str | None = Query(None, description="Фильтр по району"),
) -> list[GroupOut]:
    rows = data_repo.get_groups(district_id=district_id)
    return [GroupOut(**r.__dict__) for r in rows]