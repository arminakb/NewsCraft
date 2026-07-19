ARG PYTHON_IMAGE=python:3.14.6-slim-bookworm@sha256:86f975aca15cf04a40b399eebede9aea7c82eae084d1f1a0a6ef6bcaae871a30
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.11.29@sha256:eb2843a1e56fd9e30c7276ce1a52cba86e64c7b385f5e3279a0e08e02dd058fc

FROM ${UV_IMAGE} AS uv-bin

FROM ${PYTHON_IMAGE} AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app

COPY --from=uv-bin /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

COPY app ./app
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

FROM ${PYTHON_IMAGE} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH

RUN groupadd --gid 10001 newscraft \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin newscraft \
    && mkdir -p /app /data/media /data/exports /data/media-staging \
    && chown -R newscraft:newscraft /app /data /home/newscraft

WORKDIR /app

COPY --from=builder --chown=newscraft:newscraft /opt/venv /opt/venv
COPY --from=builder --chown=newscraft:newscraft /app/alembic.ini ./alembic.ini
COPY --from=builder --chown=newscraft:newscraft /app/alembic ./alembic

USER newscraft

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
