# ============================================================
# Civic Monitor НН — Dockerfile
# Python 3.13-slim + все зависимости проекта
# ============================================================

FROM python:3.13-slim

# --- Системные зависимости ---
# libpq-dev + gcc нужны для psycopg2
# git нужен некоторым pip-пакетам при сборке
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        git \
        curl \
    && rm -rf /var/lib/apt/lists/*

# --- Рабочая директория ---
WORKDIR /app

# --- Зависимости Python (кэшируются отдельным слоем) ---
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install \
        --no-cache-dir \
        --timeout=300 \
        --retries=10 \
        -r requirements.txt

# --- Код приложения ---
COPY . .

# --- Директории для данных ---
RUN mkdir -p /app/data

# --- Переменные окружения ---
# HF_HOME — куда sentence-transformers и transformers кэшируют модели.
# Монтируем как volume в docker-compose, чтобы модели не качались каждый раз.
ENV HF_HOME=/app/.cache/huggingface
ENV TRANSFORMERS_CACHE=/app/.cache/huggingface
ENV SENTENCE_TRANSFORMERS_HOME=/app/.cache/huggingface/sentence_transformers

# Streamlit не нужен браузер в контейнере
ENV STREAMLIT_SERVER_HEADLESS=true
ENV STREAMLIT_SERVER_PORT=8501
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# --- Порт ---
EXPOSE 8501

# --- Healthcheck ---
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

# --- Точка входа ---
CMD ["streamlit", "run", "app.py", \
     "--server.address=0.0.0.0", \
     "--server.port=8501"]
