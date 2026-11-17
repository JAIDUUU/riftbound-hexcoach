# syntax=docker/dockerfile:1
# The HexCoach API as a portable container (issue #22). Build from backend/:
#   docker build -t hexcoach-backend backend
#   docker run --rm -p 8000:8000 --env-file backend/.env hexcoach-backend
# Configuration is the same environment variables as dev (backend/.env.example); hosts
# inject them as secrets. The embedding model is baked into the image, so a cold start
# never downloads it.

FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

# Editable install (uv's default): config.py locates alembic.ini relative to the source tree.
COPY README.md alembic.ini ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

ENV FASTEMBED_CACHE_PATH=/opt/fastembed
RUN /app/.venv/bin/python -c \
    "from backend.retrieval.embedding import embedder; embedder().embed_query('warm up')"


FROM python:3.13-slim
RUN useradd --create-home --uid 1000 app
WORKDIR /app
COPY --from=build --chown=app /app /app
COPY --from=build --chown=app /opt/fastembed /opt/fastembed

ENV PATH=/app/.venv/bin:$PATH \
    FASTEMBED_CACHE_PATH=/opt/fastembed \
    HF_HUB_OFFLINE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000
USER app
EXPOSE 8000

# Most hosts choose the port through $PORT.
CMD ["sh", "-c", "exec backend serve --host 0.0.0.0 --port \"$PORT\""]
