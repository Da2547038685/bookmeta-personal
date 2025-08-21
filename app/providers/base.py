# app/providers/base.py
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Protocol

@dataclass
class SearchResult:
    """搜索结果的轻量项，用于从搜索页进入详情页"""
    title: str
    authors: List[str]
    url: Optional[str] = None
    isbn: Optional[str] = None

@dataclass
class BookDetail:
    """
    结构化的书籍元数据。注意：所有字段都允许为空（Optional），
    以兼容不同站点/页面不完整的情况。
    """
    title: str
    authors: List[str]

    publisher: Optional[str] = None
    pub_year: Optional[int] = None
    isbn: Optional[str] = None
    edition: Optional[str] = None
    pages: Optional[int] = None

    summary: Optional[str] = None
    author_bio: Optional[str] = None
    language: Optional[str] = None

    cover_url: Optional[str] = None

    # ★ 关键修复：cip/中图法分类号设为可选，默认 None
    cip: Optional[str] = None

class Provider(Protocol):
    """
    Provider 接口约定：站点实现 search / get_by_isbn / get_detail 任意组合。
    - search 返回若干 SearchResult（通常只需 title/authors/url/isbn）
    - get_by_isbn 直接返回 BookDetail（若站点提供 ISBN 定位）
    - get_detail 从详情页解析并返回 BookDetail
    """
    site: str

    def search(self, query: str) -> List[SearchResult]:
        """关键词/ISBN 搜索，返回若干 SearchResult；无结果返回空列表。"""
        ...

    def get_by_isbn(self, isbn: str) -> Optional[BookDetail]:
        """若站点支持 ISBN 直查则实现；未命中返回 None。"""
        ...

    def get_detail(self, url: str) -> Optional[BookDetail]:
        """解析详情页为 BookDetail；解析失败返回 None。"""
        ...
