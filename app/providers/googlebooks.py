import requests
from typing import Optional
from ..config import USER_AGENT, REQUEST_TIMEOUT
from .base import Provider, SearchResult, BookDetail

API = "https://www.googleapis.com/books/v1/volumes"

class GoogleBooksProvider(Provider):
    site = "googlebooks"
    headers = {"User-Agent": USER_AGENT}

    def search(self, query: str):
        params = {"q": query, "maxResults": 5, "printType": "books"}
        r = requests.get(API, params=params, headers=self.headers, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        out = []
        for item in (data.get("items") or []):
            vi = item.get("volumeInfo", {})
            title = vi.get("title") or ""
            authors = vi.get("authors") or []
            # ISBN
            isbn = None
            for ident in vi.get("industryIdentifiers", []):
                if ident.get("type") in ("ISBN_13", "ISBN_10"):
                    isbn = ident.get("identifier")
                    break
            out.append(SearchResult(
                title=title, authors=authors, url=item.get("selfLink") or "", isbn=isbn
            ))
        return out

    def get_by_isbn(self, isbn: str) -> Optional[BookDetail]:
        params = {"q": f"isbn:{isbn}", "maxResults": 1}
        r = requests.get(API, params=params, headers=self.headers, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return None
        data = r.json()
        items = data.get("items") or []
        if not items:
            return None
        return self._to_detail(items[0])

    def get_detail(self, url: str) -> Optional[BookDetail]:
        r = requests.get(url, headers=self.headers, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return None
        return self._to_detail(r.json())

    def _to_detail(self, item) -> Optional[BookDetail]:
        vi = item.get("volumeInfo", {})
        title = vi.get("title") or ""
        authors = vi.get("authors") or []
        publisher = vi.get("publisher")
        pub_year = None
        date = (vi.get("publishedDate") or "")[:4]
        if date.isdigit():
            pub_year = int(date)
        pages = vi.get("pageCount")
        summary = vi.get("description")
        language = vi.get("language")
        cover_url = None
        image_links = vi.get("imageLinks") or {}
        # 选一个较大的缩略图
        cover_url = image_links.get("thumbnail") or image_links.get("smallThumbnail")

        isbn = None
        for ident in vi.get("industryIdentifiers", []):
            if ident.get("type") in ("ISBN_13", "ISBN_10"):
                isbn = ident.get("identifier"); break

        return BookDetail(
            title=title, authors=authors, publisher=publisher, pub_year=pub_year,
            isbn=isbn, edition=None, pages=pages, summary=summary, author_bio=None,
            language=language, cover_url=cover_url, cip=None
        )
