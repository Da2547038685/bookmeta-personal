# scripts/import_from_txt.py
import sys, pathlib
from app.pipeline import search_and_ingest

def main(path: str):
    if path == "-":
        content = sys.stdin.read()
    else:
        p = pathlib.Path(path)
        content = p.read_text(encoding="utf-8")
    lines = [l.strip() for l in content.splitlines() if l.strip()]
    for ln in lines:
        print(">>>", ln)
        bid = search_and_ingest(ln)
        print("  ->", "OK id="+str(bid) if bid else "未找到")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python scripts/import_from_txt.py <txt文件路径>  或  '-' (从stdin读)")
        sys.exit(1)
    main(sys.argv[1])
