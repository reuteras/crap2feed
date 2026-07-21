# AGENTS.md

Guidance for AI coding agents working in this repository. Human-facing docs
are in [README.md](README.md).

## Project shape

- `crap2rss.py` is the entire application: a single flat module (not a
  package). CLI entry point is `main()`, wired up via
  `[project.scripts] crap2rss = "crap2rss:main"` and
  `[tool.setuptools] py-modules = ["crap2rss"]` in `pyproject.toml`. Don't
  turn this into a package (`crap2rss/__init__.py` etc.) without updating
  both of those.
- `crap2rss.yaml` (user config) and `feeds/` (generated output +
  `.crap2rss_cache.json`) are gitignored and only exist locally/at runtime.
  Don't assume they exist; `load_config` creates an example config if
  missing.
- No test suite exists yet. `.github/workflows/tests.yml` references
  `src/rwreader`, `READWISE_TOKEN`, and `tests/` — that's leftover from a
  different project template and does not apply here; don't treat it as a
  source of truth for how to test this repo.

## Before committing changes to crap2rss.py

Run all three; the project's mypy/ruff config is strict on purpose:

```sh
uv run ruff check .
uv run ruff format .
uv run mypy crap2rss.py
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
  deps (`ruff`, `mypy` in `[dependency-groups] dev`) are declared with `>=`
  floors in `pyproject.toml`; `uv.lock` is the actual pin and must stay
  committed and in sync (`uv sync --dev` after any manifest change).
  `urllib3` is declared directly (not left as an implicit transitive dep
  of `requests`) because `crap2rss.py` imports `urllib3.util.retry.Retry`
  directly, for the retry/backoff adapter — don't rely on a package you
  import only being present transitively.
- Don't add `types-*` stub packages, testing frameworks, or other tooling
  speculatively — if a task needs one, say so explicitly rather than
  installing it silently.
- Match `ruff`'s floor in `[dependency-groups]` to the version pinned in
  `.pre-commit-config.yaml` when bumping either one, so local runs,
  `uv run`, and the pre-commit hook stay consistent.

## Remote content is untrusted — security invariants in fetch()/scrape_index()

crap2rss fetches attacker-reachable content (any blog in the config can
serve a compromised or hostile index page), and that content directly
influences what other URLs get fetched next. Do not weaken any of these
without understanding why they're there:

- `scrape_index` only queues links whose scheme is `http`/`https` and whose
  `netloc` matches the configured blog's host. Without this, a malicious
  index page can plant a same-path link (`/blog/whatever`) pointing at a
  completely different host — internal services, cloud metadata endpoints,
  etc. — and crap2rss would fetch it as if it were an article.
- `fetch()` calls `SESSION.get(..., allow_redirects=False)` and resolves
  redirects itself, checking the `Location` header's host **before**
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
  installed package version via `importlib.metadata.version("crap2rss")`,
  not a hardcoded string — don't duplicate the version number from
  `pyproject.toml` here. `--agent firefox` swaps in `FIREFOX_USER_AGENT`
  for sites that block non-browser UAs.
- Retries/backoff live on the `HTTPAdapter` via `urllib3.util.retry.Retry`
  (`RETRY_TOTAL`, `RETRY_BACKOFF_FACTOR`, `RETRY_STATUS_FORCELIST`,
  `respect_retry_after_header=True`) in `build_session()`, not hand-rolled
  — prefer extending the `Retry` config over adding a manual retry loop.

## Gotchas already hit in this repo

- The original `pyproject.toml` had `readme`/`license`/`classifiers` keys
  placed after `[build-system]` instead of under `[project]` — TOML
  silently let this parse, but setuptools never applied that metadata.
  Keep all `[project]` keys contiguous under the `[project]` header, above
  `[build-system]`, or setuptools will either drop them silently or (once
  `[tool.setuptools]` exists) fail the build outright with an "unknown
  key" error.
- `console_scripts` pointing at `crap2rss.main:main` will fail at runtime
  with `ModuleNotFoundError` — there is no `crap2rss` package or `main`
  submodule, just `crap2rss.py`. The correct target is `crap2rss:main`.
- Verify packaging changes with `uv build` and inspecting the resulting
  wheel (`unzip -l dist/*.whl`), not just `uv sync` — `uv sync` uses an
  editable install and won't catch entry-point or `py-modules` mistakes
  that only surface in a real wheel.
