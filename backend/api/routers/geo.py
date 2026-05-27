"""Геоданные — отдача GeoJSON районов как статики."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..config import GEOJSON_PATH


router = APIRouter(prefix="/api/geo", tags=["geo"])


@router.get(
    "/districts",
    summary="GeoJSON границ районов",
    responses={
        200: {"content": {"application/geo+json": {}}},
        404: {"description": "districts.geojson не найден"},
    },
)
def districts_geojson() -> FileResponse:
    """
    Возвращает data/districts.geojson — границы 8 районов в формате FeatureCollection.
    Фронт грузит его один раз при инициализации карты MapLibre.
    """
    if not GEOJSON_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                f"GeoJSON не найден: {GEOJSON_PATH}. "
                "Запустите `python prepare_data.py` в корне репозитория."
            ),
        )
    return FileResponse(
        GEOJSON_PATH,
        media_type="application/geo+json",
        filename="districts.geojson",
    )