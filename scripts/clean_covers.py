# scripts/clean_covers.py
from pathlib import Path
from app.db import SessionLocal, Book
from app.config import COVERS_DIR

def main():
    session = SessionLocal()
    used_covers = {
        Path(b.cover_path).name
        for b in session.query(Book).filter(Book.cover_path.isnot(None))
    }
    session.close()

    deleted_count = 0
    for f in Path(COVERS_DIR).glob("*"):
        if f.is_file() and f.name not in used_covers:
            f.unlink()
            deleted_count += 1

    print(f"✅ 已删除 {deleted_count} 个无用封面文件。")

if __name__ == "__main__":
    main()
