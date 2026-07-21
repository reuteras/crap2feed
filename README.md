# crap2rss

Since many companies and organisations don't think that RSS is needed for
blogs, this tool scrapes their blog index pages and generates RSS feeds for
them anyway.

It works by fetching a blog's index page, finding links that look like
articles, and pulling title/description/image/date metadata out of each
article page (JSON-LD, Open Graph tags, or a best-effort fallback). The
result is written out as a standard RSS 2.0 XML file that any feed reader
can subscribe to.

## Requirements

- Python 3.14+
- [uv](https://docs.astral.sh/uv/)

## Installation

```sh
git clone https://github.com/reuteras/crap2rss.git
cd crap2rss
uv sync
```

This installs the runtime dependencies (`beautifulsoup4`, `pyyaml`,
`requests`) and the `crap2rss` command inside `.venv`.

## Configuration

crap2rss reads a YAML config file (`crap2rss.yaml` by default). Generate a
starter file with:

```sh
uv run crap2rss --init
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
```

Edit `feeds` to point at the blog index pages you want feeds for. `output`
is optional; if omitted, the filename is derived from the feed `name`.

## Usage

```sh
# Generate all configured feeds into settings.output_dir
uv run crap2rss

# Generate only one feed (partial, case-insensitive name/url match)
uv run crap2rss --feed "Pillar Security"

# Use a config file at a different path
uv run crap2rss --config /etc/crap2rss.yaml

# List configured feeds and their output paths without generating anything
uv run crap2rss --list

# Write the example config and exit
uv run crap2rss --init

# Spoof a Firefox User-Agent instead of the default, honest one
uv run crap2rss --agent firefox
```

Each run writes one `.xml` file per feed into `output_dir`, plus a
`.crap2rss_cache.json` file that stores metadata already fetched for each
article. The cache avoids re-fetching and re-hammering source sites on
every run, and articles that fall off the index page are automatically
dropped from it. Run crap2rss on a schedule (cron, systemd timer, etc.) and
serve `output_dir` with any static file server to get feeds that stay up to
date.

## Being a good crawler

- By default requests identify as `crap2rss/<version> (+https://github.com/reuteras/crap2rss)`
  so site operators can recognize and allowlist/rate-limit the bot instead
  of lumping it in with browser traffic. `--agent firefox` opts into a
  spoofed browser UA if a site otherwise blocks non-browser clients.
- Fetches are sequential (no concurrency) with a polite delay between
  newly-fetched articles; cached articles are skipped entirely.
- On rate-limiting or transient server errors (429/500/502/503/504),
  requests are retried with backoff, honoring a `Retry-After` header when
  the server sends one, instead of immediately giving up or hammering
  the server again next run.
- We don't consult `robots.txt` — crap2rss only ever fetches a blog's own
  public index page and the article links found on it, i.e. pages the
  operator already intends the public to browse.

## Development

```sh
uv sync --dev          # install ruff + mypy alongside runtime deps
uv run ruff check .    # lint
uv run ruff format .   # format
uv run mypy crap2rss.py  # type-check
```

[pre-commit](https://pre-commit.com/) hooks are configured in
`.pre-commit-config.yaml` (ruff, generic file checks, editorconfig,
zizmor). Install with `uv tool install pre-commit && pre-commit install`.

See [AGENTS.md](AGENTS.md) for conventions AI coding agents should follow
in this repo.

## License

MIT — see [LICENSE](LICENSE).
