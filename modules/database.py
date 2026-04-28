"""
Схема БД проекта.
Поддерживает PostgreSQL (продакшн) и SQLite (локальная разработка).
Миграции структуры — через Alembic (см. alembic/).

Таблицы:
  groups   — VK-сообщества, которые мы парсим. Привязаны к району
             (или None для общегородских пабликов).
  posts    — посты со стен групп.
  comments — комментарии к постам. Сюда же позже допишутся sentiment
             и тема (topic_id) — поля заведены заранее, чтобы не делать
             миграции при подключении следующего блока.
  users    — авторы комментариев. Заполняется отдельным шагом
             (vk_parser.enrich_users) для топа авторов и фильтра ботов.

Использование:
    from modules.database import init_db, get_session, Group, Post, Comment

    init_db()
    with get_session() as s:
        s.add(...)
        s.commit()
"""


from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Float, ForeignKey,
    Integer, String, Text, UniqueConstraint, create_engine, text,
)
from sqlalchemy.orm import (
    DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker, Session,
)
from sqlalchemy import inspect as sa_inspect

from modules.config import DB_URL, IS_POSTGRES


class Base(DeclarativeBase):
    pass


# ----------------------------------------------------------------------
class Group(Base):
    __tablename__ = "groups"

    id:             Mapped[int]           = mapped_column(primary_key=True)
    vk_id:          Mapped[int]           = mapped_column(BigInteger, unique=True)
    screen_name:    Mapped[str]           = mapped_column(String(100), unique=True)
    name:           Mapped[Optional[str]] = mapped_column(String(255))
    district_id:    Mapped[Optional[str]] = mapped_column(String(50), index=True)
    is_local:       Mapped[bool]          = mapped_column(Boolean, default=True)
    members_count:  Mapped[Optional[int]] = mapped_column(Integer)
    last_parsed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    posts: Mapped[list["Post"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )


# ----------------------------------------------------------------------
class Post(Base):
    __tablename__ = "posts"

    id:               Mapped[int]           = mapped_column(primary_key=True)
    group_id:         Mapped[int]           = mapped_column(ForeignKey("groups.id"), index=True)
    vk_post_id:       Mapped[int]           = mapped_column(BigInteger, unique=True)
    owner_id:         Mapped[Optional[int]] = mapped_column(BigInteger)
    from_id:          Mapped[Optional[int]] = mapped_column(BigInteger)
    date:             Mapped[Optional[datetime]] = mapped_column(DateTime, index=True)
    text:             Mapped[Optional[str]] = mapped_column(Text)
    likes_count:      Mapped[Optional[int]] = mapped_column(Integer)
    reposts_count:    Mapped[Optional[int]] = mapped_column(Integer)
    comments_count:   Mapped[Optional[int]] = mapped_column(Integer)
    views_count:      Mapped[Optional[int]] = mapped_column(Integer)
    is_pinned:        Mapped[bool]          = mapped_column(Boolean, default=False)
    collected_at:     Mapped[Optional[datetime]] = mapped_column(DateTime)

    # аналитика
    sentiment:          Mapped[Optional[str]]   = mapped_column(String(20))
    sentiment_score:    Mapped[Optional[float]] = mapped_column(Float)
    topic_id:           Mapped[Optional[int]]   = mapped_column(Integer)
    district_id:        Mapped[Optional[str]]   = mapped_column(String(50), index=True)
    district_confidence: Mapped[Optional[float]] = mapped_column(Float)

    group:    Mapped["Group"]         = relationship(back_populates="posts")
    comments: Mapped[list["Comment"]] = relationship(
        back_populates="post", cascade="all, delete-orphan"
    )


# ----------------------------------------------------------------------
class Comment(Base):
    __tablename__ = "comments"

    id:               Mapped[int]           = mapped_column(primary_key=True)
    post_id:          Mapped[int]           = mapped_column(ForeignKey("posts.id"), index=True)
    vk_comment_id:    Mapped[int]           = mapped_column(BigInteger, unique=True)
    from_id:          Mapped[Optional[int]] = mapped_column(BigInteger, index=True)
    date:             Mapped[Optional[datetime]] = mapped_column(DateTime, index=True)
    text:             Mapped[Optional[str]] = mapped_column(Text)
    likes_count:      Mapped[Optional[int]] = mapped_column(Integer)
    replies_count:    Mapped[Optional[int]] = mapped_column(Integer)
    parent_id:        Mapped[Optional[int]] = mapped_column(BigInteger)
    collected_at:     Mapped[Optional[datetime]] = mapped_column(DateTime)

    # аналитика
    sentiment:           Mapped[Optional[str]]   = mapped_column(String(20))
    sentiment_score:     Mapped[Optional[float]] = mapped_column(Float)
    topic_id:            Mapped[Optional[int]]   = mapped_column(Integer)
    district_id:         Mapped[Optional[str]]   = mapped_column(String(50), index=True)
    district_confidence: Mapped[Optional[float]] = mapped_column(Float)

    post: Mapped["Post"] = relationship(back_populates="comments")


# ----------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id:           Mapped[int]           = mapped_column(primary_key=True)
    vk_user_id:   Mapped[int]           = mapped_column(BigInteger, unique=True)
    first_name:   Mapped[Optional[str]] = mapped_column(String(100))
    last_name:    Mapped[Optional[str]] = mapped_column(String(100))
    screen_name:  Mapped[Optional[str]] = mapped_column(String(100))
    is_closed:    Mapped[Optional[bool]] = mapped_column(Boolean)
    is_excluded:  Mapped[bool]          = mapped_column(Boolean, default=False)
    collected_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


# ----------------------------------------------------------------------
class Topic(Base):
    __tablename__ = "topics"

    id:         Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    label:      Mapped[str] = mapped_column(String(255))
    keywords:   Mapped[str] = mapped_column(Text)
    size:       Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ----------------------------------------------------------------------
class Burst(Base):
    __tablename__ = "bursts"
    __table_args__ = (
        UniqueConstraint(
            "topic_id", "district_id", "date",
            name="uq_burst_topic_district_date"
        ),
    )

    id:            Mapped[int]           = mapped_column(primary_key=True)
    topic_id:      Mapped[int]           = mapped_column(ForeignKey("topics.id"), index=True)
    district_id:   Mapped[Optional[str]] = mapped_column(String(50), index=True)
    date:          Mapped[datetime]      = mapped_column(DateTime, index=True)
    volume:        Mapped[int]           = mapped_column(Integer)
    baseline_mean: Mapped[float]         = mapped_column(Float)
    baseline_std:  Mapped[float]         = mapped_column(Float)
    z_score:       Mapped[float]         = mapped_column(Float)
    intensity:     Mapped[str]           = mapped_column(String(10))
    neg_share:     Mapped[Optional[float]] = mapped_column(Float)


# ----------------------------------------------------------------------
# Engine / Session
# ----------------------------------------------------------------------
def _make_engine():
    kwargs = {"echo": False, "future": True}
    if IS_POSTGRES:
        # Пул соединений для продакшна
        kwargs.update({
            "pool_size": 10,
            "max_overflow": 20,
            "pool_pre_ping": True,   # проверять живость соединений
            "pool_recycle": 1800,    # пересоздавать через 30 мин
        })
    return create_engine(DB_URL, **kwargs)


_engine = _make_engine()
_SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)


def _migrate_schema() -> None:
    """
    Лёгкая миграция: добавляет недостающие колонки через ALTER TABLE.
    Работает на SQLite и PostgreSQL одинаково через SQLAlchemy Inspector.
    Для крупных изменений схемы используйте Alembic.
    """
    inspector = sa_inspect(_engine)
    existing_tables = inspector.get_table_names()

    expected: dict[str, list[tuple[str, str]]] = {
        "posts": [
            ("district_confidence", "FLOAT"),
            ("sentiment",           "VARCHAR(20)"),
            ("sentiment_score",     "FLOAT"),
            ("topic_id",            "INTEGER"),
            ("district_id",         "VARCHAR(50)"),
        ],
        "comments": [
            ("district_confidence", "FLOAT"),
            ("sentiment",           "VARCHAR(20)"),
            ("sentiment_score",     "FLOAT"),
            ("topic_id",            "INTEGER"),
            ("district_id",         "VARCHAR(50)"),
        ],
    }

    with _engine.begin() as conn:
        for table, cols in expected.items():
            if table not in existing_tables:
                continue
            present = {
                col["name"]
                for col in inspector.get_columns(table)
            }
            for col_name, col_type in cols:
                if col_name not in present:
                    conn.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
                    )


def init_db() -> None:
    """Создать таблицы (если нет) и применить лёгкие миграции."""
    Base.metadata.create_all(_engine)
    _migrate_schema()


def get_session() -> Session:
    return _SessionLocal()
