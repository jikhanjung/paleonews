FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for lxml
RUN apt-get update && \
    apt-get install -y --no-install-recommends libxml2-dev libxslt1-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY paleonews/ paleonews/
COPY sources.txt config.yaml ./

RUN pip install --no-cache-dir .

# Use /app/data for DB, /app/logs for logs
RUN mkdir -p /app/data /app/logs && \
    sed -i 's|db_path:.*|db_path: "data/paleonews.db"|' config.yaml && \
    sed -i 's|file:.*logs/paleonews.log|file: "logs/paleonews.log"|' config.yaml

VOLUME ["/app/data", "/app/logs"]

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "-m", "paleonews"]
CMD ["run"]
