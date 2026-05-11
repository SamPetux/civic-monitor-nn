"""
Глобальные пути и константы API.

REPO_ROOT определяется по env CIVIC_REPO_ROOT (выставляется в Dockerfile),
а в локальной разработке — относительно расположения этого файла.
Это позволяет API одинаково работать и в контейнере (/app), и из PyCharm
при запуске `uvicorn backend.api.main:app` из корня репозитория.
"""
from __future__ import annotations

import os
from pathlib import Path


def _detect_repo_root() -> Path:
    env = os.environ.get("CIVIC_REPO_ROOT")
    if env:
        return Path(env).resolve()
    # backend/api/config.py → parents: [api, backend, REPO_ROOT]
    return Path(__file__).resolve().parents[2]


REPO_ROOT: Path = _detect_repo_root()
DATA_DIR: Path = REPO_ROOT / "data"
GEOJSON_PATH: Path = DATA_DIR / "districts.geojson"

# CORS-origin'ы для фронта. В проде заменим на конкретные домены.
ALLOWED_ORIGINS: list[str] = [
    o.strip()
    for o in os.environ.get(
        "CIVIC_CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if o.strip()
]