"""
Sentiment-анализ русскоязычных комментариев на базе RuBERT.

Использование:
    from modules.sentiment import SentimentAnalyzer

    sa = SentimentAnalyzer()
    results = sa.predict_batch(["Опять снег не убрали", "Спасибо коммунальщикам"])
    # [("negative", 0.91), ("positive", 0.87)]

Архитектура:
  • Модель грузится лениво — первый predict_batch() инициализирует.
  • Веса кэшируются в ~/.cache/huggingface (стандартный путь HF).
  • Используется CPU по умолчанию; если найдётся MPS (Apple Silicon)
    или CUDA — поднимется на нём автоматически.
  • Батч 32 по умолчанию: компромисс между памятью и скоростью на CPU.
  • Длина токенов ограничена 256: VK-комменты редко длиннее, на всё что
    длиннее — обрезается без потери качества для оценки тональности.

Модели:
  • DEFAULT_MODEL — лёгкий tiny (~30 MB, ~50 комм/сек на CPU мака).
  • HEAVY_MODEL   — base (~700 MB, ~5 комм/сек). Точнее, но для 14k
    комментариев разница 5 минут vs час. Для диплома tiny хватает.
"""
from __future__ import annotations

import logging
from typing import Literal

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

log = logging.getLogger(__name__)

DEFAULT_MODEL = "seara/rubert-tiny2-russian-sentiment"
HEAVY_MODEL = "blanchefort/rubert-base-cased-sentiment"

Sentiment = Literal["negative", "neutral", "positive"]


def _pick_device() -> str:
    """Лучшее доступное устройство: CUDA > MPS (Apple) > CPU."""
    if torch.cuda.is_available():
        return "cuda"
    # На M1/M2/M3 MPS даёт ускорение, но иногда конфликтует с моделями
    # — оставляем как опцию, активируется через переменную окружения,
    # чтобы не ловить странные глюки на свежей версии PyTorch.
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class SentimentAnalyzer:
    """
    Обёртка с ленивой загрузкой и батч-инференсом.
    Безопасна к повторному использованию: модель грузится один раз.
    """

    LABEL_MAP_3CLASS = {
        # Возможные раскладки label2id у разных моделей.
        # Приведены lower-case для устойчивости.
        "negative": "negative", "neg": "negative", "label_0": "negative",
        "neutral":  "neutral",  "neu": "neutral",  "label_1": "neutral",
        "positive": "positive", "pos": "positive", "label_2": "positive",
    }

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        device: str | None = None,
        max_length: int = 256,
    ):
        self.model_name = model_name
        self.device = device or _pick_device()
        self.max_length = max_length
        self._tokenizer = None
        self._model = None
        self._id2label: dict[int, Sentiment] = {}

    # ------------------------------------------------------------------
    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        log.info("Загружаю модель '%s' на устройство %s", self.model_name, self.device)
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        self._model = AutoModelForSequenceClassification.from_pretrained(self.model_name)
        self._model.eval()
        self._model.to(self.device)

        # Каждая модель называет классы по-своему — нормализуем.
        raw_id2label = self._model.config.id2label
        normalized: dict[int, Sentiment] = {}
        for idx, raw in raw_id2label.items():
            key = str(raw).lower()
            mapped = self.LABEL_MAP_3CLASS.get(key)
            if mapped is None:
                # Попытка номер 2: имя класса похоже, но регистр другой.
                for k, v in self.LABEL_MAP_3CLASS.items():
                    if k in key:
                        mapped = v
                        break
            if mapped is None:
                raise RuntimeError(
                    f"Неизвестная метка модели: {raw}. "
                    f"Добавьте в LABEL_MAP_3CLASS."
                )
            normalized[int(idx)] = mapped  # type: ignore[assignment]
        self._id2label = normalized
        log.info("Маппинг классов: %s", self._id2label)

    # ------------------------------------------------------------------
    @torch.inference_mode()
    def predict_batch(
        self,
        texts: list[str],
        batch_size: int = 32,
    ) -> list[tuple[Sentiment, float]]:
        """
        Прогнать батч текстов через модель.
        Возвращает список (метка, уверенность) той же длины и порядка.
        """
        self._ensure_loaded()
        if not texts:
            return []

        out: list[tuple[Sentiment, float]] = []
        for i in range(0, len(texts), batch_size):
            chunk = texts[i:i + batch_size]
            enc = self._tokenizer(
                chunk,
                padding=True, truncation=True,
                max_length=self.max_length,
                return_tensors="pt",
            ).to(self.device)
            logits = self._model(**enc).logits
            probs = torch.softmax(logits, dim=-1)
            confs, preds = probs.max(dim=-1)
            for pred_idx, conf in zip(preds.tolist(), confs.tolist()):
                out.append((self._id2label[pred_idx], float(conf)))
        return out
