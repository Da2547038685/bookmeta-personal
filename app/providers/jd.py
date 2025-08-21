# app/providers/jd.py
import re, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from urllib.parse import quote
from typing import Optional, List

from ..config import USER_AGENT, REQUEST_TIMEOUT, REQUEST_TIMEOUT_FAST
from .base import Provider, SearchResult, BookDetail

def _mk_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://search.jd.com/",
    })
    retry = Retry(total=2, connect=1, read=1, backoff_factor=0.3,
                  status_forcelist=[429, 500, 502, 503, 504], raise_on_status=False)
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    return s

class JDProvider(Provider):
    site = "jd"

    def __init__(self):
        self.sess = _mk_session()

    def search(self, query: str) -> List[SearchResult]:
        url = f"https://search.jd.com/Search?keyword={quote(query)}"
        try:
            r = self.sess.get(url, timeout=REQUEST_TIMEOUT_FAST)
            if r.status_code != 200:
                return []
        except requests.RequestException:
            return []

        html = r.text
        m = re.search(r'//item\.jd\.com/(\d+)\.html', html)
        if not m:
            return []
        sku = m.group(1)
        detail_url = f"https://item.jd.com/{sku}.html"
        d = self.get_detail(detail_url)
        if not d:
            return []
        return [SearchResult(title=d.title or "", authors=d.authors or [], url=detail_url, isbn=d.isbn)]

    def get_by_isbn(self, isbn: str) -> Optional[BookDetail]:
        res = self.search(isbn)
        if not res:
            return None
        return self.get_detail(res[0].url)

    def get_detail(self, url: str) -> Optional[BookDetail]:
        try:
            r = self.sess.get(url, timeout=REQUEST_TIMEOUT)
            if r.status_code != 200:
                return None
        except requests.RequestException:
            return None

        soup = BeautifulSoup(r.text, "lxml")

        title = ""
        t = soup.select_one("div.sku-name")
        if t:
            title = t.get_text(" ", strip=True)
        if not title:
            pt = soup.find("title")
            if pt:
                title = pt.get_text(strip=True)

        # 参数区：不同模板位置不同，合并尝试
        param_texts = []
        for sel in ["#detail .p-parameter", "#parameter2", "#detail .ssd-module-wrap", "#specifications"]:
            block = soup.select_one(sel)
            if block:
                param_texts.append(block.get_text("\n", strip=True))
        param_blob = "\n".join(param_texts)

        def find1(pat: str):
            m = re.search(pat, param_blob, flags=re.I)
            return m.group(1).strip() if m else None

        isbn = find1(r"ISBN[:：]?\s*([0-9Xx\-]{10,})")
        if isbn:
            isbn = isbn.replace("-", "").upper()
        publisher = find1(r"出版社[:：]?\s*([^\s/|]+)")
        year = find1(r"(出版时间|出版年)[:：]?\s*((?:19|20)\d{2})")
        pub_year = int(year) if year and year.isdigit() else None
        pages_s = find1(r"(页数|页码)[:：]?\s*(\d+)")
        pages = int(pages_s) if pages_s and pages_s.isdigit() else None

        return BookDetail(
            title=title or "",
            authors=[],  # JD 页面作者结构不稳定，留空更稳
            publisher=publisher,
            pub_year=pub_year,
            isbn=isbn,
            edition=None,
            pages=pages,
            summary=None,
            author_bio=None,
            language="中文",
            cover_url=None,
        )
