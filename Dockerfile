FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8787

COPY pyproject.toml ./
COPY orchestra ./orchestra
RUN pip install --no-cache-dir .
COPY . .

EXPOSE 8787
CMD ["sh", "-c", "uvicorn orchestra.main:app --host 0.0.0.0 --port ${PORT:-8787}"]
