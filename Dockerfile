FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x docker-entrypoint.sh

ENV HUB_DB=/app/data/hub.db \
    PYTHONUNBUFFERED=1

EXPOSE 8900

ENTRYPOINT ["./docker-entrypoint.sh"]
