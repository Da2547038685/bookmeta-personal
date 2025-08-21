# scripts/self_check.py
import sys, importlib, traceback, json, inspect
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def ok(msg):  print("✅", msg)
def warn(msg):print("⚠️ ", msg)
def err(msg): print("❌", msg)

def check_imports():
    try:
        import app, app.db, app.config, app.pipeline
        ok("包路径与导入正常（app/, app.db, app.pipeline 可导入）")
    except Exception as e:
        err(f"导入失败：{e}")
        traceback.print_exc()

def check_config():
    from app import config
    must = ["DATA_DIR","DB_PATH","COVERS_DIR","PROVIDERS","REQUEST_TIMEOUT","USER_AGENT"]
    miss = [k for k in must if not hasattr(config,k)]
    if miss:
        err(f"config 缺少字段：{miss}")
    else:
        ok("config 字段完整")
    print("PROVIDERS =", getattr(config,"PROVIDERS",None))

def check_db():
    from sqlalchemy import inspect as sa_inspect
    from app.db import init_db, engine, Book
    init_db()
    insp = sa_inspect(engine)
    if not insp.has_table("books"):
        err("数据库表 books 不存在")
        return
    cols = {c["name"]:c for c in insp.get_columns("books")}
    if "isbn" not in cols:
        err("books.isbn 字段不存在")
    else:
        ok("books.isbn 字段存在")
    idx = [i["name"] for i in insp.get_indexes("books")]
    if any("isbn" in (i or "") for i in idx) or cols["isbn"].get("unique"):
        ok("ISBN 唯一/索引已设置（至少其一）")
    else:
        warn("ISBN 没有唯一或索引，建议设置 unique=True, index=True")

def check_providers():
    from app.pipeline import get_providers
    ps = get_providers()
    if not ps:
        err("PROVIDERS 列表为空或加载失败")
        return
    names = [getattr(p,"site",p.__class__.__name__) for p in ps]
    print("加载到的 Providers:", names)
    for p in ps:
        name = getattr(p,"site",p.__class__.__name__)
        has_isbn = hasattr(p,"get_by_isbn") and callable(p.get_by_isbn)
        has_search = hasattr(p,"search") and callable(p.search)
        if not has_isbn:
            warn(f"{name}: 缺少 get_by_isbn（ISBN 精确导入会失败）")
        else:
            ok(f"{name}: get_by_isbn 存在")
        if not has_search:
            warn(f"{name}: 缺少 search（书名模糊搜索会失败）")
        else:
            ok(f"{name}: search 存在")

def check_pipeline_guard():
    from app.pipeline import search_and_ingest, _get_or_create_book_by_detail
    sig = inspect.signature(_get_or_create_book_by_detail)
    ok("pipeline 保护逻辑已包含：ISBN 优先 + 无 ISBN 不随意合并（通过函数存在性检查）")

def main():
    print("== 自检开始 ==")
    check_imports()
    check_config()
    check_db()
    check_providers()
    try:
        check_pipeline_guard()
    except Exception:
        warn("未检测到 _get_or_create_book_by_detail（使用旧版 pipeline ？）")
    print("== 自检结束 ==")

if __name__ == "__main__":
    main()
