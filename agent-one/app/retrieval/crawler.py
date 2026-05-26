from __future__ import annotations

import logging
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.retrieval.pipeline import WebsiteDocument

logger = logging.getLogger(__name__)


class WebCrawler:
    def __init__(
        self,
        start_url: str,
        *,
        max_pages: int = 10,
        allowed_domain: str | None = None,
        timeout: float = 10.0,
        website_id: str = "demo-site",
    ) -> None:
        self.start_url = start_url
        self.max_pages = max_pages
        self.timeout = timeout
        self.website_id = website_id
        parsed = urlparse(start_url)
        self.allowed_domain = allowed_domain or parsed.netloc

    def crawl(self) -> list[WebsiteDocument]:
        visited: set[str] = set()
        queue: list[str] = [self.start_url]
        documents: list[WebsiteDocument] = []

        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            while queue and len(visited) < self.max_pages:
                url = queue.pop(0)
                if url in visited:
                    continue
                visited.add(url)

                try:
                    response = client.get(url)
                    if response.status_code != 200:
                        continue
                    if "text/html" not in response.headers.get("content-type", ""):
                        continue

                    html = response.text
                    title, text = self._extract_text(html)
                    if text.strip():
                        documents.append(
                            WebsiteDocument(
                                url=url,
                                title=title or url,
                                content=text,
                                website_id=self.website_id,
                            )
                        )

                    for link in self._extract_links(html, url):
                        if link not in visited:
                            queue.append(link)

                except Exception as exc:
                    logger.debug("Skipping %s: %s", url, exc)

        return documents

    def _extract_text(self, html: str) -> tuple[str, str]:
        soup = BeautifulSoup(html, "html.parser")
        title = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        for tag in soup(["script", "style", "nav", "footer", "header", "meta", "link"]):
            tag.decompose()
        text = " ".join(soup.get_text(" ", strip=True).split())
        return title, text

    def _extract_links(self, html: str, base_url: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        seen: set[str] = set()
        links: list[str] = []
        for a in soup.find_all("a", href=True):
            href = urljoin(base_url, a["href"])
            parsed = urlparse(href)
            if parsed.scheme not in ("http", "https"):
                continue
            if parsed.netloc != self.allowed_domain:
                continue
            clean = parsed._replace(fragment="").geturl()
            if clean not in seen:
                seen.add(clean)
                links.append(clean)
        return links
