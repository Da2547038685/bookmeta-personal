# app/providers/localjson.py
import json
from pathlib import Path
from typing import Optional
from rapidfuzz import fuzz
from ..config import DATA_DIR
from .base import Provider, SearchResult, BookDetail
from ..nlp import clean_line

# 离线 JSON 文件路径
CATALOG_PATH = (DATA_DIR / "offline_catalog.json").resolve()

class LocalJSONProvider(Provider):
    site = "localjson"

    def _load(self):
        print(f"[LocalJSON] Loading catalog from {CATALOG_PATH}")
        if not CATALOG_PATH.exists():
            print("[LocalJSON] Catalog file not found.")
            return []
        try:
            data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
            print(f"[LocalJSON] Loaded {len(data)} items.")
            return data
        except Exception as e:
            print("[LocalJSON] Failed to load JSON:", e)
            return []

    def _normalize(self, s: str) -> str:
        return clean_line((s or "").strip()).lower()

    def _best_match(self, query: str):
        items = self._load()
        if not items:
            return None
        qn = self._normalize(query)

        # 1) 先按标题精确匹配
        for it in items:
            if self._normalize(it.get("title", "")) == qn:
                return it

        # 2) 再模糊匹配（只用标题，不考虑作者）
        best = None
        best_score = -1
        for it in items:
            cand_title = it.get("title", "")
            s1 = fuzz.token_sort_ratio(query, cand_title)
            s2 = fuzz.partial_ratio(query, cand_title)
            score = max(s1, s2)
            if score > best_score:
                best, best_score = it, score
        return best if best_score >= 60 else None

    def search(self, query: str):
        hit = self._best_match(query)
        if not hit:
            return []
        return [SearchResult(
            title=hit.get("title", ""),
            authors=hit.get("authors", []),
            url=f"local://{hit.get('isbn') or hit.get('title')}",
            isbn=hit.get("isbn")
        )]

    def get_by_isbn(self, isbn: str) -> Optional[BookDetail]:
        items = self._load()
        for it in items:
            if it.get("isbn") and it["isbn"].replace("-", "") == isbn.replace("-", ""):
                return self._to_detail(it)
        return None

    def get_detail(self, url: str) -> Optional[BookDetail]:
        key = url.replace("local://", "")
        items = self._load()
        for it in items:
            if it.get("isbn") == key or it.get("title") == key:
                return self._to_detail(it)
        return None

    def _to_detail(self, it) -> Optional[BookDetail]:
        return BookDetail(
            title=it.get("title", ""),
            authors=it.get("authors", []),
            publisher=it.get("publisher"),
            pub_year=it.get("pub_year"),
            isbn=it.get("isbn"),
            edition=it.get("edition"),
            pages=it.get("pages"),
            summary=it.get("summary"),
            author_bio=it.get("author_bio"),
            language=it.get("language") or "中文",
            cover_url=it.get("cover_url"),
            cip=it.get("cip")
        )
