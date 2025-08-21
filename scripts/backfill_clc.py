# scripts/backfill_clc.py
from app.db import SessionLocal, Book, init_db
from app.classify import classify_clc

def main(limit=5000):
    init_db()
    s = SessionLocal()
    rows = s.query(Book).filter((Book.clc == None) | (Book.clc == "")).order_by(Book.id.asc()).limit(limit).all()
    print(f"待回填：{len(rows)}")
    n_ok = 0
    for b in rows:
        code, label, score, src = classify_clc(
            title=b.title_std or "",
            authors=(b.authors_std or "").split(",") if b.authors_std else [],
            summary=b.summary or "",
            cip=b.cip,
        )
        if code and code.strip():
            b.clc = code.strip()
            s.add(b)
            n_ok += 1
            print(f"[{b.id}] {b.title_std} -> CLC={b.clc} (src={src}, score={score:.2f})")
    s.commit()
    s.close()
    print(f"完成：写入 {n_ok} 条")

if __name__ == "__main__":
    main()
