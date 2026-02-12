"""
Препроцессинг текстов комментариев перед подачей в RuBERT.

В БД сохраняется оригинал — функция clean_for_sentiment() готовит
ОТДЕЛЬНУЮ строку для модели, не меняя текст в `comments.text`.

Что чистится:
  • URL (https://, vk.com/..., t.me/..., и т.п.)
  • VK-упоминания вида [id12345|Имя] или [club12345|Группа]
  • Хэштеги и упоминания через @
  • Подписи "Подписаться", "Источник:" и пр. (короткий стоп-словарь)
  • Множественные пробелы и переводы строк сводятся к одному пробелу

Что определяется как "спам/нерелевантное" (is_spam):
  • После очистки осталось < 3 символов
  • После очистки осталось >= 80% эмодзи (одни смайлики)
  • Есть характерные рекламные паттерны (t.me/, "подписывайтесь", промокоды)

Спам помечаем как neutral / score=0 без вызова модели — экономим время
и не зашумляем агрегаты.
"""
from __future__ import annotations

import re
import unicodedata

# --- регексы (компилируем один раз) ---
_URL_RE        = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_VK_LINK_RE    = re.compile(r"\[(id|club|public)\d+\|([^\]]+)\]")
_TG_LINK_RE    = re.compile(r"t\.me/\S+", re.IGNORECASE)
_MENTION_RE    = re.compile(r"@\w+")
_HASHTAG_RE    = re.compile(r"#\w+")
_MULTISPACE_RE = re.compile(r"\s+")

# Паттерны рекламы — если хоть один матчится, считаем комментарий спамом.
# Регистр игнорируем.
_SPAM_PATTERNS = [
    re.compile(r"\bt\.me/", re.IGNORECASE),
    re.compile(r"подпис(ыв|ат|ка)", re.IGNORECASE),
    re.compile(r"промокод", re.IGNORECASE),
    re.compile(r"наш канал", re.IGNORECASE),
    re.compile(r"перейти по ссылк", re.IGNORECASE),
    re.compile(r"(скидк|акци)\w* до \d+", re.IGNORECASE),
    re.compile(r"работа на дому.+\d{4,}", re.IGNORECASE),
    re.compile(r'\berid\b', re.IGNORECASE),
    re.compile(r'\bинн\s*\d{10,12}\b', re.IGNORECASE),
    re.compile(r'erid\s*[:\s]\s*[A-Za-z0-9]+', re.IGNORECASE),
]


def _emoji_share(text: str) -> float:
    """Доля эмодзи и спецсимволов от общей длины. 0..1."""
    if not text:
        return 0.0
    emoji_chars = sum(
        1 for ch in text
        if unicodedata.category(ch).startswith("S")  # символы (включая эмодзи)
        or ord(ch) > 0x2600                           # дополнительные символьные блоки
    )
    return emoji_chars / len(text)


def clean_for_sentiment(text: str) -> str:
    """
    Очистить текст для подачи в модель. Возвращает строку без URL,
    без VK-разметки, со схлопнутыми пробелами.
    """
    if not text:
        return ""
    t = text
    # [id123|Имя] -> Имя (сохраняем человекочитаемое)
    t = _VK_LINK_RE.sub(r"\2", t)
    t = _URL_RE.sub(" ", t)
    t = _TG_LINK_RE.sub(" ", t)
    t = _MENTION_RE.sub(" ", t)
    t = _HASHTAG_RE.sub(" ", t)
    t = _MULTISPACE_RE.sub(" ", t).strip()
    return t


def is_spam(original_text: str, cleaned_text: str) -> bool:
    """Эвристика: считается ли комментарий рекламой/мусором."""
    if len(cleaned_text) < 3:
        return True
    if _emoji_share(cleaned_text) >= 0.8:
        return True
    for pat in _SPAM_PATTERNS:
        if pat.search(original_text):
            return True
    return False
