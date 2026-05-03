"""
Загрузка конфигурации из .env и общие пути проекта.
Поддерживает PostgreSQL (продакшн) и SQLite (локальная разработка).
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=False)

# --- VK ---
VK_TOKEN: str | None = os.getenv("VK_TOKEN")

# --- БД ---
# DATA_DIR нужен всегда — для refresh.lock, refresh.result и других файлов платформы
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

# Приоритет: DATABASE_URL (Postgres) → собираем из частей → SQLite fallback
DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)
    DB_URL = DATABASE_URL
else:
    PG_HOST = os.getenv("POSTGRES_HOST")
    PG_PORT = os.getenv("POSTGRES_PORT", "5432")
    PG_DB   = os.getenv("POSTGRES_DB")
    PG_USER = os.getenv("POSTGRES_USER")
    PG_PASS = os.getenv("POSTGRES_PASSWORD")

    if all([PG_HOST, PG_DB, PG_USER, PG_PASS]):
        DB_URL = (
            f"postgresql+psycopg2://{PG_USER}:{PG_PASS}"
            f"@{PG_HOST}:{PG_PORT}/{PG_DB}"
        )
    else:
        # SQLite fallback для локальной разработки без Postgres
        DB_PATH = DATA_DIR / "posts.db"
        DB_URL = f"sqlite:///{DB_PATH}"

IS_POSTGRES = DB_URL.startswith("postgresql")
IS_SQLITE   = DB_URL.startswith("sqlite")


def require_token() -> str:
    if not VK_TOKEN or VK_TOKEN == "your_token_here":
        raise RuntimeError(
            "VK_TOKEN не задан. Скопируйте .env.example в .env "
            "и пропишите туда реальный токен."
        )
    return VK_TOKEN