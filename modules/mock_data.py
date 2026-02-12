"""
Моковые данные для разработки UI.

Когда подключим парсер VK + RuBERT, этот модуль заменим на реальные
выгрузки из БД. Структура возвращаемых данных останется той же —
функции в visualization.py и app.py к ней привязаны.

Все цифры здесь — детерминированные (random.seed), чтобы при перезапуске
карта выглядела одинаково и можно было воспроизводить баги.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Literal

from modules.districts import DISTRICTS, DISTRICT_BY_ID

Sentiment = Literal["negative", "neutral", "positive"]

random.seed(42)


@dataclass
class DistrictMetrics:
    """Сводка по району за выбранный период."""
    district_id: str
    name_ru: str
    total_posts: int
    negative: int
    neutral: int
    positive: int
    activity: int          # суммарный объём (для нормировки)
    negativity_score: float  # 0..1 — итоговый "градус красноты" района

    @property
    def neg_share(self) -> float:
        return self.negative / max(self.total_posts, 1)


@dataclass
class Comment:
    author: str
    user_id: int
    group: str
    text: str
    sentiment: Sentiment
    score: float           # уверенность модели
    created_at: datetime
    district_id: str


@dataclass
class TopUser:
    user_id: int
    name: str
    comments_30d: int
    avg_sentiment: float   # -1..+1 (отрицательный = пишет много негатива)
    districts: list[str]   # в каких районах активен
    suspected_bot: bool


# ----------------------------------------------------------------------
# Генерация
# ----------------------------------------------------------------------

_NEG_SAMPLES = [
    "Опять перекопали двор, ходить негде. Сколько можно?",
    "Маршрутки не ходят с утра, на работу не доехать.",
    "Управляющая компания не реагирует уже месяц на жалобы.",
    "Снег не убирают, тротуары — каток. Где администрация?",
    "Вонь со свалки на весь район. Дышать нечем.",
    "Школу обещали два года назад, до сих пор стройка стоит.",
    "Мусор не вывозят, контейнеры переполнены.",
    "Фонари не горят, вечером страшно идти.",
]
_NEU_SAMPLES = [
    "Когда планируется ремонт дороги на нашей улице?",
    "Подскажите расписание автобуса №40.",
    "Где можно посмотреть план благоустройства?",
    "Информация о приёме главы района — кто-то был?",
    "Завтра отключение горячей воды по графику.",
]
_POS_SAMPLES = [
    "Спасибо коммунальщикам, двор отлично почистили!",
    "Новая площадка во дворе — детям радость, давно пора было.",
    "Дорогу наконец сделали, ехать одно удовольствие.",
    "Парк обновили, гулять приятно стало.",
    "Хорошо, что освещение починили на остановке.",
]
_FIRST_NAMES = ["Алексей", "Мария", "Иван", "Ольга", "Дмитрий", "Анна", "Сергей",
                "Екатерина", "Андрей", "Татьяна", "Павел", "Наталья", "Михаил"]
_LAST_NAMES = ["Иванов", "Смирнов", "Кузнецов", "Попов", "Соколов", "Лебедев",
               "Козлов", "Новиков", "Морозов", "Петров", "Волков", "Соловьёв"]


def _district_profile(d_id: str) -> tuple[float, int]:
    """
    Базовый "характер" района: (доля негатива, объём активности).
    Подобрано так, чтобы карта выглядела разнообразно.
    """
    profiles = {
        "avtozavodsky":  (0.62, 1850),  # большой район, много жалоб
        "kanavinsky":    (0.55, 1200),
        "leninsky":      (0.41, 980),
        "moskovsky":     (0.38, 740),
        "nizhegorodsky": (0.34, 1620),  # центр, активный, но не очень негативный
        "priokskiy":     (0.22, 520),
        "sovetsky":      (0.28, 690),
        "sormovsky":     (0.71, 1410),  # горячая точка
    }
    return profiles.get(d_id, (0.4, 800))


def get_district_metrics() -> list[DistrictMetrics]:
    """Сводки по всем районам — для раскраски карты."""
    out: list[DistrictMetrics] = []
    for d in DISTRICTS:
        neg_share, total = _district_profile(d["id"])
        # доли с шумом
        neg = int(total * (neg_share + random.uniform(-0.04, 0.04)))
        pos = int(total * random.uniform(0.10, 0.25))
        neu = total - neg - pos

        # Итоговый "градус". Учитывает И долю негатива, И абсолютный объём:
        # маленький район с 10 негативными постами не должен светиться красным.
        max_total = 2000
        volume_w = min(total / max_total, 1.0)
        score = neg_share * (0.6 + 0.4 * volume_w)

        out.append(DistrictMetrics(
            district_id=d["id"],
            name_ru=d["name_ru"],
            total_posts=total,
            negative=neg, neutral=neu, positive=pos,
            activity=total,
            negativity_score=round(score, 3),
        ))
    return out


def get_recent_comments(district_id: str, limit: int = 30) -> list[Comment]:
    """Последние комментарии в районе. В реальной версии — выборка из БД."""
    d = DISTRICT_BY_ID[district_id]
    now = datetime.now()
    out: list[Comment] = []
    for i in range(limit):
        sentiment = random.choices(
            ["negative", "neutral", "positive"],
            weights=[_district_profile(district_id)[0] * 100, 30, 20],
            k=1,
        )[0]
        text_pool = {
            "negative": _NEG_SAMPLES,
            "neutral":  _NEU_SAMPLES,
            "positive": _POS_SAMPLES,
        }[sentiment]
        out.append(Comment(
            author=f"{random.choice(_FIRST_NAMES)} {random.choice(_LAST_NAMES)}",
            user_id=random.randint(10_000_000, 99_999_999),
            group=f"Подслушано {d['name_ru']}",
            text=random.choice(text_pool),
            sentiment=sentiment,
            score=round(random.uniform(0.72, 0.98), 2),
            created_at=now - timedelta(hours=i * 2 + random.randint(0, 5)),
            district_id=district_id,
        ))
    return out


def get_sentiment_timeseries(district_id: str, days: int = 30):
    """
    Временной ряд активности по тональности — для графика
    в боковой панели района.
    Возвращает: list[dict] с полями date, negative, neutral, positive.
    """
    base_neg, base_total = _district_profile(district_id)
    today = datetime.now().date()
    rows = []
    for i in range(days, 0, -1):
        day = today - timedelta(days=i)
        total = max(int(base_total / days * random.uniform(0.5, 1.7)), 1)
        neg = int(total * (base_neg + random.uniform(-0.1, 0.1)))
        pos = int(total * random.uniform(0.1, 0.25))
        neu = max(total - neg - pos, 0)
        rows.append({
            "date": day.isoformat(),
            "negative": neg, "neutral": neu, "positive": pos,
        })
    return rows


def get_top_users(limit: int = 25) -> list[TopUser]:
    """
    Самые активные за 30 дней. Используется для отдельной вкладки
    'Топ авторов / детектор ботов'.

    Половина — с устойчиво отрицательным окрасом, половина — с
    устойчиво положительным: оба полюса подозрительны на бот-сети.
    """
    out: list[TopUser] = []
    for i in range(limit):
        # делаем профили перекошенными: либо заметно негативный, либо позитивный
        polarity = random.choice([-1, -1, -1, 1, 1])  # негативных чуть больше
        avg = polarity * random.uniform(0.55, 0.95)
        comments = random.randint(80, 480)
        d_count = random.choices([1, 2, 3], weights=[5, 3, 2])[0]
        out.append(TopUser(
            user_id=random.randint(10_000_000, 99_999_999),
            name=f"{random.choice(_FIRST_NAMES)} {random.choice(_LAST_NAMES)}",
            comments_30d=comments,
            avg_sentiment=round(avg, 2),
            districts=random.sample([d["id"] for d in DISTRICTS], k=d_count),
            # Эвристика подозрения на бота: очень высокая активность
            # И сильный перекос окраса (≥ 0.8 по модулю).
            suspected_bot=(comments > 250 and abs(avg) >= 0.8),
        ))
    out.sort(key=lambda u: u.comments_30d, reverse=True)
    return out
