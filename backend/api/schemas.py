"""
Pydantic-схемы ответов API.

Соответствуют 1:1 dataclass'ам из modules/data_repo.py — это слой сериализации,
никакой логики здесь нет.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


Sentiment = Literal["negative", "neutral", "positive"]


# ---- meta ----------------------------------------------------------------

class DataPeriodOut(BaseModel):
    """Минимальная и максимальная дата записей в БД."""
    start: datetime | None
    end: datetime | None
    is_db_empty: bool


class DistrictRefOut(BaseModel):
    """Справочник: 8 административных районов НН."""
    id: str
    name_ru: str
    name_en: str


# ---- districts -----------------------------------------------------------

class DistrictMetricsOut(BaseModel):
    district_id: str
    name_ru: str
    total_posts: int
    negative: int
    neutral: int
    positive: int
    activity: int
    negativity_score: float = Field(..., description="0..1, sigmoid(z)")
    neg_share: float = Field(..., description="абсолютная доля негатива")
    delta_vs_city: float = Field(..., description="отклонение от среднего по городу")


class CommentOut(BaseModel):
    author: str
    user_id: int
    user_url: str | None
    group: str
    group_url: str | None
    text: str
    sentiment: Sentiment
    score: float
    created_at: datetime
    district_id: str | None
    comment_url: str | None


class SentimentBucketOut(BaseModel):
    """Точка временного ряда тональностей."""
    date: str
    negative: int
    neutral: int
    positive: int


# ---- topics --------------------------------------------------------------

class TopicOut(BaseModel):
    topic_id: int
    label: str
    keywords: str
    count: int
    neg_share: float


class BurstOut(BaseModel):
    date: datetime
    topic_label: str
    volume: int
    z_score: float
    intensity: str
    neg_share: float | None


# ---- users ---------------------------------------------------------------

class TopUserOut(BaseModel):
    user_id: int
    name: str
    user_url: str
    comments_in_period: int
    avg_sentiment: float
    districts: list[str]
    suspected_bot: bool