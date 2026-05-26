"""Tests for WebCrawler: text extraction, link filtering, HTTP mocking."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Unit tests — no network calls
# ---------------------------------------------------------------------------

def _make_crawler(url="https://example.com", max_pages=5):
    from app.retrieval.crawler import WebCrawler
    return WebCrawler(url, max_pages=max_pages)


def test_extract_text_returns_title_and_body():
    crawler = _make_crawler()
    html = (
        "<html><head><title>Test Page</title></head>"
        "<body><nav>Nav</nav><h1>Hello</h1><p>World content here.</p>"
        "<footer>Footer</footer></body></html>"
    )
    title, text = crawler._extract_text(html)
    assert title == "Test Page"
    assert "Hello" in text
    assert "World content here" in text
    # nav/footer tags should be stripped
    assert "Nav" not in text
    assert "Footer" not in text


def test_extract_text_empty_html():
    crawler = _make_crawler()
    _, text = crawler._extract_text("<html><body></body></html>")
    assert text == ""


def test_extract_links_keeps_same_domain():
    crawler = _make_crawler("https://example.com")
    html = """
    <html><body>
      <a href="/about">About</a>
      <a href="https://example.com/services">Services</a>
      <a href="https://other.com/page">External</a>
      <a href="mailto:x@example.com">Email</a>
    </body></html>
    """
    links = crawler._extract_links(html, "https://example.com")
    assert "https://example.com/about" in links
    assert "https://example.com/services" in links
    assert not any("other.com" in l for l in links)
    assert not any("mailto" in l for l in links)


def test_extract_links_strips_fragments():
    crawler = _make_crawler("https://example.com")
    html = '<html><body><a href="/page#section">Link</a></body></html>'
    links = crawler._extract_links(html, "https://example.com")
    assert links == ["https://example.com/page"]


def test_extract_links_no_duplicates():
    crawler = _make_crawler("https://example.com")
    html = """<html><body>
      <a href="/page">Link 1</a>
      <a href="/page">Link 2</a>
    </body></html>"""
    links = crawler._extract_links(html, "https://example.com")
    assert links.count("https://example.com/page") == 1


def test_allowed_domain_derived_from_start_url():
    from app.retrieval.crawler import WebCrawler
    crawler = WebCrawler("https://docs.mysite.com/intro")
    assert crawler.allowed_domain == "docs.mysite.com"


# ---------------------------------------------------------------------------
# Integration-style test — mocked HTTP
# ---------------------------------------------------------------------------

def _mock_response(html: str, status: int = 200, content_type: str = "text/html; charset=utf-8"):
    resp = MagicMock()
    resp.status_code = status
    resp.headers = {"content-type": content_type}
    resp.text = html
    return resp


def test_crawl_returns_documents_for_mocked_site():
    from app.retrieval.crawler import WebCrawler

    home_html = """
    <html><head><title>Home</title></head>
    <body><p>Welcome to the site.</p>
    <a href="https://example.com/about">About</a>
    </body></html>
    """
    about_html = """
    <html><head><title>About</title></head>
    <body><p>We are a consulting firm.</p></body></html>
    """

    responses = {
        "https://example.com": _mock_response(home_html),
        "https://example.com/about": _mock_response(about_html),
    }

    crawler = WebCrawler("https://example.com", max_pages=5)

    mock_client = MagicMock()
    mock_client.__enter__ = lambda s: s
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.side_effect = lambda url, **kw: responses.get(url, _mock_response("", 404))

    with patch("app.retrieval.crawler.httpx.Client", return_value=mock_client):
        docs = crawler.crawl()

    assert len(docs) == 2
    titles = {d.title for d in docs}
    assert "Home" in titles
    assert "About" in titles
    assert all(d.website_id == "demo-site" for d in docs)


def test_crawl_skips_non_html_responses():
    from app.retrieval.crawler import WebCrawler

    home_html = '<html><head><title>Home</title></head><body><p>Text.</p><a href="https://example.com/file.pdf">PDF</a></body></html>'

    responses = {
        "https://example.com": _mock_response(home_html),
        "https://example.com/file.pdf": _mock_response("binary", content_type="application/pdf"),
    }

    crawler = WebCrawler("https://example.com", max_pages=5)
    mock_client = MagicMock()
    mock_client.__enter__ = lambda s: s
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.side_effect = lambda url, **kw: responses.get(url, _mock_response("", 404))

    with patch("app.retrieval.crawler.httpx.Client", return_value=mock_client):
        docs = crawler.crawl()

    assert len(docs) == 1
    assert docs[0].title == "Home"


def test_crawl_respects_max_pages():
    from app.retrieval.crawler import WebCrawler

    def _make_page(n, links=()):
        link_tags = "".join(f'<a href="https://example.com/p{i}">P{i}</a>' for i in links)
        return _mock_response(f"<html><head><title>P{n}</title></head><body><p>Content {n}.</p>{link_tags}</body></html>")

    responses = {f"https://example.com/p{i}": _make_page(i) for i in range(20)}
    responses["https://example.com"] = _make_page(0, links=range(1, 20))

    crawler = WebCrawler("https://example.com", max_pages=3)
    mock_client = MagicMock()
    mock_client.__enter__ = lambda s: s
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.side_effect = lambda url, **kw: responses.get(url, _mock_response("", 404))

    with patch("app.retrieval.crawler.httpx.Client", return_value=mock_client):
        docs = crawler.crawl()

    assert len(docs) <= 3


def test_crawl_tolerates_http_errors():
    from app.retrieval.crawler import WebCrawler

    home_html = '<html><head><title>Home</title></head><body><p>OK</p><a href="https://example.com/bad">Bad</a></body></html>'

    def _side_effect(url, **kw):
        if "bad" in url:
            raise Exception("connection refused")
        return _mock_response(home_html)

    crawler = WebCrawler("https://example.com", max_pages=5)
    mock_client = MagicMock()
    mock_client.__enter__ = lambda s: s
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get.side_effect = _side_effect

    with patch("app.retrieval.crawler.httpx.Client", return_value=mock_client):
        docs = crawler.crawl()

    assert len(docs) == 1
