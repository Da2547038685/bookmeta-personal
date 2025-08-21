# app/pipeline.py
import json
import requests
from time import perf_counter
from typing import Optional
from slugify import slugify
from sqlalchemy.exc import IntegrityError
from pathlib import Path

from .db import SessionLocal, init_db, Book, Source
from .nlp import split_title_author
from .utils import find_isbn
from .config import COVERS_DIR, PROVIDERS, USER_AGENT, REQUEST_TIMEOUT
from .classify import classify_clc


# ---------- Provider 装载 ----------
def get_providers():
    """
    从 app/providers 子包按 config.PROVIDERS 顺序装载。
    """
    prov_map = {}
    try:
        from .providers.douban import DoubanProvider
        prov_map["douban"] = DoubanProvider
    except Exception as e:
        print("[prov] douban load failed:", e)

    try:
        from .providers.jd import JDProvider
        prov_map["jd"] = JDProvider
    except Exception as e:
        print("[prov] jd load failed:", e)

    loaded = [prov_map[name]() for name in PROVIDERS if name in prov_map]
    print("[pipeline] providers:", [p.__class__.__name__ for p in loaded])
    return loaded


# ---------- 封面抓取（返回“相对路径”） ----------
def fetch_cover(url: Optional[str]) -> str:
    """
    下载封面到 data/covers 下，返回相对路径 'covers/<file>.jpg'。
    若失败返回空字符串。
    """
    if not url:
        return ""
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        # 文件名尽量稳定，控制长度
        fname = slugify(url)[:80] + ".jpg"
        abs_path = COVERS_DIR / fname
        abs_path.write_bytes(r.content)
        # ★ 关键：返回相对路径
        return f"covers/{fname}"
    except Exception as e:
        print("[cover] fetch failed:", e)
        return ""


# ---------- 写入/更新 ----------
def _get_or_create_book_by_detail(d, session: SessionLocal) -> Book:
    """
    有 ISBN 按 ISBN 定位并更新；无 ISBN 新建，避免按标题误合并。
    """
    isbn = (d.isbn or "").strip() or None
    if isbn:
        b = session.query(Book).filter(Book.isbn == isbn).first()
        if not b:
            b = Book(isbn=isbn, title_std=d.title or "", authors_std=",".join(d.authors or []))
            session.add(b)
            session.flush()
        # 标题覆盖、其他“有值才覆盖”
        if (d.title or "").strip():
            b.title_std = d.title.strip()
        if d.authors:
            b.authors_std = ",".join(d.authors)
        if d.publisher:
            b.publisher = d.publisher
        if d.pub_year:
            b.pub_year = d.pub_year
        if d.edition:
            b.edition = d.edition
        if d.pages:
            b.pages = d.pages
        if (d.summary or "").strip():
            b.summary = d.summary.strip()
        if (d.author_bio or "").strip():
            b.author_bio = d.author_bio.strip()
        if d.language:
            b.language = d.language
        if getattr(d, "cip", None):
            b.cip = d.cip or b.cip
        return b

    # 无 ISBN：直接新建
    b = Book(
        title_std=d.title or "",
        authors_std=",".join(d.authors or []),
        publisher=d.publisher,
        pub_year=d.pub_year,
        isbn=None,
        edition=d.edition,
        pages=d.pages,
        summary=(d.summary or "").strip() or None,
        author_bio=(d.author_bio or "").strip() or None,
        language=d.language,
        cip=getattr(d, "cip", None),
    )
    session.add(b)
    session.flush()
    return b


# ---------- 主流程 ----------
def search_and_ingest(query: str):
    """
    1) 解析 ISBN/标题；
    2) 依次尝试 providers（失败快）；
    3) 写书目 + 封面（★ 以相对路径保存）；
    4) 若 clc 为空则自动分类；
    5) 记一条 Source。
    """
    init_db()
    providers = get_providers()
    session = SessionLocal()

    try:
        title, authors = split_title_author(query)
        isbn_input = find_isbn(query)
        author1 = (authors[0] if authors else "").strip()

        # 多路候选：标题 → 标题+第一作者 → 原始输入
        search_candidates = []
        if title:
            search_candidates.append(title)
        if title and author1:
            search_candidates.append(f"{title} {author1}")
        search_candidates.append(query)

        for p in providers:
            t0 = perf_counter()
            detail = None
            try:
                # 1) ISBN 直查
                if isbn_input and hasattr(p, "get_by_isbn"):
                    detail = p.get_by_isbn(isbn_input)

                # 2) 关键词（多路兜底）
                if not detail and hasattr(p, "search"):
                    for q in search_candidates:
                        res = p.search(q)
                        if res:
                            if hasattr(p, "get_detail") and getattr(res[0], "url", None):
                                detail = p.get_detail(res[0].url)
                            elif hasattr(p, "get_by_isbn") and getattr(res[0], "isbn", None):
                                detail = p.get_by_isbn(res[0].isbn)
                        if detail:
                            break
            except Exception as e:
                session.rollback()
                print(f"[{p.__class__.__name__}] exception:", e)

            if not detail:
                print(f"[{p.__class__.__name__}] no result ({perf_counter()-t0:.1f}s), next…")
                continue

            # ★ ISBN 一致性保护
            if isbn_input and getattr(detail, "isbn", None):
                if detail.isbn.replace("-", "").upper() != isbn_input.replace("-", "").upper():
                    print(f"[{p.__class__.__name__}] isbn mismatch: got {detail.isbn} expect {isbn_input}")
                    continue

            # 若 provider 没给 ISBN，但我们是 ISBN 入库，回填
            if isbn_input and not getattr(detail, "isbn", None):
                detail.isbn = isbn_input

            try:
                with session.begin():
                    book = _get_or_create_book_by_detail(detail, session)

                    # ---- 封面：保存为相对路径 ----
                    rel_cover = fetch_cover(getattr(detail, "cover_url", None))
                    if rel_cover and not book.cover_path:
                        book.cover_path = rel_cover  # e.g. "covers/xxxx.jpg"

                    # ---- 自动分类（clc 为空时）----
                    if not getattr(book, "clc", None):
                        code, _, _, _ = classify_clc(
                            title=book.title_std or "",
                            authors=(book.authors_std or "").split(",") if book.authors_std else [],
                            summary=book.summary or "",
                            cip=getattr(book, "cip", None),
                        )
                        if code and code.strip():
                            book.clc = code.strip()

                    s = Source(
                        book_id=book.id,
                        site=getattr(p, "site", p.__class__.__name__),
                        url=getattr(detail, "url", ""),
                        extracted=json.dumps(detail.__dict__, ensure_ascii=False),
                    )
                    session.add(s)

                return book.id

            except IntegrityError as ie:
                session.rollback()
                print("[DB] IntegrityError:", ie)
                if getattr(detail, "isbn", None):
                    existing = session.query(Book).filter(Book.isbn == detail.isbn).first()
                    if existing:
                        return existing.id

        return None

    finally:
        session.close()
