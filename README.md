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
`requests`) and the `crap2feed` command inside `.venv`.

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
```

Edit `feeds` to point at the blog index pages you want feeds for. `output`
is optional; if omitted, the filename is derived from the feed `name`.

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

## Development

```sh
uv sync --dev          # install ruff + mypy alongside runtime deps
uv run ruff check .    # lint
uv run ruff format .   # format
uv run mypy crap2feed.py  # type-check
```

[pre-commit](https://pre-commit.com/) hooks are configured in
`.pre-commit-config.yaml` (ruff, generic file checks, editorconfig,
zizmor). Install with `uv tool install pre-commit && pre-commit install`.

See [AGENTS.md](AGENTS.md) for conventions AI coding agents should follow
in this repo.

## License

MIT — see [LICENSE](LICENSE).
