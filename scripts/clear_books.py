# scripts/clear_books.py
import os
from pathlib import Path

from app.db import SessionLocal, Base, engine

# SQLite 数据库文件路径
DB_PATH = Path(__file__).resolve().parents[1] / "data" / "app.db"

def main():
    # 确认用户操作
    confirm = input("⚠️ 这将清空数据库中所有数据，确定要继续吗？(yes/no): ")
    if confirm.lower() != "yes":
        print("❌ 已取消操作。")
        return

    # 如果数据库文件存在，直接删除重新建表
    if DB_PATH.exists():
        print(f"🗑 删除数据库文件: {DB_PATH}")
        os.remove(DB_PATH)

    # 重新创建空数据库
    print("📦 重新初始化空数据库...")
    Base.metadata.create_all(bind=engine)
    print("✅ 数据库已清空并重置为空。")

if __name__ == "__main__":
    main()

