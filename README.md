# crap2feed

Since many companies and organisations don't think that RSS/Atom is needed
for blogs, this tool scrapes their blog index pages and generates Atom
feeds for them anyway.

It works by fetching a blog's index page, finding links that look like
articles, and pulling title/description/image/date metadata out of each
article page (JSON-LD, Open Graph tags, or a best-effort fallback). The
result is written out as a standard Atom 1.0 XML file that any feed reader
can subscribe to.

Some blogs render their post list purely client-side and have no `<a href>`
markup for individual posts in the raw HTML at all (e.g. Next.js sites that
embed the post list as JSON in a `__NEXT_DATA__` script tag). When the
normal link-scrape finds nothing, crap2feed falls back to hunting through
that embedded JSON for a list that looks like a set of blog posts, so these
"different types of crap blogs" are supported too, not just the plain
link-list ones.

## Requirements

- Python 3.14+
- [uv](https://docs.astral.sh/uv/)

## Installation

```sh
git clone https://github.com/reuteras/crap2feed.git
cd crap2feed
uv sync
```

This installs the runtime dependencies (`beautifulsoup4`, `pyyaml`,
`requests`, `urllib3`) and the `crap2feed` command inside `.venv`.

## Configuration

crap2feed reads a YAML config file (`crap2feed.yaml` by default). Generate a
starter file with:

```sh
uv run crap2feed --init
```

which writes:

```yaml
settings:
  max_items: 20          # articles per feed
  output_dir: ./feeds    # where to write .xml files

feeds:
  - name: Pillar Security Blog
    url: https://www.pillar.security/blog
    output: pillar.xml

  - name: Sekoia Blog
    url: https://www.sekoia.com/blog
    output: sekoia.xml

  - name: AAIF Blog
    url: https://aaif.io/blog
    output: aaif.xml
```

Edit `feeds` to point at the blog index pages you want feeds for. `output`
is optional; if omitted, the filename is derived from the feed `name`.

Optional settings:

```yaml
settings:
  # ...
  flaresolverr_url: http://flaresolverr:8191/v1  # unset/absent = disabled
  serve_host: 0.0.0.0    # --serve bind address
  serve_port: 8002       # --serve port
  serve_ttl: 900          # seconds a generated feed is reused before --serve regenerates it
```

`flaresolverr_url` points at a running
[FlareSolverr](https://github.com/FlareSolverr/FlareSolverr) instance. It's
opt-in: leave it unset and crap2feed behaves exactly as before. When set, a
403 response from a direct fetch (Cloudflare/bot-protection challenges) is
transparently retried through FlareSolverr instead of giving up, and the
offending host is remembered for the rest of the run so later requests to
it skip straight to FlareSolverr. This applies to both a feed's index page
and its article pages. Note that FlareSolverr resolves redirects itself
inside its own headless browser, so crap2feed can't apply its usual
same-host redirect check to those hops — enabling FlareSolverr for a host
means trusting FlareSolverr's own network egress for it.

## Usage

```sh
# Generate all configured feeds into settings.output_dir
uv run crap2feed

# Generate only one feed (partial, case-insensitive name/url match)
uv run crap2feed --feed "Pillar Security"

# Use a config file at a different path
uv run crap2feed --config /etc/crap2feed.yaml

# List configured feeds and their output paths without generating anything
uv run crap2feed --list

# Write the example config and exit
uv run crap2feed --init

# Check whether crap2feed can find articles at a URL, no config needed
uv run crap2feed --check https://example.com/blog

# Spoof a Firefox User-Agent instead of the default, honest one
uv run crap2feed --agent firefox

# Only log warnings/errors (quiet, cron-friendly)
uv run crap2feed --quiet

# Also copy generated feed files to a second directory (e.g. a web server dir)
uv run crap2feed --copy /var/www/feeds

# Serve feeds on demand over HTTP instead of generating once and exiting
uv run crap2feed --serve
```

Each run writes one `.xml` file per feed into `output_dir`, plus a
`.crap2feed_cache.json` file that stores metadata already fetched for each
article. The cache avoids re-fetching and re-hammering source sites on
every run, and articles that fall off the index page are automatically
dropped from it. Run crap2feed on a schedule (cron, systemd timer, etc.) and
serve `output_dir` with any static file server to get feeds that stay up to
date.

All log output goes to stderr, so `> /dev/null` alone won't silence it; use
`--quiet` to drop INFO-level messages and only log warnings/errors, which
plays nicer with cron's default of mailing anything a job prints. If you
keep your checkout separate from the directory your web server serves
(e.g. `output_dir` is a working copy and a web server reads from
`/var/www/feeds`), pass `--copy DIR` to also copy each generated `.xml`
file there after it's written. A typical crontab entry:

```cron
*/30 * * * * cd /path/to/crap2feed && uv run crap2feed --quiet --copy /var/www/feeds
```

### Serving feeds on demand (`--serve`)

Instead of a scheduled generate-and-write run, `--serve` starts an HTTP
server (bound to `settings.serve_host`/`serve_port`, default
`0.0.0.0:8002`) that generates feeds the first time they're requested and
reuses the on-disk copy for `settings.serve_ttl` seconds (default 900)
before regenerating on the next request — so a feed reader that polls every
few minutes doesn't cause a re-scrape on every poll. Only the exact output
filenames configured under `feeds` are served (e.g.
`http://localhost:8002/pillar.xml`); anything else 404s. This is the mode
to use when pointing a feed reader like [Miniflux](https://miniflux.app/)
straight at crap2feed instead of at a static file server — see "Running in
a container" below.

## Being a good crawler

- By default requests identify as `crap2feed/<version> (+https://github.com/reuteras/crap2feed)`
  so site operators can recognize and allowlist/rate-limit the bot instead
  of lumping it in with browser traffic. `--agent firefox` opts into a
  spoofed browser UA if a site otherwise blocks non-browser clients.
- Fetches are sequential (no concurrency) with a polite delay between
  newly-fetched articles; cached articles are skipped entirely.
- On rate-limiting or transient server errors (429/500/502/503/504),
  requests are retried with backoff, honoring a `Retry-After` header when
  the server sends one, instead of immediately giving up or hammering
  the server again next run.
- We don't consult `robots.txt` — crap2feed only ever fetches a blog's own
  public index page and the article links found on it, i.e. pages the
  operator already intends the public to browse.

## Running in a container

The included `Dockerfile` builds a small image (two-stage: `uv` only exists
in the build stage, the runtime image has no package manager at all) that
runs `crap2feed --serve`. Config and generated feeds live on a `/data`
volume. The container runs as uid/gid 1000 (not root); if your host's
first user isn't uid 1000, `chown -R 1000:1000` the directory you bind-mount
to `/data`.

```sh
docker build -t crap2feed .
```

`/data/crap2feed.yaml` (mounted in) should set `output_dir: /data/feeds`
and bind to all interfaces so other containers on the same network can
reach it:

```yaml
settings:
  output_dir: /data/feeds
  serve_host: 0.0.0.0
  serve_port: 8002
  flaresolverr_url: http://flaresolverr:8191/v1  # only if you run FlareSolverr too

feeds:
  - name: Pillar Security Blog
    url: https://www.pillar.security/blog
    output: pillar.xml
```

To run it alongside an existing Miniflux + FlareSolverr `docker compose`
stack, add a service on the same network — no host port mapping is needed
since Miniflux reaches it by service name:

```yaml
services:
  crap2feed:
    build: /path/to/crap2feed   # or a pinned image once you're building one
    restart: unless-stopped
    volumes:
      - ./crap2feed:/data
    # same network as your miniflux/flaresolverr services
```

Then in Miniflux, add each feed as `http://crap2feed:8002/<output>.xml`
(e.g. `http://crap2feed:8002/pillar.xml`) instead of the blog's own URL.

### Adding to another repo's docker-compose (git submodule)

If Miniflux/FlareSolverr already live in their own repo with a
`docker-compose.yml`, add crap2feed there as a git submodule rather than a
remote build context — a submodule pins an exact commit (consistent with
how this project pins its own dependencies) and doesn't need live GitHub
access at build time:

```sh
cd /path/to/miniflux-repo
git submodule add https://github.com/reuteras/crap2feed.git crap2feed
```

Then point the compose service's build context at the submodule directory:

```yaml
services:
  crap2feed:
    build:
      context: ./crap2feed
    restart: unless-stopped
    volumes:
      - ./crap2feed-data:/data
    # same network as your miniflux/flaresolverr services
```

Anyone cloning the miniflux repo afterward needs the submodule initialized
too (`git clone --recurse-submodules`, or `git submodule update --init` on
an existing clone). To pick up crap2feed changes later:

```sh
cd crap2feed && git pull && cd ..
git add crap2feed && git commit -m "Bump crap2feed submodule"
```

## Development

```sh
uv sync --dev          # install ruff + mypy alongside runtime deps
uv run ruff check .    # lint
uv run ruff format .   # format
uv run mypy crap2feed.py  # type-check
```

[pre-commit](https://pre-commit.com/) hooks are configured in
`.pre-commit-config.yaml` (ruff, generic file checks, editorconfig,
markdownlint). Install with `uv tool install pre-commit && pre-commit install`.

See [AGENTS.md](AGENTS.md) for conventions AI coding agents should follow
in this repo.

## License

MIT — see [LICENSE](LICENSE).
