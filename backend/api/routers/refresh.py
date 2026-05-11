from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from modules.refresh_runner import (
    cancel_refresh, clear_last_result, get_status, start_refresh,
)

router = APIRouter(prefix="/api/refresh", tags=["refresh"])


class RefreshStartRequest(BaseModel):
    hours: int | None = None
    days: int | None = None
    max_posts: int = 50


class RefreshStatusOut(BaseModel):
    is_running: bool
    pid: int | None
    started_at: float | None
    last_result: str | None   # "done" | "failed" | None
    log_tail: str | None


@router.post("/start", summary="Запустить фоновое обновление данных")
def refresh_start(req: RefreshStartRequest):
    status = get_status()
    if status.is_running:
        raise HTTPException(409, "Обновление уже запущено")
    ok, msg = start_refresh(
        hours=req.hours,
        days=req.days,
        max_posts=req.max_posts,
    )
    if not ok:
        raise HTTPException(500, detail=msg)
    return {"ok": True, "message": msg}


@router.get("/status", response_model=RefreshStatusOut)
def refresh_status():
    s = get_status()
    return RefreshStatusOut(
        is_running=s.is_running,
        pid=s.pid,
        started_at=s.started_at,
        last_result=s.last_result,
        log_tail=s.log_tail,
    )


@router.post("/cancel", summary="Остановить фоновое обновление")
def refresh_cancel():
    ok, msg = cancel_refresh()
    return {"ok": ok, "message": msg}


@router.post("/clear", summary="Сбросить last_result после прочтения")
def refresh_clear():
    clear_last_result()
    return {"ok": True}