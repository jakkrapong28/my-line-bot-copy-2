FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps for PDF / scientific wheels
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY app/ ./app/
COPY main.py ./

# Run the public-facing API without root privileges.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD python -c "import httpx,sys; sys.exit(0 if httpx.get('http://localhost:8000/health').status_code==200 else 1)"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
