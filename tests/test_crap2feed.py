"""Basic tests for the pure-logic parts of crap2feed.py.

Covers date parsing/formatting, XML escaping, __NEXT_DATA__ scoring, and
anchor/Atom-feed generation. Network-touching functions (fetch, get_article_metadata)
are out of scope here since they'd need mocked HTTP.
"""

from datetime import UTC, datetime

from bs4 import BeautifulSoup

from crap2feed import (
    build_atom,
    find_nextdata_post_lists,
    nextdata_item_to_article,
    output_filename,
    parse_date,
    public_blog_index_items_to_articles,
    score_nextdata_post_list,
    scrape_index_anchors,
    to_rfc3339,
    xml_escape,
)

NOW_TOLERANCE_SECONDS = 5
EXPECTED_POST_COUNT = 2


class TestParseDate:
    """Tests for parse_date()."""

    def test_empty_string_returns_none(self) -> None:
        """An empty string has no date to parse."""
        assert parse_date("") is None

    def test_unrecognized_format_returns_none(self) -> None:
        """A string matching none of DATE_FORMATS is rejected."""
        assert parse_date("not a date") is None

    def test_iso8601_with_z_suffix(self) -> None:
        """A trailing Z is treated as UTC."""
        dt = parse_date("2026-07-20T12:00:00Z")
        assert dt == datetime(2026, 7, 20, 12, 0, 0, tzinfo=UTC)

    def test_iso8601_with_offset(self) -> None:
        """A +00:00 offset is normalized before parsing."""
        dt = parse_date("2026-07-20T12:00:00+00:00")
        assert dt == datetime(2026, 7, 20, 12, 0, 0, tzinfo=UTC)

    def test_date_only(self) -> None:
        """A bare YYYY-MM-DD date defaults to midnight UTC."""
        dt = parse_date("2026-07-20")
        assert dt == datetime(2026, 7, 20, 0, 0, 0, tzinfo=UTC)

    def test_long_month_name(self) -> None:
        """'July 20, 2026' matches the '%B %d, %Y' format."""
        dt = parse_date("July 20, 2026")
        assert dt == datetime(2026, 7, 20, 0, 0, 0, tzinfo=UTC)

    def test_month_and_year_only(self) -> None:
        """'July 2026' matches the '%B %Y' format, defaulting to the 1st."""
        dt = parse_date("July 2026")
        assert dt == datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)


class TestToRfc3339:
    """Tests for to_rfc3339()."""

    def test_none_defaults_to_now(self) -> None:
        """A None datetime is formatted as roughly the current time."""
        result = to_rfc3339(None)
        assert result.endswith("Z")
        parsed = datetime.fromisoformat(result.replace("Z", "+00:00"))
        assert abs((datetime.now(UTC) - parsed).total_seconds()) < NOW_TOLERANCE_SECONDS

    def test_utc_datetime_uses_z_suffix(self) -> None:
        """A UTC datetime is rendered with a Z suffix, not +00:00."""
        dt = datetime(2026, 7, 20, 12, 0, 0, tzinfo=UTC)
        assert to_rfc3339(dt) == "2026-07-20T12:00:00Z"


class TestXmlEscape:
    """Tests for xml_escape()."""

    def test_escapes_special_characters(self) -> None:
        """The five XML-significant characters are all escaped."""
        assert (
            xml_escape("<a> & \"b\" 'c'")
            == "&lt;a&gt; &amp; &quot;b&quot; &apos;c&apos;"
        )

    def test_strips_illegal_control_characters(self) -> None:
        """XML 1.0-illegal control characters are stripped, not escaped."""
        assert xml_escape("hello\x00\x1fworld") == "helloworld"

    def test_leaves_plain_text_untouched(self) -> None:
        """Ordinary text passes through unchanged."""
        assert xml_escape("plain text") == "plain text"


class TestOutputFilename:
    """Tests for output_filename()."""

    def test_explicit_output_is_respected(self) -> None:
        """An explicitly configured output filename wins over derivation."""
        assert (
            output_filename({"name": "My Blog", "output": "custom.xml"}) == "custom.xml"
        )

    def test_derives_slug_from_name(self) -> None:
        """Without an explicit output, the filename is slugified from the name."""
        assert (
            output_filename({"name": "Pillar Security Blog"})
            == "pillar-security-blog.xml"
        )

    def test_derivation_strips_non_alphanumeric(self) -> None:
        """Punctuation collapses into single hyphens, trimmed at the edges."""
        assert output_filename({"name": "  A & B!! "}) == "a-b.xml"


class TestNextdataPostLists:
    """Tests for find_nextdata_post_lists() and score_nextdata_post_list()."""

    def test_finds_list_with_title_and_link_keys(self) -> None:
        """A list of dicts with a title-like and link-like key is a candidate."""
        data = {
            "props": {
                "posts": [
                    {"title": "First", "slug": "first"},
                    {"title": "Second", "slug": "second"},
                ]
            }
        }
        candidates = find_nextdata_post_lists(data)
        assert len(candidates) == 1
        assert len(candidates[0]) == EXPECTED_POST_COUNT

    def test_ignores_list_without_link_key(self) -> None:
        """A list missing a link-like key is not treated as a post list."""
        data = {"tags": [{"title": "News"}, {"title": "Security"}]}
        assert find_nextdata_post_lists(data) == []

    def test_ignores_empty_or_non_dict_lists(self) -> None:
        """Empty lists and lists of non-dicts are skipped."""
        assert find_nextdata_post_lists({"a": [], "b": [1, 2, 3]}) == []

    def test_score_prefers_list_with_date_and_description(self) -> None:
        """A shorter list with date/description keys can outscore a longer one without."""
        plain = [
            {"title": "A", "slug": "a"},
            {"title": "B", "slug": "b"},
            {"title": "C", "slug": "c"},
        ]
        rich = [{"title": "A", "slug": "a", "date": "2026-01-01", "excerpt": "..."}]
        assert score_nextdata_post_list(rich) > score_nextdata_post_list(plain)


class TestNextdataItemToArticle:
    """Tests for nextdata_item_to_article()."""

    def test_builds_article_from_relative_link(self) -> None:
        """A relative slug is resolved against the blog URL."""
        item = {"title": "Hello World", "slug": "hello-world", "date": "2026-01-01"}
        article = nextdata_item_to_article(
            item, "https://example.com/blog", "example.com"
        )
        assert article == {
            "url": "https://example.com/blog/hello-world",
            "title": "Hello World",
            "date_str": "2026-01-01",
        }

    def test_rejects_off_host_link(self) -> None:
        """A link resolving to a different host than the blog is refused."""
        item = {"title": "Hello", "url": "https://evil.example/x"}
        assert (
            nextdata_item_to_article(item, "https://example.com/blog", "example.com")
            is None
        )

    def test_missing_title_or_link_returns_none(self) -> None:
        """An item without both a title and a link key is not a valid article."""
        assert (
            nextdata_item_to_article(
                {"title": "Only Title"}, "https://example.com", "example.com"
            )
            is None
        )
        assert (
            nextdata_item_to_article(
                {"slug": "only-slug"}, "https://example.com", "example.com"
            )
            is None
        )


class TestScrapeIndexAnchors:
    """Tests for scrape_index_anchors()."""

    def test_finds_article_links_under_blog_path(self) -> None:
        """Links under the blog's own path, with a long-enough slug, are collected."""
        html = """
        <html><body>
          <a href="/blog/a-real-article-slug">A real article slug and title</a>
          <a href="/blog/tag/">Tag</a>
          <a href="https://other.example/blog/x-article-slug">Off host</a>
          <a href="/about">About</a>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        articles = scrape_index_anchors("https://example.com/blog", soup)
        assert list(articles) == ["https://example.com/blog/a-real-article-slug"]
        assert articles["https://example.com/blog/a-real-article-slug"]["title"] == (
            "A real article slug and title"
        )

    def test_skips_short_slugs(self) -> None:
        """Slugs shorter than MIN_SLUG_LENGTH are assumed to be category pages."""
        html = '<html><body><a href="/blog/ab">ab</a></body></html>'
        soup = BeautifulSoup(html, "html.parser")
        assert scrape_index_anchors("https://example.com/blog", soup) == {}

    def test_skips_deeply_nested_paths(self) -> None:
        """Links more than one path segment below the blog path are skipped."""
        html = '<html><body><a href="/blog/2026/01/some-article">Some article</a></body></html>'
        soup = BeautifulSoup(html, "html.parser")
        assert scrape_index_anchors("https://example.com/blog", soup) == {}


class TestPublicBlogIndexItemsToArticles:
    """Tests for conventional public blog-index conversion."""

    def test_keeps_only_black_lotus_articles(self) -> None:
        """Only complete entries bearing Lumen's Black Lotus category are kept."""
        data = [
            {
                "title": "A botnet report",
                "description": "Research summary",
                "url": "/en-us/a-botnet-report",
                "blogPublishedDate": "July 24, 2026",
                "categories": ["blog-and-news:categories/black-lotus-lab"],
            },
            {
                "title": "Other Lumen post",
                "url": "/en-us/other-post",
                "categories": ["blog-and-news:categories/topics/cloud-computing"],
            },
        ]
        assert public_blog_index_items_to_articles(
            "https://www.lumen.com/blog-and-news/en-us/black-lotus-labs", data
        ) == [
            {
                "url": "https://www.lumen.com/blog/en-us/a-botnet-report",
                "title": "A botnet report",
                "date_str": "July 24, 2026",
                "description": "Research summary",
            }
        ]

    def test_rejects_invalid_payload_and_paths(self) -> None:
        """Unexpected JSON shapes and non-blog paths do not become fetch targets."""
        url = "https://www.lumen.com/blog-and-news/en-us/black-lotus-labs"
        assert public_blog_index_items_to_articles(url, {}) == []
        assert (
            public_blog_index_items_to_articles(
                url,
                [
                    {
                        "title": "Off-site",
                        "url": "https://evil.example/post",
                        "categories": ["blog-and-news:categories/black-lotus-lab"],
                    }
                ],
            )
            == []
        )

    def test_uses_all_articles_when_page_has_no_matching_category(self) -> None:
        """A general blog page can consume an unfiltered index."""
        data = [
            {
                "title": "A post",
                "url": "/blog/a-post",
                "blogPublishedDate": "August 24, 2026",
            }
        ]
        assert public_blog_index_items_to_articles(
            "https://example.com/blog", data
        ) == [
            {
                "url": "https://example.com/blog/a-post",
                "title": "A post",
                "date_str": "August 24, 2026",
            }
        ]


class TestBuildAtom:
    """Tests for build_atom()."""

    def test_produces_well_formed_entries(self) -> None:
        """Each article becomes an <entry> with escaped title/link/content."""
        articles = [
            {
                "url": "https://example.com/blog/a",
                "title": "Hello & <World>",
                "description": "A description",
                "date": "2026-07-20",
            }
        ]
        xml = build_atom("My Feed", "https://example.com/blog", articles)
        assert "<title>My Feed</title>" in xml
        assert "Hello &amp; &lt;World&gt;" in xml
        assert '<link href="https://example.com/blog/a"/>' in xml
        assert "<updated>2026-07-20T00:00:00Z</updated>" in xml

    def test_empty_article_list_still_produces_valid_feed_shell(self) -> None:
        """A feed with no articles is still a well-formed (empty) Atom document."""
        xml = build_atom("Empty Feed", "https://example.com/blog", [])
        assert '<feed xmlns="http://www.w3.org/2005/Atom">' in xml
        assert "<entry>" not in xml

    def test_missing_title_falls_back_to_untitled(self) -> None:
        """An article with no title renders as 'Untitled' rather than empty."""
        xml = build_atom(
            "Feed", "https://example.com", [{"url": "https://example.com/a"}]
        )
        assert "<title>Untitled</title>" in xml
