from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from modules import data_repo
from ..deps import Period, get_period
from ..schemas import TopUserOut

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/top", response_model=list[TopUserOut])
def top_users(
    period: Period = Depends(get_period),
    limit: int = Query(30, ge=1, le=100),
):
    rows = data_repo.get_top_users(
        start_dt=period.start_dt, end_dt=period.end_dt, limit=limit,
    )
    return [TopUserOut(**r.__dict__) for r in rows]