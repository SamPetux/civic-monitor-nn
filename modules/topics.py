"""
Тематическое моделирование (BERTopic).

Архитектура:
    TopicModeler(...)              — фабрика модели с настроенными параметрами
    .fit_transform(texts, ...)     — обучение + назначение тем
    .get_topic_info()              — DataFrame с темами, ключевыми словами, размерами
    .build_label(topic_id)         — человекочитаемое имя темы (топ-3 слова)

Используем:
  • SBERT-эмбеддинги (paraphrase-multilingual-MiniLM-L12-v2 по умолчанию)
  • UMAP для понижения размерности
  • HDBSCAN для кластеризации
  • c-TF-IDF + русские стоп-слова для извлечения ключевых слов

Параметры подобраны под объёмы 5-20k коротких комментариев.
"""
from __future__ import annotations

import logging
import re
from typing import Iterable

from bertopic import BERTopic
from bertopic.vectorizers import ClassTfidfTransformer
from hdbscan import HDBSCAN
from sentence_transformers import SentenceTransformer
from sklearn.feature_extraction.text import CountVectorizer
from umap import UMAP

log = logging.getLogger(__name__)

def _resolve_model_path(model_name: str) -> str:
    """
    Если модель лежит в HuggingFace hub-кэше (Docker/офлайн) —
    возвращаем полный путь к snapshot. Иначе возвращаем имя модели
    как есть (обычный локальный запуск с доступом в интернет).
    """
    import os
    hf_home = os.environ.get("HF_HOME", os.path.expanduser("~/.cache/huggingface"))
    hub_dir = os.path.join(hf_home, "hub")
    folder_name = "models--" + model_name.replace("/", "--")
    snapshots_dir = os.path.join(hub_dir, folder_name, "snapshots")
    if os.path.isdir(snapshots_dir):
        snapshots = sorted(os.listdir(snapshots_dir))
        if snapshots:
            full_path = os.path.join(snapshots_dir, snapshots[-1])
            log.info("Модель найдена в кэше: %s", full_path)
            return full_path
    return model_name

LIGHT_EMB_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
HEAVY_EMB_MODEL = "ai-forever/sbert_large_nlu_ru"

# Русские стоп-слова. Не тащим зависимость от nltk ради одного списка —
# берём базовый собственный набор + типичный VK-мусор. По опыту, после
# препроцессинга в clean_for_sentiment() этого достаточно.
RU_STOPWORDS = {
    # короткие частотные слова
    "и", "в", "не", "на", "что", "я", "с", "а", "по", "то", "он", "она",
    "это", "так", "но", "как", "из", "у", "к", "за", "для", "же", "ну",
    "уж", "ли", "бы", "был", "была", "было", "были", "есть", "быть",
    "от", "до", "о", "об", "при", "над", "под", "без", "через",
    "вот", "там", "тут", "уже", "ещё", "еще", "тоже", "только",
    "если", "или", "когда", "потому", "поэтому", "чтобы", "хотя",
    "мы", "вы", "они", "его", "её", "ее", "их", "им", "ему", "ей",
    "себя", "свой", "свою", "своё", "свои", "сам", "сама", "сами",
    "мой", "моя", "моё", "наш", "ваш", "тот", "та", "те", "этот", "эта",
    "очень", "просто", "может", "можно", "нужно", "надо", "буду", "будет",
    "сейчас", "вчера", "сегодня", "завтра", "всегда", "никогда",
    "всё", "все", "вся", "весь", "ничего", "никто", "ничто", "что-то",
    "кто", "кто-то", "какой", "какая", "какое", "какие", "который", "которая", "которые",
    # типичный мусор VK
    "ответить", "ответ", "спасибо", "пожалуйста", "здравствуйте",
    "доброе", "утро", "день", "вечер", "привет", "пока",
    "согласен", "согласна", "согласны",
    "люди", "человек", "товарищ",
    "просьба", "коллеги",
    # местоимения с предлогами и т.п.
    "меня", "тебя", "нас", "вас", "них",
    # Общие вопросительные и разговорные слова — тянут мусорную мега-тему
    "где", "когда", "почему", "зачем", "как", "что", "кто",
    "нет", "да", "ну", "вот", "уже", "всё", "ещё", "там",
    "так", "лет", "год", "раз", "просто", "очень",
    # Общие бытовые слова без топической нагрузки
    "добрый", "больше", "дома", "вопрос", "хорошо",
    "вообще", "даже", "чем", "вам", "мне", "тебе", "про",
    "будут", "было", "стало", "потом", "после", "если",
    "этот", "эта", "это", "эти", "такой", "такая", "этим", "этом",
    "снег", "зима", "снега"
    # общегородские события
    "нижнего новгорода", "новгорода", "новгород", "нижнего", "нижний", "новгороде", "нижнем"
    "россии", "россия", "рф",
    # Реклама
    "erid", "инн", "com", "www", "http", "https",
}

# Имена — частая ловушка: тема "александр, дмитрий, канале" получается
# не потому, что обсуждают людей, а потому что это типичные имена авторов
# подписей под видео / постами. Имена не несут географической или
# содержательной нагрузки для нашей задачи.
RU_FIRST_NAMES = {
    # мужские
    "александр", "алексей", "анатолий", "андрей", "антон", "аркадий",
    "артём", "артем", "борис", "вадим", "валентин", "валерий", "василий",
    "виктор", "виталий", "владимир", "владислав", "вячеслав", "геннадий",
    "георгий", "глеб", "григорий", "даниил", "данил", "данила", "денис",
    "дмитрий", "евгений", "егор", "иван", "игорь", "илья", "кирилл",
    "константин", "леонид", "максим", "марк", "матвей", "михаил",
    "никита", "николай", "олег", "павел", "пётр", "петр", "роман",
    "руслан", "сергей", "станислав", "степан", "тимофей", "тимур",
    "фёдор", "федор", "филипп", "эдуард", "юрий", "ярослав",
    # уменьшительные мужские
    "саша", "сашка", "лёша", "леша", "андрюха", "ваня", "ванька",
    "дима", "димон", "женя", "коля", "костя", "лёня", "леня",
    "максик", "мишка", "миша", "никитка", "паша", "петя",
    "серёга", "серега", "стас", "толя", "юра",
    # женские
    "александра", "алина", "алла", "анастасия", "ангелина", "анжела",
    "анна", "валентина", "валерия", "варвара", "вера", "вероника",
    "виктория", "галина", "дарья", "диана", "екатерина", "елена",
    "елизавета", "жанна", "зинаида", "зоя", "инна", "ирина", "карина",
    "кира", "кристина", "ксения", "лариса", "лидия", "любовь", "людмила",
    "маргарита", "марина", "мария", "надежда", "наталия", "наталья",
    "нина", "оксана", "ольга", "полина", "раиса", "светлана", "софия",
    "софья", "тамара", "татьяна", "ульяна", "юлия", "яна",
    # уменьшительные женские
    "настя", "катя", "лена", "лиза", "маша", "наташа", "оля", "света",
    "таня", "юля",
}

# Всё вместе — то, что отдадим в CountVectorizer
ALL_STOPWORDS = RU_STOPWORDS | RU_FIRST_NAMES

# Регулярка для токенизации: только буквы (русские/латиница), длиной от 3.
# Цифры и пунктуация выкидываем — они в темах создают шум вроде "2024".
_TOKEN_RE = re.compile(r"\b[а-яёa-z]{3,}\b")


def _tokenizer(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


class TopicModeler:
    """Обёртка над BERTopic с настройками под русские VK-комментарии."""

    def __init__(
        self,
        embedding_model_name: str = LIGHT_EMB_MODEL,
        min_topic_size: int = 15,
        nr_topics: int | str | None = "auto",
        random_state: int = 42,
    ):
        self.embedding_model_name = embedding_model_name
        self.min_topic_size = min_topic_size
        self.nr_topics = nr_topics
        self.random_state = random_state
        self._model: BERTopic | None = None

    # ------------------------------------------------------------------
    def _build(self) -> BERTopic:
        """Собрать настроенный экземпляр BERTopic."""
        log.info("Загружаю эмбеддинг-модель '%s'", self.embedding_model_name)
        embedder = SentenceTransformer(_resolve_model_path(self.embedding_model_name))

        # UMAP — снижение размерности перед кластеризацией.
        # n_neighbors=15, n_components=5 — стандарт для коротких текстов.
        umap = UMAP(
            n_neighbors=15, n_components=5, min_dist=0.0,
            metric="cosine", random_state=self.random_state,
        )

        # HDBSCAN — кластеризация. min_cluster_size = min_topic_size.
        hdbscan = HDBSCAN(
            min_cluster_size=self.min_topic_size,
            metric="euclidean",
            cluster_selection_method="eom",
            prediction_data=True,
        )

        # Векторизатор для извлечения ключевых слов из кластеров.
        # min_df=2 — слово должно встретиться хотя бы дважды в кластере.
        vectorizer = CountVectorizer(
            tokenizer=_tokenizer,
            stop_words=list(ALL_STOPWORDS),
            min_df=2,
            ngram_range=(1, 2),  # униграммы + биграммы
            token_pattern=None,  # т.к. передаём свой tokenizer
        )

        ctfidf = ClassTfidfTransformer(reduce_frequent_words=True)

        return BERTopic(
            embedding_model=embedder,
            umap_model=umap,
            hdbscan_model=hdbscan,
            vectorizer_model=vectorizer,
            ctfidf_model=ctfidf,
            nr_topics=self.nr_topics,
            calculate_probabilities=False,  # ускоряет инференс
            verbose=False,
            language="multilingual",
        )

    # ------------------------------------------------------------------
    def fit_transform(self, texts: list[str]) -> list[int]:
        """
        Обучить модель и вернуть номер темы для каждого текста.
        Шум помечается -1.
        """
        if len(texts) < self.min_topic_size * 2:
            raise ValueError(
                f"Слишком мало текстов ({len(texts)}) для min_topic_size="
                f"{self.min_topic_size}. Уменьшите --min-topic-size или "
                f"расширьте выборку (--limit)."
            )
        self._model = self._build()
        log.info("Обучаю BERTopic на %d текстах...", len(texts))
        topics, _ = self._model.fit_transform(texts)
        return list(topics)

    # ------------------------------------------------------------------
    def get_topic_info(self):
        """DataFrame с темами: id, count, name, представители."""
        assert self._model is not None, "Сначала вызовите fit_transform()"
        return self._model.get_topic_info()

    def get_topic_words(self, topic_id: int, top_n: int = 10) -> list[str]:
        """Топ-N ключевых слов темы (без c-TF-IDF весов)."""
        assert self._model is not None
        words = self._model.get_topic(topic_id) or []
        return [w for w, _score in words[:top_n]]

    def build_label(self, topic_id: int, n_words: int = 3) -> str:
        """Короткое имя темы из её ключевых слов."""
        words = self.get_topic_words(topic_id, top_n=n_words)
        return ", ".join(words) if words else f"topic_{topic_id}"
