"""
Схема БД проекта (SQLite через SQLAlchemy 2.x).

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
    Integer, String, Text, UniqueConstraint, create_engine, select,
)
from sqlalchemy.orm import (
    DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker, Session,
)

from modules.config import DB_URL


class Base(DeclarativeBase):
    pass


# ----------------------------------------------------------------------
class Group(Base):
    """VK-сообщество, которое мы мониторим."""
    __tablename__ = "groups"

    id:            Mapped[int]            = mapped_column(primary_key=True)
    vk_id:         Mapped[int]            = mapped_column(BigInteger, unique=True)
    screen_name:   Mapped[str]            = mapped_column(String(100), unique=True)
    name:          Mapped[Optional[str]]  = mapped_column(String(255))
    # district_id == None для общегородских пабликов
    district_id:   Mapped[Optional[str]]  = mapped_column(String(50), index=True)
    is_local:      Mapped[bool]           = mapped_column(Boolean, default=True)
    members_count: Mapped[Optional[int]]  = mapped_column(Integer)
    last_parsed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    posts: Mapped[list["Post"]] = relationship(back_populates="group",
                                               cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Group {self.screen_name} ({self.name})>"


# ----------------------------------------------------------------------
class Post(Base):
    """Пост со стены группы."""
    __tablename__ = "posts"
    __table_args__ = (
        UniqueConstraint("vk_id", "group_id", name="uq_post_vk_group"),
    )

    id:            Mapped[int]            = mapped_column(primary_key=True)
    vk_id:         Mapped[int]            = mapped_column(BigInteger, index=True)
    group_id:      Mapped[int]            = mapped_column(ForeignKey("groups.id"), index=True)
    author_vk_id:  Mapped[Optional[int]]  = mapped_column(BigInteger)
    text:          Mapped[str]            = mapped_column(Text, default="")
    date:          Mapped[datetime]       = mapped_column(DateTime, index=True)
    likes:         Mapped[int]            = mapped_column(Integer, default=0)
    reposts:       Mapped[int]            = mapped_column(Integer, default=0)
    comments_count: Mapped[int]           = mapped_column(Integer, default=0)
    # Унаследовано от группы (для local), для city-групп будет переопределено
    # этапом геокодинга по тексту поста.
    district_id:   Mapped[Optional[str]]  = mapped_column(String(50), index=True)
    # Уверенность геокодера, если район присвоен по тексту (0..1).
    # Для постов из локальных групп остаётся None (район унаследован, не вычислен).
    district_confidence: Mapped[Optional[float]] = mapped_column(Float)

    # Поля под sentiment / topic — заполняются отдельными этапами.
    sentiment:       Mapped[Optional[str]]   = mapped_column(String(20), index=True)
    sentiment_score: Mapped[Optional[float]] = mapped_column(Float)
    topic_id:        Mapped[Optional[int]]   = mapped_column(Integer, index=True)

    group:    Mapped["Group"]              = relationship(back_populates="posts")
    comments: Mapped[list["Comment"]]      = relationship(back_populates="post",
                                                          cascade="all, delete-orphan")


# ----------------------------------------------------------------------
class Comment(Base):
    """Комментарий к посту."""
    __tablename__ = "comments"
    __table_args__ = (
        UniqueConstraint("vk_id", "post_id", name="uq_comment_vk_post"),
    )

    id:            Mapped[int]            = mapped_column(primary_key=True)
    vk_id:         Mapped[int]            = mapped_column(BigInteger, index=True)
    post_id:       Mapped[int]            = mapped_column(ForeignKey("posts.id"), index=True)
    author_vk_id:  Mapped[Optional[int]]  = mapped_column(BigInteger, index=True)
    text:          Mapped[str]            = mapped_column(Text, default="")
    date:          Mapped[datetime]       = mapped_column(DateTime, index=True)
    likes:         Mapped[int]            = mapped_column(Integer, default=0)
    parent_comment_vk_id: Mapped[Optional[int]] = mapped_column(BigInteger)

    # Поля заведены заранее под следующие блоки:
    sentiment:       Mapped[Optional[str]]   = mapped_column(String(20), index=True)
    sentiment_score: Mapped[Optional[float]] = mapped_column(Float)
    topic_id:        Mapped[Optional[int]]   = mapped_column(Integer, index=True)
    district_id:     Mapped[Optional[str]]   = mapped_column(String(50), index=True)
    # Уверенность геокодера; None, если район унаследован от поста/группы.
    district_confidence: Mapped[Optional[float]] = mapped_column(Float)

    post: Mapped["Post"] = relationship(back_populates="comments")


# ----------------------------------------------------------------------
class User(Base):
    """
    Автор комментариев. Заполняется отдельным шагом enrich_users:
    после парсинга комментариев батчами вытягиваются профили из users.get
    и пишутся сюда. Поле is_excluded используется в UI для исключения
    подозрительных аккаунтов из агрегатов на карте.
    """
    __tablename__ = "users"

    id:           Mapped[int]            = mapped_column(primary_key=True)
    vk_id:        Mapped[int]            = mapped_column(BigInteger, unique=True)
    first_name:   Mapped[Optional[str]]  = mapped_column(String(100))
    last_name:    Mapped[Optional[str]]  = mapped_column(String(100))
    screen_name:  Mapped[Optional[str]]  = mapped_column(String(100))
    is_closed:    Mapped[Optional[bool]] = mapped_column(Boolean)
    is_excluded:  Mapped[bool]           = mapped_column(Boolean, default=False)


# ----------------------------------------------------------------------
class Topic(Base):
    """
    Тема, найденная BERTopic. Заполняется analyze_topics.py.
    Поле id здесь == номер темы в BERTopic (положительное число).
    Тема -1 (шум) в эту таблицу не пишется, у комментариев topic_id
    остаётся NULL.
    """
    __tablename__ = "topics"

    id:          Mapped[int]            = mapped_column(primary_key=True, autoincrement=False)
    label:       Mapped[str]            = mapped_column(String(255))
    keywords:    Mapped[str]            = mapped_column(Text)        # топ-10 слов через ", "
    size:        Mapped[int]            = mapped_column(Integer)     # сколько текстов в теме
    created_at:  Mapped[datetime]       = mapped_column(DateTime, default=datetime.utcnow)


# ----------------------------------------------------------------------
class Burst(Base):
    """
    Обнаруженный всплеск активности по конкретной теме в конкретном районе
    в конкретный день. Заполняется detect_bursts.py.

    Один день (topic_id, district_id, date) даёт максимум одну запись —
    UniqueConstraint защищает от дублей при повторном прогоне.
    district_id может быть NULL — это всплеск 'по всему городу'
    без географической привязки.
    """
    __tablename__ = "bursts"
    __table_args__ = (
        UniqueConstraint("topic_id", "district_id", "date",
                         name="uq_burst_topic_district_date"),
    )

    id:            Mapped[int]            = mapped_column(primary_key=True)
    topic_id:      Mapped[int]            = mapped_column(ForeignKey("topics.id"), index=True)
    district_id:   Mapped[Optional[str]]  = mapped_column(String(50), index=True)
    date:          Mapped[datetime]       = mapped_column(DateTime, index=True)

    volume:        Mapped[int]            = mapped_column(Integer)        # сообщений в этот день
    baseline_mean: Mapped[float]          = mapped_column(Float)
    baseline_std:  Mapped[float]          = mapped_column(Float)
    z_score:       Mapped[float]          = mapped_column(Float)
    intensity:     Mapped[str]            = mapped_column(String(10))     # low/medium/high

    # доля негатива в этот день — полезно для пары "Pattern 1: всплеск + негатив"
    neg_share:     Mapped[Optional[float]] = mapped_column(Float)


# ----------------------------------------------------------------------
# Engine / Session
# ----------------------------------------------------------------------
_engine = create_engine(DB_URL, echo=False, future=True)
_SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)


def _existing_columns(conn, table: str) -> set[str]:
    rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").all()
    return {row[1] for row in rows}


def _migrate_schema() -> None:
    """
    Лёгкая миграция: проверяет наличие новых колонок и добавляет
    их через ALTER TABLE, не пересоздавая БД. Нужна, если код
    обновился на машине, где БД уже наполнена данными.
    """
    expected: dict[str, list[tuple[str, str]]] = {
        "posts": [
            ("district_confidence", "FLOAT"),
            ("sentiment",           "VARCHAR(20)"),
            ("sentiment_score",     "FLOAT"),
            ("topic_id",            "INTEGER"),
        ],
        "comments": [
            ("district_confidence", "FLOAT"),
        ],
    }
    with _engine.begin() as conn:
        # таблицы могут ещё не существовать — пропустим
        existing_tables = {
            row[0] for row in conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).all()
        }
        for table, cols in expected.items():
            if table not in existing_tables:
                continue
            present = _existing_columns(conn, table)
            for col, sql_type in cols:
                if col not in present:
                    conn.exec_driver_sql(
                        f"ALTER TABLE {table} ADD COLUMN {col} {sql_type}"
                    )


def init_db() -> None:
    """Создать таблицы, если их ещё нет, и применить лёгкие миграции."""
    Base.metadata.create_all(_engine)
    _migrate_schema()


def get_session() -> Session:
    """Получить новую сессию. Закрывать вручную или через with-блок."""
    return _SessionLocal()
