# scripts/doctor.py
import sys, re, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import SessionLocal, Book, init_db
from app.pipeline import search_and_ingest

def looks_inconsistent(b: Book) -> bool:
    """
    粗判：标题与简介/封面来源常见不一致场景
    1) 有 ISBN 但标题很短或包含另一本的明显关键词
    2) 标题包含“南边的人，北边的人”但 ISBN 对应不在这个标题集合里（示例）
    """
    if not b.isbn:
        return False
    t = (b.title_std or "").strip()
    if len(t) <= 1:
        return True
    # 你可以在这里按你的库再补充一些规则
    return False

def main(limit=2000):
    init_db()
    s = SessionLocal()
    bad = []
    rows = s.query(Book).order_by(Book.id.desc()).limit(limit).all()
    for b in rows:
        if looks_inconsistent(b):
            bad.append((b.id, b.isbn, b.title_std))
    print(f"Found {len(bad)} suspicious rows.")
    for (bid, isbn, old_title) in bad:
        print(f" -> fix #{bid} {isbn} {old_title}")
        # 重新按 ISBN 抓并覆盖（会走我们加的 ISBN 强覆盖逻辑）
        search_and_ingest(isbn)
    s.close()

if __name__ == "__main__":
    main()
