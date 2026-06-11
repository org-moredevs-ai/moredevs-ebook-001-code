FROM mcr.microsoft.com/devcontainers/python:1-3.13-bookworm

# Install uv (Astral package manager)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    mv /root/.local/bin/uv /usr/local/bin/uv && \
    mv /root/.local/bin/uvx /usr/local/bin/uvx

# OS tools used across recipes (PlatformIO, Mermaid CLI, image processing, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libgl1 \
    libglib2.0-0 \
    mosquitto-clients \
    postgresql-client \
    make \
    && rm -rf /var/lib/apt/lists/*

# Pre-warm uv cache to a persistent location
ENV UV_CACHE_DIR=/home/vscode/.cache/uv
RUN mkdir -p /home/vscode/.cache/uv && chown -R vscode:vscode /home/vscode/.cache
