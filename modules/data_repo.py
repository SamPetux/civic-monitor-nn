"""
Слой данных для UI: запросы к БД с фильтром по периоду.

Изменения:
  • CommentRow и TopUserRow теперь несут vk_id-поля для ссылок.
  • DistrictMetrics.negativity_score — это z-score отклонения доли
    негатива от средней по городу. Так районы с заметным локальным
    всплеском подсвечиваются красным, даже если абсолютная доля
    негатива в обоих районах ~20%.
  • Поддержка блок-листа topic_id (TOPIC_BLOCKLIST_KEYWORDS) — темы,
    у которых ключевые слова матчатся, исключаются из аналитики.
  • Все функции принимают datetime с точностью до часа/минуты —
    фильтр "последние N часов" работает без изменений в схеме.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import case, func, not_, select

from modules.database import (
    Burst, Comment, Group, Post, Topic, User, get_session,
)
from modules.districts import DISTRICT_BY_ID, DISTRICTS


# ----------------------------------------------------------------------
# Темы-шум: ключевые слова, по которым выкидываем "общеновостные"
# темы, не несущие информации о районной повестке.
# Тема исключается, если хотя бы одно её ключевое слово совпадает
# (полное равенство токена) с этим списком.
# ----------------------------------------------------------------------
TOPIC_BLOCKLIST_KEYWORDS = {
    # шум новостных рассылок и подписок
    "max", "макс", "мах", "alex",
    "канале", "канал", "канала",
    "подпис", "подписаться", "подписывайтесь", "подписка",
    "новостей", "новости", "источник",
    "россии", "россия", "рф", "россию",
    #"телеграм", "телеграмм", "tg",
    "ссылка", "ссылку", "сайт",
    "вопрос", "добрый", "больше", "лет",
    #"вопрос",

    "erid", "инн", "студии", "com", "реклама", # реклама
    #"владимирович", "алексеевич", "ульянова", имена из рекламных текстов
    #"мужское", "женское",
}


# ----------------------------------------------------------------------
# Структуры
# ----------------------------------------------------------------------
@dataclass
class DistrictMetrics:
    district_id: str
    name_ru: str
    total_posts: int
    negative: int
    neutral: int
    positive: int
    activity: int
    negativity_score: float       # 0..1 — итоговый "градус" района
    neg_share: float              # абсолютная доля негатива (для подписей)
    delta_vs_city: float          # (district_neg - city_neg), +/-

    @property
    def neg_share_legacy(self) -> float:
        # сохраняем для обратной совместимости со старым UI
        return self.negative / max(self.total_posts, 1)


@dataclass
class CommentRow:
    author: str
    user_id: int
    user_url: str | None       # ссылка на профиль VK
    group: str
    group_url: str | None
    text: str
    sentiment: str
    score: float
    created_at: datetime
    district_id: str | None
    comment_url: str | None    # ссылка прямо на комментарий


@dataclass
class TopicRow:
    topic_id: int
    label: str
    keywords: str
    count: int
    neg_share: float


@dataclass
class BurstRow:
    date: datetime
    topic_label: str
    volume: int
    z_score: float
    intensity: str
    neg_share: float | None


@dataclass
class TopUserRow:
    user_id: int
    name: str
    user_url: str
    comments_in_period: int
    avg_sentiment: float
    districts: list[str]
    suspected_bot: bool


# ----------------------------------------------------------------------
# Утилиты
# ----------------------------------------------------------------------
def _period_filter(column, start_dt: datetime | None, end_dt: datetime | None):
    conds = []
    if start_dt is not None:
        conds.append(column >= start_dt)
    if end_dt is not None:
        conds.append(column < end_dt)
    return conds


def _vk_user_url(user_id: int | None) -> str | None:
    if not user_id or user_id <= 0:
        return None
    return f"https://vk.com/id{user_id}"


def _vk_post_url(group_vk_id: int | None, post_vk_id: int | None) -> str | None:
    if not group_vk_id or not post_vk_id:
        return None
    return f"https://vk.com/wall-{group_vk_id}_{post_vk_id}"


def _vk_comment_url(
    group_vk_id: int | None,
    post_vk_id: int | None,
    comment_vk_id: int | None,
) -> str | None:
    base = _vk_post_url(group_vk_id, post_vk_id)
    if not base or not comment_vk_id:
        return base
    return f"{base}?reply={comment_vk_id}"


def _vk_group_url(screen_name: str | None) -> str | None:
    if not screen_name:
        return None
    return f"https://vk.com/{screen_name}"


def _blocked_topic_ids(session) -> set[int]:
    """ID тем, ключевые слова которых матчатся с TOPIC_BLOCKLIST_KEYWORDS."""
    out: set[int] = set()
    for tid, kws in session.execute(select(Topic.id, Topic.keywords)).all():
        if not kws:
            continue
        # keywords хранятся как "слово1, слово2, слово3" — режем
        tokens = {t.strip().lower() for t in kws.split(",") if t.strip()}
        if tokens & TOPIC_BLOCKLIST_KEYWORDS:
            out.add(int(tid))
    return out


def get_data_period() -> tuple[datetime, datetime] | None:
    with get_session() as s:
        row = s.execute(select(
            func.min(Post.date), func.max(Post.date),
            func.min(Comment.date), func.max(Comment.date),
        )).one()
    candidates = [d for d in row if d is not None]
    if not candidates:
        return None
    return min(candidates), max(candidates)


def is_db_empty() -> bool:
    with get_session() as s:
        n = s.scalar(select(func.count()).select_from(Comment)) or 0
    return n == 0


# ----------------------------------------------------------------------
# Метрики по районам
# ----------------------------------------------------------------------
def _sentiment_aggs(sent_col):
    return [
        func.count().label("total"),
        func.sum(case((sent_col == "negative", 1), else_=0)).label("neg"),
        func.sum(case((sent_col == "neutral",  1), else_=0)).label("neu"),
        func.sum(case((sent_col == "positive", 1), else_=0)).label("pos"),
    ]


def get_district_metrics(
    start_dt: datetime | None = None,
    end_dt: datetime | None = None,
) -> list[DistrictMetrics]:
    """
    Сводка по каждому району с новой метрикой "отклонение от среднего":
      city_neg_share  = средняя доля негатива по городу за период
      sigma           = std долей негатива по 8 районам
      district_z      = (district_neg_share - city_neg_share) / sigma
      score           = sigmoid(district_z)  ∈ (0, 1)

    Так центр шкалы (0.5) — типичный для города уровень негатива;
    >0.5 — район хуже среднего, <0.5 — лучше.
    Маленькие районы с малым объёмом «сглаживаются» к 0.5 за счёт
    Лапласова сглаживания (см. _smoothed_neg_share).
    """
    with get_session() as s:
        p_conds = _period_filter(Post.date, start_dt, end_dt) + [
            Post.district_id.is_not(None)
        ]
        p_rows_raw = s.execute(
            select(Post.district_id, *_sentiment_aggs(Post.sentiment))
            .where(*p_conds).group_by(Post.district_id)
        ).all()
        p_rows = {r[0]: r[1:] for r in p_rows_raw}

        c_conds = _period_filter(Comment.date, start_dt, end_dt) + [
            Comment.district_id.is_not(None)
        ]
        c_rows_raw = s.execute(
            select(Comment.district_id, *_sentiment_aggs(Comment.sentiment))
            .where(*c_conds).group_by(Comment.district_id)
        ).all()
        c_rows = {r[0]: r[1:] for r in c_rows_raw}

    combined: dict[str, dict] = {}
    city_total = 0
    city_neg = 0
    for d in DISTRICTS:
        d_id = d["id"]
        p = p_rows.get(d_id, (0, 0, 0, 0))
        c = c_rows.get(d_id, (0, 0, 0, 0))
        total = (p[0] or 0) + (c[0] or 0)
        neg   = (p[1] or 0) + (c[1] or 0)
        neu   = (p[2] or 0) + (c[2] or 0)
        pos   = (p[3] or 0) + (c[3] or 0)
        combined[d_id] = {"total": total, "neg": neg, "neu": neu, "pos": pos}
        city_total += total
        city_neg += neg

    city_neg_share = city_neg / max(city_total, 1)

    # Лапласово сглаживание: добавляем по 5 виртуальных "средних" сообщений,
    # чтобы районы с 3 коммами не давали 100% негатива случайно.
    SMOOTH_N = 5

    def smoothed_share(neg: int, total: int) -> float:
        return (neg + SMOOTH_N * city_neg_share) / (total + SMOOTH_N)

    shares = {
        d_id: smoothed_share(m["neg"], m["total"])
        for d_id, m in combined.items()
    }

    # σ среди районов
    vals = list(shares.values())
    mean = sum(vals) / len(vals)
    variance = sum((v - mean) ** 2 for v in vals) / len(vals)
    sigma = math.sqrt(variance)
    if sigma < 0.005:
        # все районы примерно одинаковые → не растягиваем
        sigma = 0.005

    out: list[DistrictMetrics] = []
    for d in DISTRICTS:
        m = combined[d["id"]]
        s_share = shares[d["id"]]
        z = (s_share - mean) / sigma
        # сигмоида с нормировкой: z=0 → 0.5, z=±1.5 → ~0.18/0.82
        score = 1.0 / (1.0 + math.exp(-z))
        out.append(DistrictMetrics(
            district_id=d["id"],
            name_ru=d["name_ru"],
            total_posts=m["total"],
            negative=m["neg"], neutral=m["neu"], positive=m["pos"],
            activity=m["total"],
            negativity_score=round(score, 3),
            neg_share=round(s_share, 3),
            delta_vs_city=round(s_share - city_neg_share, 3),
        ))
    return out


# ----------------------------------------------------------------------
# Комментарии в районе — теперь с ссылками
# ----------------------------------------------------------------------
def get_recent_comments(
    district_id: str,
    start_dt: datetime | None = None,
    end_dt: datetime | None = None,
    limit: int = 50,
    sentiment: str | None = None,
    excluded_user_ids: set[int] | None = None,
) -> list[CommentRow]:
    excluded_user_ids = excluded_user_ids or set()
    conds = [Comment.district_id == district_id]
    conds += _period_filter(Comment.date, start_dt, end_dt)
    if sentiment:
        conds.append(Comment.sentiment == sentiment)

    with get_session() as s:
        rows = s.execute(
            select(
                Comment.author_vk_id,
                Comment.vk_id, Comment.text, Comment.sentiment,
                Comment.sentiment_score, Comment.date, Comment.district_id,
                User.first_name, User.last_name,
                Group.name, Group.screen_name, Group.vk_id.label("group_vk_id"),
                Post.vk_id.label("post_vk_id"),
            )
            .join(Post, Post.id == Comment.post_id)
            .join(Group, Group.id == Post.group_id)
            .join(User, User.vk_id == Comment.author_vk_id, isouter=True)
            .where(*conds)
            .order_by(Comment.date.desc())
            .limit(limit * 2)
        ).all()

    out: list[CommentRow] = []
    for r in rows:
        uid = r.author_vk_id
        if uid in excluded_user_ids:
            continue
        author = f"{r.first_name or ''} {r.last_name or ''}".strip()
        if not author:
            author = f"id{uid}" if uid else "—"
        group_name = r.name or r.screen_name or "—"
        out.append(CommentRow(
            author=author,
            user_id=int(uid or 0),
            user_url=_vk_user_url(uid),
            group=group_name,
            group_url=_vk_group_url(r.screen_name),
            text=r.text or "",
            sentiment=r.sentiment or "neutral",
            score=float(r.sentiment_score or 0),
            created_at=r.date,
            district_id=r.district_id,
            comment_url=_vk_comment_url(r.group_vk_id, r.post_vk_id, r.vk_id),
        ))
        if len(out) >= limit:
            break
    return out


# ----------------------------------------------------------------------
# Динамика по тонам
# ----------------------------------------------------------------------
def get_sentiment_timeseries(
    district_id: str,
    start_dt: datetime | None = None,
    end_dt: datetime | None = None,
    bucket: str = "day",  # "day" или "hour"
) -> list[dict]:
    """[{date, negative, neutral, positive}] по бакетам."""
    if bucket == "hour":
        # SQLite: группируем по час-уровню через strftime
        date_p = func.strftime("%Y-%m-%d %H:00", Post.date)
        date_c = func.strftime("%Y-%m-%d %H:00", Comment.date)
    else:
        date_p = func.date(Post.date)
        date_c = func.date(Comment.date)

    conds_p = [Post.district_id == district_id]
    conds_p += _period_filter(Post.date, start_dt, end_dt)
    conds_c = [Comment.district_id == district_id]
    conds_c += _period_filter(Comment.date, start_dt, end_dt)

    by_bucket: dict[str, dict[str, int]] = {}

    def upsert(key: str, sent: str, n: int):
        d = by_bucket.setdefault(key, {"negative": 0, "neutral": 0, "positive": 0})
        d[sent or "neutral"] = d.get(sent or "neutral", 0) + int(n or 0)

    with get_session() as s:
        p_rows = s.execute(
            select(date_p, Post.sentiment, func.count())
            .where(*conds_p).group_by(date_p, Post.sentiment)
        ).all()
        c_rows = s.execute(
            select(date_c, Comment.sentiment, func.count())
            .where(*conds_c).group_by(date_c, Comment.sentiment)
        ).all()

    for d, sent, n in list(p_rows) + list(c_rows):
        if d is None:
            continue
        upsert(str(d), sent, n)

    return [{"date": d, **counts} for d, counts in sorted(by_bucket.items())]


# ----------------------------------------------------------------------
# Топ тем — с фильтром блок-листа
# ----------------------------------------------------------------------
def get_top_topics(
    district_id: str | None,
    start_dt: datetime | None = None,
    end_dt: datetime | None = None,
    limit: int = 5,
) -> list[TopicRow]:
    neg_case = case((Comment.sentiment == "negative", 1), else_=0)

    with get_session() as s:
        blocked = _blocked_topic_ids(s)

        conds = [Comment.topic_id.is_not(None)]
        if blocked:
            conds.append(not_(Comment.topic_id.in_(blocked)))
        if district_id:
            conds.append(Comment.district_id == district_id)
        conds += _period_filter(Comment.date, start_dt, end_dt)

        rows = s.execute(
            select(
                Comment.topic_id,
                func.count().label("n"),
                func.sum(neg_case).label("neg"),
                Topic.label, Topic.keywords,
            )
            .join(Topic, Topic.id == Comment.topic_id)
            .where(*conds)
            .group_by(Comment.topic_id)
            .order_by(func.count().desc())
            .limit(limit)
        ).all()

    return [
        TopicRow(
            topic_id=int(tid), label=label or "", keywords=keywords or "",
            count=int(n),
            neg_share=round(float(neg or 0) / max(int(n), 1), 3),
        )
        for tid, n, neg, label, keywords in rows
    ]


# ----------------------------------------------------------------------
# Всплески — с фильтром блок-листа
# ----------------------------------------------------------------------
def get_bursts(
    district_id: str | None,
    start_dt: datetime | None = None,
    end_dt: datetime | None = None,
    limit: int = 10,
    citywide_if_none: bool = True,
) -> list[BurstRow]:
    if district_id is None and not citywide_if_none:
        return []

    with get_session() as s:
        blocked = _blocked_topic_ids(s)

        conds = []
        if district_id is None:
            conds.append(Burst.district_id.is_(None))
        else:
            conds.append(Burst.district_id == district_id)
        if blocked:
            conds.append(not_(Burst.topic_id.in_(blocked)))
        conds += _period_filter(Burst.date, start_dt, end_dt)

        rows = s.execute(
            select(
                Burst.date, Topic.label,
                Burst.volume, Burst.z_score, Burst.intensity, Burst.neg_share,
            )
            .join(Topic, Topic.id == Burst.topic_id)
            .where(*conds)
            .order_by(Burst.z_score.desc())
            .limit(limit)
        ).all()

    return [
        BurstRow(
            date=d, topic_label=label or "—",
            volume=int(vol), z_score=float(z),
            intensity=intensity or "low",
            neg_share=float(neg) if neg is not None else None,
        )
        for d, label, vol, z, intensity, neg in rows
    ]


# ----------------------------------------------------------------------
# Топ авторов — с user_url
# ----------------------------------------------------------------------
def get_top_users(
    start_dt: datetime | None = None,
    end_dt: datetime | None = None,
    limit: int = 30,
) -> list[TopUserRow]:
    pos_case = case((Comment.sentiment == "positive", 1), else_=0)
    neg_case = case((Comment.sentiment == "negative", 1), else_=0)

    conds = [Comment.author_vk_id.is_not(None), Comment.author_vk_id > 0]
    conds += _period_filter(Comment.date, start_dt, end_dt)

    with get_session() as s:
        rows = s.execute(
            select(
                Comment.author_vk_id,
                func.count().label("n"),
                func.sum(pos_case).label("pos"),
                func.sum(neg_case).label("neg"),
                User.first_name, User.last_name, User.screen_name,
            )
            .join(User, User.vk_id == Comment.author_vk_id, isouter=True)
            .where(*conds)
            .group_by(Comment.author_vk_id)
            .order_by(func.count().desc())
            .limit(limit)
        ).all()

        user_districts: dict[int, set[str]] = {}
        if rows:
            user_ids = [r[0] for r in rows]
            d_rows = s.execute(
                select(Comment.author_vk_id, Comment.district_id)
                .where(
                    Comment.author_vk_id.in_(user_ids),
                    Comment.district_id.is_not(None),
                    *_period_filter(Comment.date, start_dt, end_dt),
                )
                .distinct()
            ).all()
            for uid, did in d_rows:
                user_districts.setdefault(int(uid), set()).add(did)

    out: list[TopUserRow] = []
    for uid, n, pos, neg, fn, ln, sn in rows:
        n = int(n)
        avg = (int(pos or 0) - int(neg or 0)) / max(n, 1)
        suspected = (n >= 30 and abs(avg) >= 0.7)
        # имя: либо first+last, либо screen_name, либо id
        name = f"{fn or ''} {ln or ''}".strip()
        if not name:
            name = sn or f"id{uid}"
        # url: всегда через id, это надёжнее чем screen_name
        url = _vk_user_url(uid) or f"https://vk.com/id{uid}"
        out.append(TopUserRow(
            user_id=int(uid),
            name=name,
            user_url=url,
            comments_in_period=n,
            avg_sentiment=round(avg, 2),
            districts=sorted(user_districts.get(int(uid), set())),
            suspected_bot=suspected,
        ))
    return out


# ----------------------------------------------------------------------
# Heatmap "темы x время"
# ----------------------------------------------------------------------
def get_topic_day_heatmap(
    district_id: str | None,
    start_dt: datetime | None = None,
    end_dt: datetime | None = None,
    top_n_topics: int = 8,
) -> tuple[list[str], list[str], list[list[int]]]:
    top = get_top_topics(district_id, start_dt, end_dt, limit=top_n_topics)
    if not top:
        return [], [], []
    topic_ids = [t.topic_id for t in top]
    topic_labels = [t.label for t in top]

    conds = [Comment.topic_id.in_(topic_ids)]
    if district_id:
        conds.append(Comment.district_id == district_id)
    conds += _period_filter(Comment.date, start_dt, end_dt)

    with get_session() as s:
        rows = s.execute(
            select(func.date(Comment.date), Comment.topic_id, func.count())
            .where(*conds).group_by(func.date(Comment.date), Comment.topic_id)
        ).all()

    all_days = sorted({str(r[0]) for r in rows})
    day_idx = {d: i for i, d in enumerate(all_days)}
    topic_idx = {t: i for i, t in enumerate(topic_ids)}

    matrix = [[0] * len(all_days) for _ in topic_ids]
    for d, tid, n in rows:
        matrix[topic_idx[int(tid)]][day_idx[str(d)]] = int(n)
    return all_days, topic_labels, matrix
