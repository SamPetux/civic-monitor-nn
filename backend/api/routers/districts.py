from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from modules import data_repo
from ..deps import Period, get_period
from ..schemas import (
    DistrictMetricsOut, CommentOut, SentimentBucketOut, TopicOut, BurstOut,
)

router = APIRouter(prefix="/api/districts", tags=["districts"])

CITY = "_city"  # псевдо-id для запросов по всему городу


def _district_id_or_none(district_id: str) -> str | None:
    return None if district_id == CITY else district_id


@router.get("/metrics", response_model=list[DistrictMetricsOut])
def district_metrics(period: Period = Depends(get_period)):
    rows = data_repo.get_district_metrics(
        start_dt=period.start_dt, end_dt=period.end_dt,
    )
    return [DistrictMetricsOut(**r.__dict__) for r in rows]


@router.get("/{district_id}/comments", response_model=list[CommentOut])
def district_comments(
    district_id: str,
    period: Period = Depends(get_period),
    sentiment: str | None = Query(None, description="negative | neutral | positive"),
    limit: int = Query(50, ge=1, le=200),
    exclude_users: str | None = Query(
        None, description="Через запятую: user_id,user_id,...",
    ),
):
    excluded: set[int] = set()
    if exclude_users:
        for part in exclude_users.split(","):
            part = part.strip()
            if part.isdigit():
                excluded.add(int(part))

    did = _district_id_or_none(district_id)
    if did is None:
        raise HTTPException(400, "Для комментариев нужен конкретный район")

    rows = data_repo.get_recent_comments(
        did,
        start_dt=period.start_dt,
        end_dt=period.end_dt,
        limit=limit,
        sentiment=sentiment,
        excluded_user_ids=excluded,
    )
    return [CommentOut(**r.__dict__) for r in rows]


@router.get("/{district_id}/sentiment", response_model=list[SentimentBucketOut])
def district_sentiment(
    district_id: str,
    period: Period = Depends(get_period),
    bucket: str = Query("day", description="day | hour"),
):
    did = _district_id_or_none(district_id)
    if did is None:
        raise HTTPException(400, "Для timeseries нужен конкретный район")
    rows = data_repo.get_sentiment_timeseries(
        did, start_dt=period.start_dt, end_dt=period.end_dt, bucket=bucket,
    )
    return [SentimentBucketOut(**r) for r in rows]


@router.get("/{district_id}/topics", response_model=list[TopicOut])
def district_topics(
    district_id: str,
    period: Period = Depends(get_period),
    limit: int = Query(5, ge=1, le=20),
):
    did = _district_id_or_none(district_id)
    rows = data_repo.get_top_topics(
        did, start_dt=period.start_dt, end_dt=period.end_dt, limit=limit,
    )
    return [TopicOut(**r.__dict__) for r in rows]


@router.get("/{district_id}/bursts", response_model=list[BurstOut])
def district_bursts(
    district_id: str,
    period: Period = Depends(get_period),
    limit: int = Query(10, ge=1, le=50),
):
    did = _district_id_or_none(district_id)
    rows = data_repo.get_bursts(
        did, start_dt=period.start_dt, end_dt=period.end_dt, limit=limit,
    )
    return [BurstOut(**r.__dict__) for r in rows]


@router.get("/{district_id}/heatmap")
def district_heatmap(
    district_id: str,
    period: Period = Depends(get_period),
    top_n: int = Query(8, ge=2, le=20),
):
    """
    Возвращает данные для heatmap «тема × день».
    Формат: { topics: [...], dates: [...], matrix: [[int,...], ...] }
    matrix[i][j] — число сообщений по теме i в день j.
    """
    did = _district_id_or_none(district_id)
    topics, dates, matrix = data_repo.get_topic_day_heatmap(
        did,
        start_dt=period.start_dt,
        end_dt=period.end_dt,
        top_n_topics=top_n,
    )
    return {"topics": topics, "dates": dates, "matrix": matrix}