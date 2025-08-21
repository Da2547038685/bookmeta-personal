import requests
from typing import Optional
from ..config import USER_AGENT, REQUEST_TIMEOUT
from .base import Provider, SearchResult, BookDetail

BASE = "https://openlibrary.org"

class OpenLibraryProvider(Provider):
    site = "openlibrary"
    headers = {"User-Agent": USER_AGENT}

    def search(self, query: str):
        r = requests.get(f"{BASE}/search.json", params={"title": query}, headers=self.headers, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        out = []
        for d in data.get("docs", [])[:5]:
            out.append(SearchResult(
                title=d.get("title") or "",
                authors=d.get("author_name") or [],
                url=f"{BASE}{d.get('key')}",
                isbn=(d.get("isbn") or [None])[0]
            ))
        return out

    def get_by_isbn(self, isbn: str) -> Optional[BookDetail]:
        r = requests.get(f"{BASE}/isbn/{isbn}.json", headers=self.headers, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return None
        d = r.json()
        title = d.get("title", "")
        pages = d.get("number_of_pages")
        # Cover
        cover_url = None
        if d.get("covers"):
            cover_url = f"https://covers.openlibrary.org/b/id/{d['covers'][0]}-L.jpg"
        # Note: publisher/year may be in 'publishers' and 'publish_date'
        pub = (d.get("publishers") or [None])[0]
        year = None
        if isinstance(d.get("publish_date"), str):
            import re
            m = re.search(r"(19|20)\d{2}", d["publish_date"])
            if m: year = int(m.group(0))
        return BookDetail(title=title, authors=[], publisher=pub, pub_year=year, isbn=isbn,
                          edition=None, pages=pages, summary=None, author_bio=None,
                          language=None, cover_url=cover_url, cip=None)

    def get_detail(self, url: str) -> Optional[BookDetail]:
        return None
