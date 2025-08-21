# ui/web.py
# ===== 放在最顶部：让 Python 能 import 到项目根下的 app 包 =====
import sys, time, io, csv
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import streamlit as st
from app.db import SessionLocal, init_db, Book
from app.pipeline import search_and_ingest
from app.nlp import split_title_author
from app.classify import CLC_LABELS
from app.config import COVERS_DIR  # ★ 用于把相对路径解析成绝对路径

# ---- rerun 兼容处理 ----
try:
    rerun = st.rerun
except AttributeError:
    rerun = st.experimental_rerun

def hard_reload():
    try:
        st.cache_data.clear()
    except Exception:
        pass
    try:
        st.cache_resource.clear()
    except Exception:
        pass
    for k in list(st.session_state.keys()):
        if k.startswith(("editing-", "in-", "btn-", "confirm-del-")):
            st.session_state.pop(k, None)
    ts = str(int(time.time()))
    try:
        st.query_params["_t"] = ts
    except Exception:
        try:
            st.experimental_set_query_params(_t=ts)
        except Exception:
            pass
    rerun()

def auto_jump_refresh():
    ts = int(time.time())
    st.markdown(
        f"<meta http-equiv='refresh' content='0; url=/?_t={ts}#72f87f83'>",
        unsafe_allow_html=True
    )

# ====== CLC → 人话大类 ======
def clc_bucket(clc_code: str | None) -> str:
    if not clc_code:
        return "未分类"
    head = clc_code[0].upper()
    if head in {"T","O","Q","R","P","S","X","N","U","V"}: return "科学技术类"
    if head == "K": return "历史类"
    if head == "J": return "艺术类"
    if head == "I": return "文学类"
    if head == "H": return "语言类"
    if head == "F": return "经济管理类"
    if head == "G": return "教育文化类"
    if head == "B": return "哲学宗教类"
    if head in {"C","D"}: return "社会政治类"
    if head in {"A","Z"}: return "综合/知识类"
    return CLC_LABELS.get(head, "未分类")

# ===== CSV 导入工具 =====
TITLE_KEYS = {"title", "书名", "标题", "name", "book", "book_title"}
AUTHOR_KEYS = {"author", "authors", "作者", "作者们", "author_name", "author_names"}
ISBN_KEYS = {"isbn", "图书编号", "编码"}
QUERY_KEYS = {"query", "检索词", "搜索", "原始行", "raw"}
ENCODINGS = ["utf-8-sig", "utf-8", "gbk", "gb2312"]

def _decode_bytes(data: bytes) -> io.StringIO:
    last_exc = None
    for enc in ENCODINGS:
        try:
            return io.StringIO(data.decode(enc))
        except Exception as e:
            last_exc = e
    raise last_exc if last_exc else RuntimeError("无法解析文件编码")

def _normalize(s: str | None) -> str:
    s = (s or "").strip()
    for sep in [";", "；", "、", "/", "|", "，"]:
        s = s.replace(sep, ",")
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

def import_csv_bytes(data: bytes) -> tuple[int, int, int]:
    buf = _decode_bytes(data)
    sample = buf.read(4096); buf.seek(0)
    dialect = _sniff_dialect(sample)
    reader = csv.DictReader(buf, dialect=dialect)
    fieldnames = reader.fieldnames or []

    def _iter_rows():
        if _has_any(TITLE_KEYS | AUTHOR_KEYS | ISBN_KEYS | QUERY_KEYS, fieldnames):
            for row in reader:
                yield row
        else:
            buf.seek(0)
            raw_reader = csv.reader(buf, dialect=dialect)
            for cols in raw_reader:
                if cols:
                    yield {"__raw__": cols[0]}

    total = ok = fail = 0
    progress = st.progress(0, text="正在导入…")
    for row in _iter_rows():
        total += 1
        isbn = title = authors = query = ""

        if "__raw__" not in row:
            fn = list(row.keys())
            k_title = _pick(fn, {k.lower() for k in TITLE_KEYS})
            k_author = _pick(fn, {k.lower() for k in AUTHOR_KEYS})
            k_isbn = _pick(fn, {k.lower() for k in ISBN_KEYS})
            k_query = _pick(fn, {k.lower() for k in QUERY_KEYS})
            title   = _normalize(row.get(k_title, "")) if k_title else ""
            authors = _normalize(row.get(k_author, "")) if k_author else ""
            isbn    = _normalize(row.get(k_isbn, "")) if k_isbn else ""
            query   = _normalize(row.get(k_query, "")) if k_query else ""
            if not query:
                query = (f"{title} {authors}".strip() or title or authors)
        else:
            raw = (row.get("__raw__") or "").strip()
            t, as_ = split_title_author(raw)
            title = _normalize(t)
            authors = _normalize(",".join(as_))
            query = raw

        q = isbn or (f"{title} {authors}".strip()) or title or query
        if not q:
            st.write(f">>> (第{total}行) 空行或无法解析，跳过")
            fail += 1
            progress.progress(0.0, text=f"正在导入… {ok} 成功 / {fail} 失败")
            continue

        st.write(f">>> (第{total}行) {q}")
        bid = search_and_ingest(q)
        if bid:
            ok += 1
            st.write(f"  -> ✅ OK id={bid}")
        else:
            fail += 1
            st.write("  -> ❌ 未找到")
        progress.progress(0.0, text=f"正在导入… {ok} 成功 / {fail} 失败")
    progress.empty()
    return total, ok, fail

# ============ 页面 & 初始化 ============
st.set_page_config(page_title="BookMeta 个人版", layout="wide")
st.title("📚 BookMeta 个人版")
init_db()

# ============ 侧边栏：新增图书 + 批量导入 ============
with st.sidebar:
    st.header("新增图书")
    st.caption("输入书名/作者/ISBN，点击抓取并入库。建议优先用 ISBN，命中率最高。")
    add_q = st.text_input("书名/作者/ISBN", key="add-query")
    add_btn = st.button("抓取并入库", use_container_width=True, key="add-button")
    if add_btn:
        text = (add_q or "").strip()
        if not text:
            st.warning("请输入内容后再点击。")
        else:
            bid = search_and_ingest(text)
            if bid:
                st.success(f"✅ 已入库（ID={bid}）")
                auto_jump_refresh()
            else:
                st.warning("未从任何数据源获取到元数据。")

    st.divider()
    st.header("批量导入（CSV）")
    st.caption("支持含有表头的 CSV（title/author/isbn/query 容错），或无表头（第一列当原始行）。")
    up = st.file_uploader("选择 CSV 文件", type=["csv"], accept_multiple_files=False, key="csv-upload")
    if up is not None:
        st.write(f"文件：{up.name}，大小：{up.size} bytes")
        start = st.button("开始导入", use_container_width=True, key="csv-start")
        if start:
            with st.spinner("正在批量导入，请稍候…"):
                data = up.read()
                total, ok, fail = import_csv_bytes(data)
            st.success(f"导入完成：总计 {total}，成功 {ok}，失败 {fail}")
            auto_jump_refresh()

# ============ 顶部搜索 ============
kw = st.text_input("搜索（标题/作者/ISBN）", key="global-search")

# ============ DB 查询（稳定排序） ============
session = SessionLocal()
query = session.query(Book)
if kw:
    like = f"%{kw}%"
    query = query.filter(
        (Book.title_std.like(like)) |
        (Book.authors_std.like(like)) |
        (Book.isbn.like(like))
    )
rows = query.order_by(Book.id.desc(), Book.created_at.desc()).limit(300).all()
session.close()

# ============ 每本书独立分片渲染 ============
try:
    fragment = st.fragment  # Streamlit 1.28+
except AttributeError:
    fragment = st.experimental_fragment

def _resolve_cover_path(cover_path: str | None) -> str | None:
    """把 DB 中保存的封面路径解析为本机绝对路径。
    - 支持 'covers/xxx.jpg' 相对路径
    - 兼容历史绝对路径（存在就直接用）
    - 若文件不存在，尝试按文件名在 COVERS_DIR 下寻找/模糊匹配
    """
    if not cover_path:
        return None
    p = Path(cover_path)
    # 相对路径：以当前 data/covers 为准
    if not p.is_absolute():
        abs_path = COVERS_DIR / p.name
        if abs_path.exists():
            return str(abs_path)
        # 模糊：slug 可能被截断
        cand = list(COVERS_DIR.glob(p.stem + "*"))
        if cand:
            return str(cand[0])
        return None
    # 绝对路径（历史数据）
    if p.exists():
        return str(p)
    # 绝对路径失效：按文件名到当前 covers 下找
    alt = COVERS_DIR / p.name
    if alt.exists():
        return str(alt)
    cand = list(COVERS_DIR.glob(p.stem + "*"))
    if cand:
        return str(cand[0])
    return None

@fragment
def render_card(book_id: int):
    S = SessionLocal()
    b = S.get(Book, book_id)
    if not b:
        S.close()
        return

    bucket = clc_bucket(b.clc)
    clc_show = b.clc or "—"
    bucket_show = bucket or "未分类"

    with st.container(key=f"card-{b.id}", border=True):
        st.markdown(f"### {b.title_std}")
        st.caption(
            f"作者：{b.authors_std or '未知'}｜出版社：{b.publisher or '未知'}｜"
            f"年份：{b.pub_year or '—'}｜ISBN：{b.isbn or '—'}｜"
            f"CLC：{clc_show}｜类别：{bucket_show}"
        )
        col1, col2 = st.columns([1, 3], vertical_alignment="top")
        with col1:
            img_path = _resolve_cover_path(b.cover_path)
            if img_path:
                st.image(img_path, use_container_width=True)
            else:
                st.image("https://placehold.co/220x300?text=No+Cover", use_container_width=True)
        with col2:
            st.write((b.summary or "暂无简介")[:1200])

            ops_cols = st.columns([1, 1, 1, 2])
            edit_clicked = ops_cols[0].button("编辑", key=f"btn-edit-{b.id}")
            refresh_clicked = ops_cols[1].button("刷新", key=f"btn-refresh-{b.id}")
            delete_clicked = ops_cols[2].button("删除", key=f"btn-del-{b.id}")

            if refresh_clicked and b.isbn:
                bid2 = search_and_ingest(b.isbn)
                if bid2:
                    st.success("已刷新该书元数据。")
                    S.close()
                    hard_reload()
                else:
                    st.warning("刷新失败：数据源未返回。")

            if delete_clicked:
                st.session_state[f"confirm-del-{b.id}"] = True

            if st.session_state.get(f"confirm-del-{b.id}", False):
                with st.form(f"form-del-{b.id}", clear_on_submit=False, border=True):
                    st.warning(f"确定要删除《{b.title_std}》吗？此操作不可撤销。")
                    col_ok, col_cancel = st.columns([1, 1])
                    do_delete = col_ok.form_submit_button("确认删除", use_container_width=True)
                    do_cancel = col_cancel.form_submit_button("取消", use_container_width=True)
                    if do_cancel:
                        st.session_state[f"confirm-del-{b.id}"] = False
                    if do_delete:
                        fresh = S.get(Book, b.id)
                        if fresh:
                            S.delete(fresh)
                            S.commit()
                        st.session_state.pop(f"confirm-del-{b.id}", None)
                        S.close()
                        auto_jump_refresh()
                        return

            if edit_clicked:
                st.session_state[f"editing-{b.id}"] = True

            if st.session_state.get(f"editing-{b.id}", False):
                with st.form(f"form-{b.id}", clear_on_submit=False, border=True):
                    title = st.text_input("标题", value=b.title_std, key=f"in-title-{b.id}")
                    authors = st.text_input("作者（逗号分隔）", value=b.authors_std or "", key=f"in-authors-{b.id}")
                    publisher = st.text_input("出版社", value=b.publisher or "", key=f"in-publisher-{b.id}")
                    pub_year = st.number_input("年份", min_value=0, max_value=2100, value=b.pub_year or 0, key=f"in-year-{b.id}")
                    isbn = st.text_input("ISBN", value=b.isbn or "", key=f"in-isbn-{b.id}")
                    summary = st.text_area("内容简介", value=b.summary or "", height=160, key=f"in-summary-{b.id}")
                    save = st.form_submit_button("保存", use_container_width=True)
                    cancel = st.form_submit_button("取消", use_container_width=True)
                    if cancel:
                        st.session_state[f"editing-{b.id}"] = False
                        S.close()
                        hard_reload()
                    if save:
                        fresh = S.get(Book, b.id)
                        if fresh:
                            fresh.title_std = title.strip()
                            fresh.authors_std = (authors or "").strip() or None
                            fresh.publisher = (publisher or "").strip() or None
                            fresh.pub_year = int(pub_year) or None
                            fresh.isbn = (isbn or "").strip() or None
                            fresh.summary = summary or None
                            S.add(fresh)
                            S.commit()
                        st.session_state[f"editing-{b.id}"] = False
                        S.close()
                        hard_reload()
                        return
    S.close()

# ============ 渲染列表 ============
if not rows:
    st.info("暂无记录。可以在左侧新增图书，或上传 CSV 批量导入。")
else:
    for b in rows:
        render_card(b.id)
