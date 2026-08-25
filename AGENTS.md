# AGENTS.md

Guidance for AI coding agents working in this repository. Human-facing docs
are in [README.md](README.md).

## Project shape

- `crap2feed.py` is the entire application: a single flat module (not a
  package). CLI entry point is `main()`, wired up via
  `[project.scripts] crap2feed = "crap2feed:main"` and
  `[tool.setuptools] py-modules = ["crap2feed"]` in `pyproject.toml`. Don't
  turn this into a package (`crap2feed/__init__.py` etc.) without updating
  both of those.
- `crap2feed.yaml` (user config) and `feeds/` (generated output +
  `.crap2feed_cache.json`) are gitignored and only exist locally/at runtime.
  Don't assume they exist; `load_config` creates an example config if
  missing.
- `.crap2feed_cache.json`'s top level is keyed by feed name, but also holds
  one reserved key, `CACHE_HOSTS_KEY` (`"__hosts__"`), for FlareSolverr host
  state. Each per-feed dict is keyed by article URL, but also holds one
  reserved key, `CACHE_META_KEY` (`"__meta__"`), for that feed's remembered
  index strategy. Both reserved keys deliberately reuse the existing
  `dict[str, dict[str, str]]` shape rather than needing a schema change —
  see "Remembering how to reach a site" below. Anything that iterates feed
  names or article URLs in the cache must skip these keys (see the stale-
  entry cleanup in `generate_feed`).
- `tests/test_crap2feed.py` covers the pure-logic functions (date
  parsing/formatting, XML escaping, `__NEXT_DATA__` scoring, anchor
  scraping, Atom rendering) with stdlib-free unit tests via pytest — a
  deliberate dev dependency, not one added speculatively (see dependency
  policy below). Network-touching functions (`fetch`, `get_article_metadata`)
  aren't covered; they'd need mocked HTTP. Run with `uv run pytest`.
- CLI argument parsing lives in `build_parser()`, separate from `main()`,
  purely to stay under ruff's `PLR0915` (too-many-statements) limit — `main()`
  was already close to the ceiling before `--quiet`/`--copy` pushed it over.
  If you add another flag, add it to `build_parser()`, not inline in
  `main()`.
- All logging goes to `stderr` (`logging.basicConfig(..., stream=sys.stderr)`
  at import time) — `> /dev/null` alone never silences it. `--quiet` raises
  the *root* logger to `WARNING` at the top of `main()`; `log =
  logging.getLogger("crap2feed")` is a child logger with no level of its own,
  so it inherits whatever the root is set to. Don't set the level on `log`
  directly for this — that would only affect this one module's logger, not
  any other loggers that might exist.

## Before committing changes to crap2feed.py

Run all four; the project's mypy/ruff config is strict on purpose:

```sh
uv run ruff check .
uv run ruff format .
uv run mypy crap2feed.py
uv run pytest
```

- Every function must have full type annotations (`disallow_untyped_defs`,
  `disallow_incomplete_defs` are on) and a docstring (ruff `D` rules,
  Google convention). `ruff check` has `fix = true`, so it will
  auto-fix what it can — review the diff, don't just trust it blindly.
  `E501` (line length) is intentionally ignored; `ruff format` is the
  source of truth for layout.
- Avoid magic numbers in comparisons (`PLR2004`) — pull them into a named
  `UPPER_CASE` constant near the function that uses them, as done for
  `MIN_SLUG_LENGTH`, `MIN_LINK_TEXT_LENGTH`, etc.
- `bs4`, `requests`, and `yaml` are covered by `ignore_missing_imports`
  overrides in `[tool.mypy]` rather than `types-*` stub packages — keep it
  that way (see dependency policy below) rather than adding stub
  dependencies to make mypy quieter. `urllib3` ships its own inline types
  (`py.typed`), so it doesn't need an override.

## Dependency policy

Default to stdlib. Adding a new third-party dependency should be a
deliberate choice, not a convenience:

- Runtime deps (`beautifulsoup4`, `pyyaml`, `requests`, `urllib3`) and dev
  deps (`ruff`, `mypy`, `pytest` in `[dependency-groups] dev`) are declared
  with `>=` floors in `pyproject.toml`; `uv.lock` is the actual pin and must
  stay committed and in sync (`uv sync --dev` after any manifest change).
  `urllib3` is declared directly (not left as an implicit transitive dep
  of `requests`) because `crap2feed.py` imports `urllib3.util.retry.Retry`
  directly, for the retry/backoff adapter — don't rely on a package you
  import only being present transitively.
- `pytest` was a deliberate addition (see Tests below), not a speculative
  one. Don't add `types-*` stub packages, additional test plugins, or other
  tooling speculatively on top of it — if a task needs one, say so
  explicitly rather than installing it silently.
- Match `ruff`'s floor in `[dependency-groups]` to the version pinned in
  `.pre-commit-config.yaml` when bumping either one, so local runs,
  `uv run`, and the pre-commit hook stay consistent.
- `--serve` and the FlareSolverr fallback added no new dependencies — the
  HTTP server is stdlib `http.server`/`threading`, and FlareSolverr's API is
  called with the already-present `requests`. Keep it that way; don't reach
  for a web framework for `--serve`.
- `Dockerfile` pins `ghcr.io/astral-sh/uv:0.12.1` by exact tag (no
  `latest`) for the `uv` binary used only in the build stage, matching the
  no-version-ranges pinning discipline used everywhere else. The runtime
  stage copies just `/app/.venv` and `crap2feed.py` out of the build stage —
  no `uv`/pip in the final image at all. Bump the pinned `uv` tag
  deliberately (same review lens as any other dependency bump), not as a
  drive-by edit.

## Three index-scraping strategies, tried in order until one works

`scrape_index` tries `scrape_index_anchors` first (the original strategy:
walk `<a href>` tags on the index page). If that finds nothing —
e.g. security.apple.com/blog, a Next.js app whose post list is rendered
entirely client-side from JSON, with no `<a href>` markup for posts
anywhere in the raw HTML — it falls back to `scrape_index_nextdata`, which
parses the `__NEXT_DATA__` script tag's JSON and recursively searches it
(`find_nextdata_post_lists`) for a list of dicts that look like post
entries (has a title-like key from `NEXTDATA_TITLE_KEYS` and a link-like
key from `NEXTDATA_LINK_KEYS`), then picks the best-scoring candidate
(`score_nextdata_post_list`, biased toward lists that also carry date/
description keys — a site's JSON can embed more than one dict-list shape,
e.g. related posts alongside the full index). If that also finds nothing,
it falls back to `scrape_index_public_blog_json`, which fetches a
conventional same-host `/bin/blog/blog-index.json` (`PUBLIC_BLOG_INDEX_PATH`)
— a *different URL* from the blog's HTML page entirely, unlike the other
two strategies which both parse the one page already fetched for `soup`.

Each strategy is deliberately generic (keyed off shape-matching — presence
of `__NEXT_DATA__`, or a JSON list of dicts with title/url/date-ish keys —
not any site-specific string), since more than one "crap blog" can share
the same rendering/CMS pattern. If you add a fourth strategy for some other
pattern, follow the same shape: a function returning `list[dict[str, str]]`
with `{url, title, date_str}` (optionally `description`), tried only when
the earlier strategies come up empty, not merged with them. Also add its
name as an `INDEX_STRATEGY_*` constant and teach `scrape_index`'s ordering
logic about it (see below) — don't let a new strategy bypass the memoization.

### Remembering how to reach a site

Every new strategy added here is a strategy every *already-working* site
also pays to skip past on every single run, and (worse) a strategy that
fetches its own URL — like `scrape_index_public_blog_json` — costs a real
extra HTTP request on every run for a site that only ever works that way.
To keep that a one-time cost instead of a permanent tax:

- `generate_feed` reads the feed's last-known strategy from
  `feed_cache[CACHE_META_KEY]["index_strategy"]` and passes it to
  `scrape_index` as `known_strategy`. `scrape_index` tries that strategy
  first; only if it comes up empty (site changed layout, or this is the
  first run and there's no known strategy yet) does it fall back to probing
  all strategies in the default order. Whichever strategy actually produced
  articles is written back to the cache.
- Critically, when `known_strategy == INDEX_STRATEGY_PUBLIC_JSON`,
  `scrape_index` tries it *before* fetching the blog's HTML page at all —
  since that strategy doesn't use the HTML `soup`, a site known to need it
  costs exactly one request per run (the JSON fetch), not two (HTML fetch
  that goes nowhere, plus the JSON fetch). Preserve this ordering if you
  touch `scrape_index`; don't reintroduce an unconditional `fetch(blog_url)`
  at the top of the function.
- The same problem exists for FlareSolverr: `FLARESOLVERR.hosts` (in-memory,
  see below) is now mirrored into `cache[CACHE_HOSTS_KEY]` via
  `seed_flaresolverr_hosts`/`save_flaresolverr_hosts`, called around
  `load_cache`/`save_cache` in both `write_feeds` and `FeedServer`. Without
  this, a host discovered to need FlareSolverr would rediscover that fact
  (one wasted direct request that 403s) on every fresh process — e.g. every
  cron invocation — forever, instead of just the first time.

## Remote content is untrusted — security invariants in fetch()/scrape_index()

crap2feed fetches attacker-reachable content (any blog in the config can
serve a compromised or hostile index page), and that content directly
influences what other URLs get fetched next. Do not weaken any of these
without understanding why they're there:

- `scrape_index_anchors` only queues links whose scheme is `http`/`https`
  and whose `netloc` matches the configured blog's host. Without this, a
  malicious index page can plant a same-path link (`/blog/whatever`)
  pointing at a completely different host — internal services, cloud
  metadata endpoints, etc. — and crap2feed would fetch it as if it were an
  article. `scrape_index_nextdata`/`nextdata_item_to_article` apply the
  same same-host/same-scheme check to URLs built from `__NEXT_DATA__`
  JSON — that JSON is just as untrusted as the HTML it's embedded in.
- `fetch()` calls `SESSION.get(..., allow_redirects=False)` and resolves
  redirects itself, checking the `Location` header's host __before__
  issuing the next request. This was originally written with
  `allow_redirects=True` plus a check on `r.url` *after* the call returned
  — that looks equivalent but isn't: `requests` had already completed the
  full request to the redirect target by the time the check ran. Verified
  with a local test server acting as the "internal" redirect target: with
  `allow_redirects=True` it received and answered the request before the
  post-hoc check discarded the result; with the manual hop-by-hop version
  it never received a request at all. If you touch redirect handling here,
  re-verify the same way — a check that runs after the network call is not
  a mitigation.
- `fetch()` streams the response body and aborts once it exceeds
  `MAX_RESPONSE_BYTES` (10 MB), so a hostile/huge page can't exhaust
  memory.
- `xml_escape()` strips XML-illegal control characters before entity-
  escaping, since remote titles/descriptions can contain anything.
- The default `User-Agent` (`HONEST_USER_AGENT`) is built from the
  installed package version via `importlib.metadata.version("crap2feed")`,
  not a hardcoded string — don't duplicate the version number from
  `pyproject.toml` here. `--agent firefox` swaps in `FIREFOX_USER_AGENT`
  for sites that block non-browser UAs.
- Retries/backoff live on the `HTTPAdapter` via `urllib3.util.retry.Retry`
  (`RETRY_TOTAL`, `RETRY_BACKOFF_FACTOR`, `RETRY_STATUS_FORCELIST`,
  `respect_retry_after_header=True`) in `build_session()`, not hand-rolled
  — prefer extending the `Retry` config over adding a manual retry loop.
- `fetch()` dispatches to `_fetch_direct()` first, falling back to
  `fetch_via_flaresolverr()` only on a 403 when `FLARESOLVERR.url` is set
  (from `settings.flaresolverr_url`). `FLARESOLVERR.hosts` remembers which
  hosts needed it so later requests skip the doomed direct attempt —
  this now persists across process restarts too, via the on-disk cache
  (see "Remembering how to reach a site" above), not just within one run.
  __This is the one place that knowingly loses a safety property above__:
  FlareSolverr resolves redirects itself inside its own headless browser and
  only hands back the final HTML, so the same-host redirect check in
  `_fetch_direct()` never runs for FlareSolverr-routed requests. Enabling
  FlareSolverr for a host means trusting FlareSolverr's own egress/redirect
  handling for it — acceptable for a self-hosted tool with a fixed, known
  blog list, but don't extend the fallback to anything beyond a plain 403
  (e.g. don't start sniffing response bodies for Cloudflare challenge markup)
  without re-thinking this tradeoff.
- `FLARESOLVERR` is a small mutable dataclass instance (`FlareSolverrState`),
  not a plain `str | None` module global — `main()` sets `FLARESOLVERR.url`
  as an attribute assignment rather than rebinding a module-level name, so
  it doesn't need (and ruff's `PLW0603` would otherwise flag) a `global`
  statement. `SESSION.headers["User-Agent"]` mutation for `--agent firefox`
  follows the same "mutate an object's attribute, don't rebind the name"
  shape.

## `--serve`: on-demand generation, not a general static file server

`FeedServer` (a `ThreadingHTTPServer`) and `FeedHandler` back the `--serve`
flag. Two things to preserve if you touch this:

- `FeedHandler.do_GET` matches `self.path.lstrip("/")` against
  `feeds_by_output` __exactly__ — it is not a directory listing or general
  file server over `output_dir`. `output_dir` also contains
  `.crap2feed_cache.json` (raw scraped metadata) and, in principle, only the
  configured `output` filenames should ever be reachable over HTTP. Don't
  swap this for `http.server.SimpleHTTPRequestHandler` or similar without
  re-adding that allowlist.
- `FeedServer.feed_locks` is pre-populated for every configured feed at
  construction time, not created lazily on first request — creating a
  `threading.Lock()` lazily (`feed_locks.setdefault(...)`) would itself be a
  race between concurrent request threads for a feed neither has seen yet.
  `cache_lock` is separate and narrower: it only wraps `save_cache()` (the
  shared on-disk JSON write), not feed generation itself, so two different
  feeds regenerating at the same time don't serialize on one lock — only the
  disk write of the shared cache dict does.

## Gotchas already hit in this repo

- The original `pyproject.toml` had `readme`/`license`/`classifiers` keys
  placed after `[build-system]` instead of under `[project]` — TOML
  silently let this parse, but setuptools never applied that metadata.
  Keep all `[project]` keys contiguous under the `[project]` header, above
  `[build-system]`, or setuptools will either drop them silently or (once
  `[tool.setuptools]` exists) fail the build outright with an "unknown
  key" error.
- `console_scripts` pointing at `crap2feed.main:main` will fail at runtime
  with `ModuleNotFoundError` — there is no `crap2feed` package or `main`
  submodule, just `crap2feed.py`. The correct target is `crap2feed:main`.
- Verify packaging changes with `uv build` and inspecting the resulting
  wheel (`unzip -l dist/*.whl`), not just `uv sync` — `uv sync` uses an
  editable install and won't catch entry-point or `py-modules` mistakes
  that only surface in a real wheel.
