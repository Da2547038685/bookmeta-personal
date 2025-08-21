# scripts/prov_smoke.py
import sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.pipeline import search_and_ingest
from app.db import SessionLocal, Book, init_db

TEST_ISBNS = [
    "9787020002207",  # 红楼梦
    "9787536692930",  # 三体
    "9787506365437",  # 活着
    "9787544270878",  # 百年孤独
    "9787532731959",  # 时间简史
]

def main():
    init_db()
    s = SessionLocal()
    for code in TEST_ISBNS:
        print(f"\n=== 测试 {code} ===")
        bid = search_and_ingest(code)
        if not bid:
            print("  -> 未找到")
            continue
        b = s.query(Book).get(bid)
        print(f"  -> OK id={bid} | 标题={b.title_std} | ISBN={b.isbn} | 封面={'有' if b.cover_path else '无'}")
        time.sleep(1)
    s.close()

if __name__ == "__main__":
    main()
