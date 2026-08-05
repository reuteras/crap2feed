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

# uid/gid 1000 matches the default first-user uid on most Linux hosts, so a
# bind-mounted ./something:/data (see README) is writable without an extra
# chown on the host side in the common case.
RUN groupadd --gid 1000 crap2feed \
    && useradd --uid 1000 --gid crap2feed --home-dir /data --shell /usr/sbin/nologin crap2feed \
    && mkdir -p /data \
    && chown crap2feed:crap2feed /data

WORKDIR /app
COPY --from=builder --chown=crap2feed:crap2feed /app/.venv /app/.venv
COPY --chown=crap2feed:crap2feed crap2feed.py ./

EXPOSE 8002
VOLUME ["/data"]
USER crap2feed

# --serve doesn't expose a fixed "/" route (see AGENTS.md), so this only
# checks that something is listening on the port, not a specific response.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python3 -c "import socket; socket.create_connection(('127.0.0.1', 8002), 3).close()" || exit 1

ENTRYPOINT ["/app/.venv/bin/crap2feed"]
CMD ["--config", "/data/crap2feed.yaml", "--serve"]
