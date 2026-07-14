# syntax=docker/dockerfile:1
#
# Multi-stage build.
#  - pybuild   : compile/collect Python deps (lxml build headers live here only)
#  - claudecli : fetch the NATIVE Claude Code binary (no Node.js runtime needed)
#  - runtime   : slim final image = base + python deps + native claude + cron
#
# The Claude Code CLI ships as a self-contained native ELF binary, so the
# previous Node.js runtime (node ~120MB + npm/node_modules) is unnecessary.

# ---- Stage 1: Python dependencies ----
FROM python:3.12-slim AS pybuild
WORKDIR /app
# Build headers for lxml's source fallback (kept out of the final image).
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc libxml2-dev libxslt1-dev && \
    rm -rf /var/lib/apt/lists/*
COPY pyproject.toml .
COPY paleonews/ paleonews/
# Install into an isolated prefix we can copy wholesale into the runtime stage.
RUN pip install --no-cache-dir --prefix=/install .

# ---- Stage 2: Native Claude Code CLI ----
FROM python:3.12-slim AS claudecli
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    # Installs the native binary to /root/.local/share/claude/versions/<v>
    # with a launcher symlink at /root/.local/bin/claude. No Node.js involved.
    curl -fsSL https://claude.ai/install.sh | bash

# ---- Stage 3: Runtime ----
FROM python:3.12-slim
WORKDIR /app

# Runtime-only system deps: cron (scheduler), CA certs (HTTPS), lxml shared libs,
# gosu (deploy-contract privilege-drop scaffolding — dormant; all-mode runs as root).
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        cron ca-certificates libxml2 libxslt1.1 gosu && \
    rm -rf /var/lib/apt/lists/*

# Python packages + console scripts from the build stage.
COPY --from=pybuild /install /usr/local

# Native Claude Code binary + launcher (no Node.js). Expose on PATH.
COPY --from=claudecli /root/.local /root/.local
RUN ln -sf /root/.local/bin/claude /usr/local/bin/claude

# App config/assets (paleonews package itself is already installed above).
COPY sources.txt config.yaml ./
COPY deploy/entrypoint.sh /app/entrypoint.sh
# Deploy-contract host artifacts — extracted from the image on each deploy (git-free
# self-heal): host verb scripts + hourly backup + claude-token helper.
COPY deploy/host /app/deploy/host
COPY scripts/backup_db.py scripts/apply_claude_token.sh /app/scripts/

# Use /app/data for DB, /app/logs for logs
RUN mkdir -p /app/data /app/logs && \
    sed -i 's|^db_path:.*|db_path: "data/paleonews.db"|' config.yaml && \
    sed -i 's|^  file:.*|  file: "logs/paleonews.log"|' config.yaml

VOLUME ["/app/data", "/app/logs"]

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["run"]
