# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1: resolve dependencies into a self-contained virtualenv
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

# Pull the uv binary from its official image (no pip/curl bootstrap needed).
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Install dependencies first so this layer is cached when only source changes.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

# ---------------------------------------------------------------------------
# Stage 2: runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim

# tzdata lets the container honour the TZ environment variable; without it
# Python falls back to UTC and the header clock is wrong.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/*

# Run as a non-root user.
RUN groupadd --gid 1000 app \
 && useradd --uid 1000 --gid app --create-home --shell /usr/sbin/nologin app

WORKDIR /app

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app display.py render.py usage.py ./
COPY --chown=app:app fonts ./fonts

# Put the virtualenv on PATH so `python display.py` works without activation.
# TZ controls the clock rendered in the image; override per deployment.
# CLAUDE_TOKEN_CACHE / CODEX_TOKEN_CACHE hold only the *refreshed* tokens. They
# default to paths inside the container and need no mount: if lost (container
# recreated) the app simply refreshes again from the refresh tokens.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai \
    CLAUDE_TOKEN_CACHE=/tmp/claude_token.json \
    CODEX_TOKEN_CACHE=/tmp/codex_token.json

USER app

# Credentials are supplied entirely through environment variables:
#   QUOTE_API_KEY, QUOTE_DEVICE_ID     (required)
#   CLAUDE_ACCESS_TOKEN / CLAUDE_REFRESH_TOKEN
#   CODEX_ACCESS_TOKEN / CODEX_REFRESH_TOKEN / CODEX_ACCOUNT_ID
#   OPENCODE_GO_API_KEY
# No host credential files need to be mounted.

# Healthcheck verifies the image can run and reach the usage APIs.
HEALTHCHECK --interval=5m --timeout=60s --start-period=30s --retries=3 \
    CMD python usage.py --opencode-only >/dev/null 2>&1 || exit 1

# Default: loop every UPDATE_INTERVAL seconds (1800 by default). Pass `--preview`
# to also write /tmp/usage_preview.png.
ENTRYPOINT ["python", "display.py"]
CMD ["--loop"]
