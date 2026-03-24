FROM python:3.12-slim

WORKDIR /app

# Install system dependencies (lxml + cron)
RUN apt-get update && \
    apt-get install -y --no-install-recommends libxml2-dev libxslt1-dev cron && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY paleonews/ paleonews/
COPY sources.txt config.yaml ./
COPY deploy/entrypoint.sh /app/entrypoint.sh

RUN pip install --no-cache-dir .

# Use /app/data for DB, /app/logs for logs
RUN mkdir -p /app/data /app/logs && \
    sed -i 's|db_path:.*|db_path: "data/paleonews.db"|' config.yaml && \
    sed -i 's|file:.*|file: "logs/paleonews.log"|' config.yaml

VOLUME ["/app/data", "/app/logs"]

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["run"]
