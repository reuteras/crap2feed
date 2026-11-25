FROM ghcr.io/astral-sh/uv:0.13.10@sha256:a3ea1357342c1a4bf9a0c53a3deb1b55379aefa037338d8113d5771efa01774f AS uv

# Builder: only /app/.venv is copied out, so uv/pip never reach runtime.
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928 AS builder

COPY --from=uv /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock crap2feed.py README.md LICENSE ./
RUN uv sync --frozen --no-dev

FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928 AS runtime

# uid/gid 1000 matches the default first-user uid on most Linux hosts, so a
# bind-mounted ./something:/data (see README) needs no extra host-side chown.
# apt-get upgrade: Debian security updates the official image does not have yet.
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 crap2feed \
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
