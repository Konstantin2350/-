FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8787

COPY pyproject.toml ./
COPY orchestra ./orchestra
RUN pip install --no-cache-dir .
COPY . .

RUN useradd --create-home --uid 10001 orchestra \
    && chown -R orchestra:orchestra /app
USER orchestra

EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/ready', timeout=3)"
CMD ["sh", "-c", "alembic upgrade head && uvicorn orchestra.main:app --host 0.0.0.0 --port ${PORT:-8787}"]
