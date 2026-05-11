"""
Civic Monitor НН — REST API.

Запуск локально (из корня репозитория):
    uvicorn backend.api.main:app --reload --host 0.0.0.0 --port 8000

Swagger:    http://localhost:8000/docs
ReDoc:      http://localhost:8000/redoc
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from modules.database import init_db

from .config import ALLOWED_ORIGINS
from .routers import districts, geo, meta, refresh, reports, users

import json
from fastapi.responses import JSONResponse


log = logging.getLogger("civic.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("API запускается, инициализируем схему БД…")
    init_db()
    log.info("Схема БД готова.")
    yield
    log.info("API остановлен.")


class UTF8JSONResponse(JSONResponse):
    """FastAPI по умолчанию использует ensure_ascii=True.
    Этот класс отключает экранирование — кириллица идёт как есть."""
    def render(self, content) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            indent=None,
            separators=(",", ":"),
        ).encode("utf-8")


app = FastAPI(
    title="Civic Monitor НН — API",
    description=(
        "REST API над modules/data_repo.py: метрики районов, тональности, "
        "темы, всплески, топ-авторы, PDF-отчёты, фоновое обновление данных."
    ),
    version="1.0.0",
    lifespan=lifespan,
    default_response_class=UTF8JSONResponse,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Роутеры
app.include_router(meta.router)
app.include_router(geo.router)
app.include_router(districts.router)
app.include_router(users.router)
app.include_router(reports.router)
app.include_router(refresh.router)


@app.get("/health", tags=["meta"], summary="Liveness probe")
def health() -> dict[str, str]:
    return {"status": "ok"}