FROM ghcr.io/astral-sh/uv:0.13.6 AS uv

# Builder: only /app/.venv is copied out, so uv/pip never reach runtime.
FROM python:3.15-slim AS builder

COPY --from=uv /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock crap2feed.py README.md LICENSE ./
RUN uv sync --frozen --no-dev

FROM python:3.15-slim AS runtime

# uid/gid 1000 matches the default first-user uid on most Linux hosts, so a
# bind-mounted ./something:/data (see README) needs no extra host-side chown.
RUN groupadd --gid 1000 crap2feed \
    && useradd --uid 1000 --gid crap2feed --home-dir /data --shell /usr/sbin/nologin crap2feed \
    && mkdir -p /data \
    && chown crap2feed:crap2feed /data

WORKDIR /app
COPY --from=builder --chown=crap2feed:crap2feed /app/.venv /app/.venv
COPY --chown=crap2feed:crap2feed crap2feed.py ./

EXPOSE 8002
VOLUME ["/data"]
# Numeric uid:gid (hadolint DL3066) so it resolves even without /etc/passwd
# lookups on the host/runtime side; same ids as the user created above.
USER 1000:1000

# --serve has no fixed "/" route, so this just checks the port is listening.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD ["python3", "-c", "import socket; socket.create_connection(('127.0.0.1', 8002), 3).close()"]

ENTRYPOINT ["/app/.venv/bin/crap2feed"]
CMD ["--config", "/data/crap2feed.yaml", "--serve"]
