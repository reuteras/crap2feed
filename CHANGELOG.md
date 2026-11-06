# Changelog

Notable changes to crap2feed, newest first. Each version is also published
as a GitHub release tagged `vX.Y.Z`.

The **Hall of shame** lists sites that used to publish a working RSS/Atom
feed, dropped it, and are the reason crap2feed needed a new scraping
strategy.

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
