# CartPilot agent API - works on Hugging Face Spaces (Docker) and Render.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=7860

# Hugging Face Spaces runs containers as uid 1000.
RUN useradd -m -u 1000 app
WORKDIR /home/app/backend

COPY backend/requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY --chown=app:app backend/app ./app
USER app

EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"7860\")}/health', timeout=4)" || exit 1

# One worker keeps the in-process per-thread locks consistent; FastAPI runs sync
# endpoints in a thread pool, so requests are still served concurrently.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
