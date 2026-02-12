"""
Загрузка конфигурации из .env и общие пути проекта.

Использование:
    from modules.config import VK_TOKEN, DB_URL
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# --- VK ---
VK_TOKEN: str | None = os.getenv("VK_TOKEN")

# --- БД ---
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "posts.db"
DB_URL = f"sqlite:///{DB_PATH}"


def require_token() -> str:
    """Гарантированно вернуть токен или упасть с понятным сообщением."""
    if not VK_TOKEN or VK_TOKEN == "your_token_here":
        raise RuntimeError(
            "VK_TOKEN не задан. Скопируйте .env.example в .env "
            "и пропишите туда реальный токен — см. инструкцию в .env.example."
        )
    return VK_TOKEN
