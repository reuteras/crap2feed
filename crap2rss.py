#!/usr/bin/env python3
"""crap2rss — generic RSS/Atom feed generator for blogs that lack feeds.

Config file: crap2rss.yaml (or pass --config path/to/file)

Example config:
  feeds:
    - name: Pillar Security
      url: https://www.pillar.security/blog
      output: pillar.xml

    - name: Sekoia Blog
      url: https://www.sekoia.com/blog
      output: sekoia.xml

Usage:
  python3 crap2rss.py                        # generate all feeds from config
  python3 crap2rss.py --feed "Pillar Security"  # one feed only
  python3 crap2rss.py --config /etc/crap2rss.yaml
  python3 crap2rss.py --list                 # list configured feeds

The generated files can be served by any static file server.
"""

import argparse
import json
import logging
import mimetypes
import re
import sys
import time
from datetime import UTC, datetime
from email.utils import formatdate
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as installed_version
from pathlib import Path
from typing import Any, cast
from urllib.parse import urljoin, urlparse

try:
    import requests
    import yaml
    from bs4 import BeautifulSoup, Tag
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    sys.exit("Missing dependencies. Run: uv sync")

# ── Logging ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
    stream=sys.stderr,
)
log = logging.getLogger("crap2rss")

# ── HTTP config ────────────────────────────────────────────────────────────────


def _package_version() -> str:
    """Return the installed crap2rss version, or a dev fallback."""
    try:
        return installed_version("crap2rss")
    except PackageNotFoundError:
        return "0.0.0-dev"


# Honest by default: identifies the tool and where to complain about it, so
# site operators can allowlist/rate-limit it instead of lumping it in with
# generic browser traffic. --agent firefox opts into spoofing a browser UA.
HONEST_USER_AGENT = (
    f"crap2rss/{_package_version()} (+https://github.com/reuteras/crap2rss)"
)
FIREFOX_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0"
)

BASE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.7",
}
REQUEST_TIMEOUT = 20
DELAY = 0.6  # polite crawl delay between article fetches
MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # abort fetching an implausibly large page

# Back off and retry on rate-limiting/transient errors instead of hammering
# a site that's already telling us to slow down (respects Retry-After).
RETRY_TOTAL = 3
RETRY_BACKOFF_FACTOR = 1.0
RETRY_STATUS_FORCELIST = (429, 500, 502, 503, 504)


# ── Date parsing ───────────────────────────────────────────────────────────────

DATE_FORMATS = [
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
    "%B %d, %Y",  # July 20, 2026
    "%b %d, %Y",  # Jul 20, 2026
    "%d %B %Y",  # 20 July 2026
    "%d %b %Y",  # 20 Jul 2026
    "%B %Y",  # July 2026
]


def parse_date(s: str) -> datetime | None:
    """Parse a date string in any of the known DATE_FORMATS."""
    if not s:
        return None
    s = s.strip().rstrip("Z")
    # Handle timezone offsets like +00:00
    s = re.sub(r"([+-]\d{2}):(\d{2})$", r"\1\2", s)
    for fmt in DATE_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except ValueError:
            continue
    return None


def to_rfc822(dt: datetime | None) -> str:
    """Format a datetime as an RFC 822 string, defaulting to now."""
    if dt is None:
        return formatdate(usegmt=True)
    return formatdate(dt.timestamp(), usegmt=True)


# ── Fetching ───────────────────────────────────────────────────────────────────


def build_session() -> requests.Session:
    """Build the shared HTTP session: honest UA, retry/backoff on the adapter."""
    session = requests.Session()
    session.headers.update(BASE_HEADERS)
    session.headers["User-Agent"] = HONEST_USER_AGENT
    retry = Retry(
        total=RETRY_TOTAL,
        backoff_factor=RETRY_BACKOFF_FACTOR,
        status_forcelist=RETRY_STATUS_FORCELIST,
        respect_retry_after_header=True,
        allowed_methods=frozenset({"GET"}),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


SESSION = build_session()


MAX_REDIRECTS = 5


def fetch(url: str) -> BeautifulSoup:
    """Fetch a URL and parse it into a BeautifulSoup document.

    The URL is remote, untrusted content: redirects are resolved by hand
    (allow_redirects=False) so each hop's host can be checked *before* it is
    requested, rather than after — a check made post-hoc, after
    `requests` has already followed the redirect itself, would be too late:
    the request to the off-host target would already have gone out. The
    body is also capped, so a hostile or compromised server can't exhaust
    memory with an oversized response.
    """
    current = url
    original_netloc = urlparse(url).netloc
    for _ in range(MAX_REDIRECTS):
        r = SESSION.get(
            current, timeout=REQUEST_TIMEOUT, allow_redirects=False, stream=True
        )
        if r.is_redirect:
            location = r.headers.get("Location", "")
            r.close()
            next_url = urljoin(current, location)
            if urlparse(next_url).netloc != original_netloc:
                raise ValueError(
                    f"refused cross-host redirect from {current} to {next_url}"
                )
            current = next_url
            continue

        r.raise_for_status()
        content = bytearray()
        for chunk in r.iter_content(chunk_size=65536):
            content += chunk
            if len(content) > MAX_RESPONSE_BYTES:
                raise ValueError(
                    f"response for {url} exceeded {MAX_RESPONSE_BYTES} bytes"
                )
        return BeautifulSoup(bytes(content), "html.parser")

    raise ValueError(f"too many redirects fetching {url}")


# ── Article metadata extraction ────────────────────────────────────────────────


def extract_jsonld(soup: BeautifulSoup) -> dict[str, Any]:
    """Return first JSON-LD block that looks like an article."""
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        # Could be a list or a single object
        candidates = data if isinstance(data, list) else [data]
        for obj in candidates:
            t = obj.get("@type", "")
            if isinstance(t, list):
                t = " ".join(t)
            if any(x in t for x in ("Article", "BlogPosting", "NewsArticle")):
                return cast(dict[str, Any], obj)
    return {}


def extract_og(soup: BeautifulSoup) -> dict[str, str]:
    """Extract Open Graph meta tags."""
    og: dict[str, str] = {}
    for tag in soup.find_all("meta"):
        prop = tag.get("property", "") or tag.get("name", "")
        content = str(tag.get("content", "") or "").strip()
        if not content:
            continue
        if prop in ("og:title", "twitter:title"):
            og.setdefault("title", content)
        elif prop in ("og:description", "description", "twitter:description"):
            og.setdefault("description", content)
        elif prop == "og:image":
            og.setdefault("image", content)
        elif prop in ("article:published_time", "og:article:published_time"):
            og.setdefault("date", content)
    return og


MIN_PARAGRAPH_LENGTH = 80
PARAGRAPH_EXCERPT_LENGTH = 500


def first_real_paragraph(soup: BeautifulSoup) -> str:
    """Fallback: first substantial <p> that isn't nav/footer boilerplate."""
    BOILERPLATE = re.compile(
        r"cookie|privacy|subscribe|copyright|newsletter|©|all rights reserved",
        re.I,
    )
    for p in soup.find_all("p"):
        text = p.get_text(" ", strip=True)
        if len(text) > MIN_PARAGRAPH_LENGTH and not BOILERPLATE.search(text):
            return str(text[:PARAGRAPH_EXCERPT_LENGTH])
    return ""


def get_article_metadata(url: str) -> dict[str, str]:
    """Fetch an article URL and return {title, description, image, date}."""
    try:
        soup = fetch(url)
    except Exception as e:
        log.warning("  Could not fetch %s: %s", url, e)
        return {}

    jsonld = extract_jsonld(soup)
    og = extract_og(soup)

    title_fallback = (
        soup.title.string.strip() if soup.title and soup.title.string else ""
    )
    title = jsonld.get("headline") or og.get("title") or title_fallback
    description = (
        jsonld.get("description") or og.get("description") or first_real_paragraph(soup)
    )
    raw_image = jsonld.get("image") or og.get("image") or ""
    if isinstance(raw_image, list):
        raw_image = raw_image[0] if raw_image else ""
    if isinstance(raw_image, dict):
        raw_image = raw_image.get("url", "")
    image = str(raw_image)
    date_raw = jsonld.get("datePublished") or og.get("date") or ""

    return {
        "title": (title or "").strip(),
        "description": (description or "").strip(),
        "image": (image or "").strip(),
        "date": date_raw.strip(),
    }


# ── Index scraping ─────────────────────────────────────────────────────────────

# Matches dates in various formats found near article links
DATE_RE = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:[Z+-]\S*)?"
    r"|\d{4}-\d{2}-\d{2}"
    r"|(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
    r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+\d{1,2},?\s+\d{4}"
    r"|\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May"
    r"|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+\d{4})\b"
)


def find_date_near(tag: Tag, radius: int = 5) -> str:
    """Walk up/sideways in the DOM looking for a date string."""
    node: Tag | None = tag
    for _ in range(radius):
        if node is None:
            break
        text = node.get_text(" ", strip=True)
        m = DATE_RE.search(text)
        if m:
            return m.group(0)
        node = node.parent
    return ""


MIN_SLUG_LENGTH = 5
MIN_LINK_TEXT_LENGTH = 10


def scrape_index(blog_url: str, max_items: int = 25) -> list[dict[str, str]]:
    """Scrape the blog index page.

    Returns list of {url, title, date_str} sorted newest-first.
    """
    parsed = urlparse(blog_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    blog_netloc = parsed.netloc
    blog_path = parsed.path.rstrip("/")

    log.info("Fetching index: %s", blog_url)
    try:
        soup = fetch(blog_url)
    except Exception as e:
        log.error("Failed to fetch index %s: %s", blog_url, e)
        return []

    articles: dict[str, dict[str, str]] = {}  # url -> info

    for a in soup.find_all("a", href=True):
        href = str(a["href"]).split("?")[0].split("#")[0]

        # Resolve relative URLs
        if href.startswith("http"):
            full_url = href
        elif href.startswith("/"):
            full_url = base + href
        else:
            full_url = urljoin(blog_url, href)

        # The index page is untrusted, remote content: an <a> tag on it
        # could point anywhere (a different host, a private/internal
        # address, a non-http scheme). Only ever follow links that stay on
        # the configured blog's own host and scheme.
        full_parsed = urlparse(full_url)
        if full_parsed.scheme not in ("http", "https"):
            continue
        if full_parsed.netloc != blog_netloc:
            continue

        # Must be under the same blog path and not be the index itself
        link_path = full_parsed.path.rstrip("/")
        if not link_path.startswith(blog_path + "/"):
            continue
        # Skip paths that are clearly category/tag/author pages (short suffixes)
        suffix = link_path[len(blog_path) :]
        if suffix.count("/") > 1:
            continue  # too many levels deep
        # Skip very short slugs that are likely categories
        slug = suffix.strip("/")
        if len(slug) < MIN_SLUG_LENGTH:
            continue

        if full_url in articles:
            continue

        # Try to get the title from the link text itself
        link_text = a.get_text(" ", strip=True)
        title = link_text if len(link_text) > MIN_LINK_TEXT_LENGTH else ""

        date_str = find_date_near(a)

        articles[full_url] = {
            "url": full_url,
            "title": title,
            "date_str": date_str,
        }

    def sort_key(item: dict[str, str]) -> datetime:
        dt = parse_date(item["date_str"])
        return dt or datetime.min.replace(tzinfo=UTC)

    sorted_articles = sorted(articles.values(), key=sort_key, reverse=True)
    return sorted_articles[:max_items]


# ── Feed building ──────────────────────────────────────────────────────────────


# Control characters that are not legal in XML 1.0 text content, per
# https://www.w3.org/TR/xml/#charsets. Remote content (titles/descriptions
# scraped from third-party pages) may contain these; strip them so a
# malformed source can't produce an invalid feed.
_XML_ILLEGAL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def xml_escape(s: str) -> str:
    """Escape special characters for embedding in XML text/attribute content."""
    cleaned = _XML_ILLEGAL_CHARS_RE.sub("", str(s))
    return (
        cleaned.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def build_rss(feed_name: str, blog_url: str, articles: list[dict[str, str]]) -> str:
    """Render a list of articles as an RSS 2.0 XML document."""
    now = formatdate(usegmt=True)

    items: list[str] = []
    for a in articles:
        title = xml_escape(a.get("title") or "Untitled")
        url = xml_escape(a["url"])
        desc = xml_escape(a.get("description") or title)
        img = a.get("image", "")
        dt = parse_date(a.get("date") or a.get("date_str") or "")
        pub = to_rfc822(dt)

        img_html = (
            f'&lt;img src="{xml_escape(img)}" style="max-width:100%;margin-bottom:1em"/&gt;&lt;br/&gt;'
            if img
            else ""
        )
        enclosure = ""
        if img:
            mime = mimetypes.guess_type(img)[0] or "image/jpeg"
            enclosure = (
                f'\n      <enclosure url="{xml_escape(img)}" type="{mime}" length="0"/>'
            )

        items.append(f"""    <item>
      <title>{title}</title>
      <link>{url}</link>
      <guid isPermaLink="true">{url}</guid>
      <pubDate>{pub}</pubDate>{enclosure}
      <description>{img_html}{desc}</description>
    </item>""")

    items_xml = "\n".join(items)
    feed_name_esc = xml_escape(feed_name)
    blog_url_esc = xml_escape(blog_url)

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel>
    <title>{feed_name_esc}</title>
    <link>{blog_url_esc}</link>
    <description>RSS feed for {feed_name_esc} generated by crap2rss</description>
    <language>en</language>
    <lastBuildDate>{now}</lastBuildDate>
    <atom:link href="{blog_url_esc}" rel="self" type="application/rss+xml"/>
{items_xml}
  </channel>
</rss>
"""


# ── Per-feed generation ────────────────────────────────────────────────────────


def generate_feed(
    cfg: dict[str, str],
    cache: dict[str, dict[str, dict[str, str]]],
    max_items: int = 20,
) -> str:
    """Generate RSS XML for one feed config entry.

    `cache` maps feed name -> {article url -> metadata}. Articles already
    present in the cache are reused as-is instead of being re-fetched, so
    that unchanged items don't appear to update on every run and so that
    we don't hammer the source site for pages we've already seen.
    """
    name = cfg["name"]
    url = cfg["url"]
    feed_cache = cache.setdefault(name, {})

    articles = scrape_index(url, max_items=max_items)
    if not articles:
        log.warning("[%s] No articles found on index page.", name)
        return build_rss(name, url, [])

    new_count = sum(1 for a in articles if a["url"] not in feed_cache)
    log.info(
        "[%s] Found %d articles (%d cached, %d new)",
        name,
        len(articles),
        len(articles) - new_count,
        new_count,
    )

    for i, a in enumerate(articles):
        cached = feed_cache.get(a["url"])
        if cached:
            a.update(cached)
            continue

        log.info("  [%d/%d] %s", i + 1, len(articles), a["url"].split("/")[-1])
        meta = get_article_metadata(a["url"])
        # Only overwrite if better data was found
        if meta.get("title") and len(meta["title"]) > len(a.get("title", "")):
            a["title"] = meta["title"]
        if meta.get("description"):
            a["description"] = meta["description"]
        if meta.get("image"):
            a["image"] = meta["image"]
        if meta.get("date"):
            a["date"] = meta["date"]
        time.sleep(DELAY)

        feed_cache[a["url"]] = {
            "title": a.get("title", ""),
            "description": a.get("description", ""),
            "image": a.get("image", ""),
            "date": a.get("date", ""),
        }

    # Drop cache entries for articles that fell off the index page.
    current_urls = {a["url"] for a in articles}
    for stale_url in list(feed_cache):
        if stale_url not in current_urls:
            del feed_cache[stale_url]

    return build_rss(name, url, articles)


# ── Config ─────────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = Path("crap2rss.yaml")

EXAMPLE_CONFIG = """\
# crap2rss configuration
# Run: python3 crap2rss.py

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
"""


def load_config(path: Path) -> dict[str, Any]:
    """Load the YAML config file, creating an example one if missing."""
    if not path.exists():
        log.error("Config file not found: %s", path)
        log.info("Creating example config at %s", path)
        path.write_text(EXAMPLE_CONFIG)
        log.info("Edit it and re-run.")
        sys.exit(1)
    with open(path) as f:
        return cast(dict[str, Any], yaml.safe_load(f))


# ── Metadata cache ─────────────────────────────────────────────────────────────

CACHE_FILENAME = ".crap2rss_cache.json"


def load_cache(path: Path) -> dict[str, dict[str, dict[str, str]]]:
    """Load the article metadata cache from disk, if present."""
    if not path.exists():
        return {}
    try:
        return cast(dict[str, dict[str, dict[str, str]]], json.loads(path.read_text()))
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Could not read cache file %s (%s), starting fresh", path, e)
        return {}


def save_cache(path: Path, cache: dict[str, dict[str, dict[str, str]]]) -> None:
    """Persist the article metadata cache to disk."""
    try:
        path.write_text(json.dumps(cache, indent=2))
    except OSError as e:
        log.warning("Could not write cache file %s: %s", path, e)


# ── CLI ────────────────────────────────────────────────────────────────────────


def main() -> None:
    """CLI entry point: parse args and generate configured feeds."""
    parser = argparse.ArgumentParser(
        description="Generate RSS feeds for blogs that don't have one.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        metavar="FILE",
        help="Config file (default: crap2rss.yaml)",
    )
    parser.add_argument(
        "--feed", metavar="NAME", help="Only generate this feed (partial name match)"
    )
    parser.add_argument(
        "--list", action="store_true", help="List configured feeds and exit"
    )
    parser.add_argument(
        "--init", action="store_true", help="Write example config and exit"
    )
    parser.add_argument(
        "--agent",
        choices=["honest", "firefox"],
        default="honest",
        help=(
            "User-Agent to send: 'honest' (default, identifies crap2rss so "
            "site operators can allowlist it) or 'firefox' (spoof a browser)"
        ),
    )
    args = parser.parse_args()

    if args.agent == "firefox":
        SESSION.headers["User-Agent"] = FIREFOX_USER_AGENT

    config_path = Path(args.config)

    if args.init:
        config_path.write_text(EXAMPLE_CONFIG)
        print(f"Example config written to {config_path}")
        return

    config = load_config(config_path)
    settings = config.get("settings", {})
    max_items = settings.get("max_items", 20)
    output_dir = Path(settings.get("output_dir", "."))

    feeds = config.get("feeds", [])
    if not feeds:
        log.error("No feeds defined in %s", config_path)
        sys.exit(1)

    # Filter by --feed
    if args.feed:
        needle = args.feed.lower()
        feeds = [
            f
            for f in feeds
            if needle in f["name"].lower() or needle in f["url"].lower()
        ]
        if not feeds:
            log.error("No feed matching '%s'", args.feed)
            sys.exit(1)

    if args.list:
        for f in feeds:
            out = output_dir / f.get(
                "output", re.sub(r"[^a-z0-9]+", "-", f["name"].lower()) + ".xml"
            )
            print(f"  {f['name']:<40}  {f['url']}")
            print(f"  {'':40}  -> {out}")
        return

    # Generate all (or filtered) feeds to disk
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_path = output_dir / CACHE_FILENAME
    cache = load_cache(cache_path)
    for feed_cfg in feeds:
        name = feed_cfg["name"]
        out_name = feed_cfg.get(
            "output",
            re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") + ".xml",
        )
        out_path = output_dir / out_name

        log.info("=== %s ===", name)
        xml = generate_feed(feed_cfg, cache, max_items=max_items)
        out_path.write_text(xml, encoding="utf-8")
        log.info("Written: %s", out_path)
    save_cache(cache_path, cache)


if __name__ == "__main__":
    main()
