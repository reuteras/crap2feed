# Changelog

<!-- markdownlint-configure-file {"MD024": {"siblings_only": true}} -->

Notable changes to crap2feed, newest first. Each version is also published
as a GitHub release tagged `vX.Y.Z`.

The **Hall of shame** lists sites that used to publish a working RSS/Atom
feed, dropped it, and are the reason crap2feed needed a new scraping
strategy.

## 0.4.1 — 2026-11-26

### Fixed

- When a page crap2feed expected to be HTML turns out to be an XML
  document, it now logs a warning naming the feed, the URL and the XML
  root element. Before, it printed only bs4's generic
  `XMLParsedAsHTMLWarning`, which named a line in `crap2feed.py` and not
  the site. If the root element is `<rss>`, `<feed>` or `<rdf:RDF>`, the
  warning adds that the site may publish a feed again.

## 0.4.0 — 2026-11-19

### Added

- New `article_cards` index strategy for blogs whose posts live at the site
  root instead of under the index's own path, like `/<slug>/` next to a
  `/blog/` index. It takes the heading link (`<h2><a href>`) of each
  `<article>` element on the index page and ignores the category/tag chips
  inside the card. The date comes from the card's `<time datetime>`. It is
  tried after `nextdata` and before `anchors_relaxed`. Before this change,
  `anchors_relaxed` picked the `/tag/` links on such pages instead of the
  posts. Existing feeds keep the strategy remembered in their cache.
- ntop (`https://www.ntop.org/blog/`) added to `examples/my-crap2feed.yaml`.

### Hall of shame

- **ntop** — `https://www.ntop.org/blog/`. The blog used to have its
  feed at the standard `https://www.ntop.org/feed/`. The Wayback Machine
  recorded it answering 200 as late as 2026-10-08. After a site relaunch,
  `/feed/` returns 404, and so do `/blog/feed/`, `/rss.xml`, `/feed.xml`
  and `/index.xml`. No `<link rel="alternate">` for RSS/Atom is left on the
  page. The new site does find room to advertise a Markdown copy of the
  blog index for LLMs (`/blog/index.html.md`, plus `/llms.txt`), but nothing
  for feed readers. Noticed 2026-11-19.

## 0.3.0 — 2026-11-06

### Added

- New `eds_sheet` index strategy for sites on Adobe Experience Manager Edge
  Delivery Services. These sites ship an empty page shell and load their
  post list client-side from a same-host JSON "sheet" index
  (`/<section>-index.json` or `/query-index.json`). crap2feed now reads that
  index directly. Like `public_json`, the strategy is remembered per feed,
  so later runs fetch only the JSON and skip the HTML page.
- Dates for these posts come from the index's `publishedDate`. The article
  pages' `published-time` meta tag is the last republish time, not when the
  post was actually published.
- Infoblox (`https://www.infoblox.com/blog`) added to
  `examples/my-crap2feed.yaml`.

### Hall of shame

- **Infoblox** — `https://www.infoblox.com/blog`. It used to run on
  WordPress with a normal RSS feed at `/blog/feed/` (old
  `blogs.infoblox.com/feed/` links still redirect there). After moving to
  Edge Delivery Services, `/blog/feed` returns 404. The leftover WordPress
  `/feed/` still returns valid RSS but has no items, so feed readers see a
  feed that looks fine and never updates. The 1,880 posts are now only in
  `/blog-index.json`. Noticed 2026-11-06.
