# scripts/import_from_csv.py
"""
CSV 批量导入图书
- 列名容错：title/书名/标题, author/authors/作者, isbn/ISBN, query/检索词 ...
- 若无表头：把第一列当“原始行”，交给 split_title_author() 兜底
- 对每一行构造查询：
    1) 若有 ISBN -> 用 ISBN
    2) 否则 (title + authors)
    3) 否则 query
    4) 否则 第一列原始行
- 然后调用 search_and_ingest() 入库
用法：
    python scripts/import_from_csv.py samples/books.csv
"""

from __future__ import annotations
import sys
import csv
from pathlib import Path

# 让 Python 能 import 到项目根下的 app 包
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.pipeline import search_and_ingest
from app.nlp import split_title_author

# 允许的列名别名（大小写不敏感，读取后统一小写比较）
TITLE_KEYS = {"title", "书名", "标题", "name", "book", "book_title"}
AUTHOR_KEYS = {"author", "authors", "作者", "作者们", "author_name", "author_names"}
ISBN_KEYS = {"isbn", "图书编号", "编码"}
QUERY_KEYS = {"query", "检索词", "搜索", "原始行", "raw"}

ENCODINGS = ["utf-8-sig", "utf-8", "gbk", "gb2312"]  # 自动尝试几种常见编码


def _open_text(path: Path):
    last_exc = None
    for enc in ENCODINGS:
        try:
            return path.open("r", encoding=enc, newline="")
        except Exception as e:
            last_exc = e
            continue
    raise last_exc if last_exc else RuntimeError("无法读取文件编码")


def _normalize(s: str | None) -> str:
    s = (s or "").strip()
    # 常见的作者分隔替换成逗号，便于拼接
    for sep in [";", "；", "、", "/", "|", "，"]:
        s = s.replace(sep, ",")
    # 折叠连续逗号
    while ",," in s:
        s = s.replace(",,", ",")
    return s.strip(", ")


def _has_any(keys: set[str], fieldnames: list[str]) -> bool:
    fset = {k.lower() for k in (fieldnames or [])}
    return any(k in fset for k in keys)


def _pick(fieldnames: list[str], aliases: set[str]) -> str | None:
    fset = {k.lower(): k for k in fieldnames or []}
    for a in aliases:
        if a in fset:
            return fset[a]
    return None


def _sniff_dialect(sample: str) -> csv.Dialect:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except Exception:
        class _Fallback(csv.Dialect):
            delimiter = ","
            quotechar = '"'
            escapechar = None
            doublequote = True
            skipinitialspace = True
            lineterminator = "\n"
            quoting = csv.QUOTE_MINIMAL
        return _Fallback()


def import_csv(path: str) -> None:
    p = Path(path)
    if not p.exists():
        print(f"❌ 文件不存在: {p}")
        sys.exit(1)

    f = _open_text(p)
    # 取前 4KB 作为采样，判定分隔符
    sample = f.read(4096)
    f.seek(0)
    dialect = _sniff_dialect(sample)

    # 先尝试当作 DictReader（有表头）
    reader = csv.DictReader(f, dialect=dialect)
    fieldnames = reader.fieldnames or []

    def _iter_rows():
        # 如果表头命中了任何已知列名，就按 DictReader 处理
        if _has_any(TITLE_KEYS | AUTHOR_KEYS | ISBN_KEYS | QUERY_KEYS, fieldnames):
            for row in reader:
                yield row
        else:
            # 否则当作“无表头”处理：第一列为原始行
            f.seek(0)
            raw_reader = csv.reader(f, dialect=dialect)
            for cols in raw_reader:
                if not cols:
                    continue
                yield {"__raw__": cols[0]}

    total = ok = fail = 0
    for row in _iter_rows():
        total += 1

        isbn = ""
        title = ""
        authors = ""
        query = ""

        # 有表头场景下的取值
        if "__raw__" not in row:
            # 找到真实字段名（可能是中文）
            fn = list(row.keys())
            k_title = _pick(fn, {k.lower() for k in TITLE_KEYS})
            k_author = _pick(fn, {k.lower() for k in AUTHOR_KEYS})
            k_isbn = _pick(fn, {k.lower() for k in ISBN_KEYS})
            k_query = _pick(fn, {k.lower() for k in QUERY_KEYS})

            title = _normalize(row.get(k_title, "")) if k_title else ""
            authors = _normalize(row.get(k_author, "")) if k_author else ""
            isbn = _normalize(row.get(k_isbn, "")) if k_isbn else ""
            query = _normalize(row.get(k_query, "")) if k_query else ""

            # 如果没有 query，但有 title/author，就构造一个 query 方便日志与兜底
            if not query:
                if title and authors:
                    query = f"{title} {authors}"
                elif title:
                    query = title
                elif authors:
                    query = authors
        else:
            # 无表头：把第一列当原始行
            raw = (row.get("__raw__") or "").strip()
            # 让规则/NER 先尝试拆分，便于后续 provider 命中
            t, as_ = split_title_author(raw)
            title = _normalize(t)
            authors = _normalize(",".join(as_))
            query = raw

        # 构造最终用于检索的 q：
        # 优先 ISBN，其次 title+authors，再次 query
        if isbn:
            q = isbn
        elif title and authors:
            q = f"{title} {authors}"
        elif title:
            q = title
        elif query:
            q = query
        else:
            print(f">>> (第{total}行) 空行或无法解析，跳过")
            fail += 1
            continue

        print(f">>> (第{total}行) {q}")
        bid = search_and_ingest(q)
        if bid:
            print(f"  -> ✅ OK id={bid}")
            ok += 1
        else:
            print("  -> ❌ 未找到")
            fail += 1

    print("\n====== 导入完成 ======")
    print(f"总计: {total} | 成功: {ok} | 失败: {fail}")


def main():
    if len(sys.argv) < 2:
        print("用法: python scripts/import_from_csv.py <csv文件路径>")
        sys.exit(1)
    import_csv(sys.argv[1])


if __name__ == "__main__":
    main()
