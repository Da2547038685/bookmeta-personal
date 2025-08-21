# app/providers/douban.py
import re, random, json
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from urllib.parse import quote
from typing import Optional, List

from ..config import USER_AGENT, REQUEST_TIMEOUT, REQUEST_TIMEOUT_FAST
from .base import Provider, SearchResult, BookDetail

BASE = "https://book.douban.com"

def _mk_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": BASE + "/",
        # 随机 bid，豆瓣更容易给 200
        "Cookie": f"bid={''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=11))};"
    })
    retry = Retry(total=2, connect=1, read=1, backoff_factor=0.3,
                  status_forcelist=[429, 500, 502, 503, 504], raise_on_status=False)
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    return s

class DoubanProvider(Provider):
    site = "douban"

    def __init__(self):
        self.sess = _mk_session()

    # --- 新：优先使用 JSON 建议接口 ---
    def _suggest(self, query: str) -> List[SearchResult]:
        url = f"{BASE}/j/subject_suggest?q={quote(query)}"
        try:
            r = self.sess.get(url, timeout=REQUEST_TIMEOUT_FAST)
            if r.status_code != 200:
                return []
            arr = r.json()
        except Exception:
            return []
        out: List[SearchResult] = []
        for it in arr:
            # 只要“图书”
            if it.get("type") != "b":
                continue
            sid = it.get("id")
            title = (it.get("title") or "").strip()
            alt = (it.get("sub_title") or "").strip()
            author = (it.get("author") or "").strip()
            authors = [a.strip() for a in re.split(r"[、,，/;；]", author) if a.strip()] if author else []
            if sid and title:
                url = f"{BASE}/subject/{sid}/"
                out.append(SearchResult(title=title or alt, authors=authors, url=url, isbn=None))
            if len(out) >= 5:
                break
        return out

    def _search_html(self, query: str) -> List[SearchResult]:
        url = f"{BASE}/subject_search?search_text={quote(query)}&cat=1001"
        try:
            r = self.sess.get(url, timeout=REQUEST_TIMEOUT_FAST)
            if r.status_code != 200:
                return []
        except requests.RequestException:
            return []
        html = r.text
        subject_urls = re.findall(r"https://book\.douban\.com/subject/\d+/", html)
        out, seen = [], set()
        for su in subject_urls:
            if su in seen: 
                continue
            seen.add(su)
            d = self.get_detail(su)
            if d:
                out.append(SearchResult(title=d.title or "", authors=d.authors or [], url=su, isbn=d.isbn))
            if len(out) >= 5:
                break
        return out

    def search(self, query: str) -> List[SearchResult]:
        # 1) 建议接口（JSON，更稳）
        res = self._suggest(query)
        if res:
            return res
        # 2) 兜底：HTML 搜索页
        return self._search_html(query)

    def get_by_isbn(self, isbn: str) -> Optional[BookDetail]:
        url = f"{BASE}/isbn/{isbn}/"
        try:
            r = self.sess.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            if r.status_code != 200:
                return None
        except requests.RequestException:
            return None

        # 最终落到 subject 页
        final_url = r.url if "/subject/" in r.url else None
        if not final_url:
            s = self.search(isbn)
            if not s:
                return None
            final_url = s[0].url

        d = self.get_detail(final_url)
        if d and not d.isbn:
            d.isbn = isbn
        return d

    def get_detail(self, url: str) -> Optional[BookDetail]:
        try:
            r = self.sess.get(url, timeout=REQUEST_TIMEOUT)
            if r.status_code != 200:
                return None
        except requests.RequestException:
            return None

        soup = BeautifulSoup(r.text, "lxml")

        # 标题
        title = ""
        h1 = soup.select_one("h1 span")
        if h1:
            title = h1.get_text(strip=True)
        if not title:
            tt = soup.find("title")
            if tt:
                title = re.sub(r"\s*\(豆瓣.*?\)\s*$", "", tt.get_text(strip=True))

        # 书目信息块
        info = soup.select_one("#info")
        publisher = pub_year = pages = isbn = None
        authors: List[str] = []
        cip = None

        if info:
            text = info.get_text("\n", strip=True)

            m = re.search(r"作者[:：]\s*(.+?)(?:\n|$)", text)
            if m:
                line = re.sub(r"\s+", " ", m.group(1))
                for a in re.split(r"[、,，/;；]| +", line):
                    a = a.strip()
                    if a:
                        authors.append(a)

            m = re.search(r"出版社[:：]\s*(.+?)(?:\n|$)", text)
            if m:
                publisher = m.group(1).strip()

            m = re.search(r"出版年[:：]\s*(.+?)(?:\n|$)", text)
            if m:
                ym = re.search(r"(19|20)\d{2}", m.group(1))
                if ym:
                    pub_year = int(ym.group(0))

            m = re.search(r"页数[:：]\s*(\d+)", text)
            if m:
                pages = int(m.group(1))

            m = re.search(r"ISBN[:：]\s*([0-9Xx\-]+)", text)
            if m:
                isbn = m.group(1).replace("-", "").upper()

            # 有些页面会标出 CIP 或“中图法分类号”
            m = re.search(r"(?:CIP|中图法分类号)[:：]?\s*([A-Z][A-Z0-9\.\-]+)", text, flags=re.I)
            if m:
                cip = m.group(1).upper()

        # 简介
        summary = None
        intro = soup.select_one("#link-report .intro") or soup.select_one(".related_info .intro")
        if intro:
            summary = intro.get_text("\n", strip=True)

        # 封面
        cover_url = None
        mainpic = soup.select_one("#mainpic img")
        if mainpic and mainpic.get("src"):
            cover_url = mainpic["src"]

        d = BookDetail(
            title=title or "",
            authors=authors,
            publisher=publisher,
            pub_year=pub_year,
            isbn=isbn,
            edition=None,
            pages=pages,
            summary=summary,
            author_bio=None,
            language="中文",
            cover_url=cover_url,
            cip=cip,  # 可为空
        )
        setattr(d, "url", url)
        return d
