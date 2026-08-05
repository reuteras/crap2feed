# syntax=docker/dockerfile:1

# Named stage (not COPY --from=ghcr.io/... inline) so Dependabot's docker
# ecosystem can see and bump this pin via the FROM line.
FROM ghcr.io/astral-sh/uv:0.12.1 AS uv

# ── builder ──────────────────────────────────────────────────────────────────
# Build the venv with uv, pinned to an exact tag (no `latest`), per this
# project's dependency-pinning policy. Nothing from this stage except the
# resulting /app/.venv is copied into the runtime image.
FROM python:3.14-slim AS builder

COPY --from=uv /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock crap2feed.py README.md LICENSE ./
RUN uv sync --frozen --no-dev

# ── runtime ──────────────────────────────────────────────────────────────────
# No uv/pip in the final image at all — just Python, the locked venv, and
# the app module, to keep the runtime attack surface small.
FROM python:3.14-slim AS runtime

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY crap2feed.py ./

EXPOSE 8002
VOLUME ["/data"]

ENTRYPOINT ["/app/.venv/bin/crap2feed"]
CMD ["--config", "/data/crap2feed.yaml", "--serve"]
