# app/desktop/main_qt.py
from __future__ import annotations
import os, sys, threading, traceback, csv
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QSize, Signal, QObject
from PySide6.QtGui import QPixmap, QAction
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QLabel, QLineEdit, QTextEdit,
    QPushButton, QFileDialog, QMessageBox, QFormLayout, QSpinBox, QSplitter, QToolBar, QStatusBar
)

# ---- 将项目根目录加入 sys.path，便于相对导入 ----
ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# 业务层：直接复用你现有的模块
from app.db import SessionLocal, init_db, Book
from app.pipeline import search_and_ingest
from app.classify import CLC_LABELS

DATA_DIR = ROOT_DIR / "data"
COVERS_DIR = DATA_DIR / "covers"

def clc_bucket(clc_code: Optional[str]) -> str:
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

# --------- 异步信号 ---------
class WorkerSignals(QObject):
    finished = Signal()
    error = Signal(str)
    success = Signal(str)

# --------- 主窗体 ---------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BookMeta 个人版（桌面端）")
        self.resize(1200, 800)

        init_db()  # 确保数据库就绪

        # 工具栏
        tb = QToolBar("Main")
        tb.setIconSize(QSize(16, 16))
        self.addToolBar(tb)

        act_refresh = QAction("刷新列表", self)
        act_add = QAction("新增（书名/作者/ISBN）", self)
        act_import = QAction("导入 CSV", self)
        tb.addAction(act_refresh)
        tb.addAction(act_add)
        tb.addAction(act_import)

        # 顶部搜索
        top = QWidget()
        top_layout = QHBoxLayout(top)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索：标题 / 作者 / ISBN")
        self.search_btn = QPushButton("搜索")
        top_layout.addWidget(self.search_edit)
        top_layout.addWidget(self.search_btn)

        # 左侧列表
        self.list_widget = QListWidget()
        self.list_widget.setAlternatingRowColors(True)

        # 右侧详情
        self.cover_label = QLabel()
        self.cover_label.setFixedSize(220, 300)
        self.cover_label.setAlignment(Qt.AlignCenter)

        form = QFormLayout()
        self.title_edit = QLineEdit()
        self.authors_edit = QLineEdit()
        self.publisher_edit = QLineEdit()
        self.year_spin = QSpinBox(); self.year_spin.setRange(0, 2100)
        self.isbn_edit = QLineEdit()
        self.clc_label = QLabel("—")
        self.bucket_label = QLabel("未分类")
        self.summary_edit = QTextEdit()
        self.summary_edit.setFixedHeight(180)

        form.addRow("标题：", self.title_edit)
        form.addRow("作者（逗号分隔）：", self.authors_edit)
        form.addRow("出版社：", self.publisher_edit)
        form.addRow("年份：", self.year_spin)
        form.addRow("ISBN：", self.isbn_edit)
        form.addRow("CLC：", self.clc_label)
        form.addRow("类别：", self.bucket_label)
        form.addRow("内容简介：", self.summary_edit)

        btn_row = QHBoxLayout()
        self.btn_save = QPushButton("保存修改")
        self.btn_refresh = QPushButton("重新抓取（按 ISBN）")
        self.btn_delete = QPushButton("删除此书")
        btn_row.addWidget(self.btn_save)
        btn_row.addWidget(self.btn_refresh)
        btn_row.addWidget(self.btn_delete)

        right_box = QWidget()
        right_layout = QVBoxLayout(right_box)
        right_layout.addWidget(self.cover_label)
        right_layout.addLayout(form)
        right_layout.addLayout(btn_row)

        # 中间分割
        split = QSplitter(Qt.Horizontal)
        left_box = QWidget(); lb = QVBoxLayout(left_box)
        lb.setContentsMargins(0,0,0,0)
        lb.addWidget(top)
        lb.addWidget(self.list_widget)
        split.addWidget(left_box)
        split.addWidget(right_box)
        split.setSizes([420, 780])

        self.setCentralWidget(split)
        self.setStatusBar(QStatusBar())

        # 状态
        self.current_id: Optional[int] = None
        self._wire_events()

        # 初始加载
        self.load_list()

    # 事件绑定
    def _wire_events(self):
        self.search_btn.clicked.connect(lambda: self.load_list(self.search_edit.text().strip()))
        self.list_widget.currentItemChanged.connect(self.on_select)
        self.btn_delete.clicked.connect(self.on_delete)
        self.btn_save.clicked.connect(self.on_save)
        self.btn_refresh.clicked.connect(self.on_reingest)
        # 工具栏
        self.findChild(QAction, "新增（书名/作者/ISBN）").triggered.connect(self.on_add_dialog)
        self.findChild(QAction, "刷新列表").triggered.connect(lambda: self.load_list(self.search_edit.text().strip()))
        self.findChild(QAction, "导入 CSV").triggered.connect(self.on_import_csv)

    # 列表加载
    def load_list(self, kw: str = ""):
        self.list_widget.clear()
        S = SessionLocal()
        try:
            q = S.query(Book)
            if kw:
                like = f"%{kw}%"
                q = q.filter( (Book.title_std.like(like)) | (Book.authors_std.like(like)) | (Book.isbn.like(like)) )
            rows = q.order_by(Book.id.desc()).limit(500).all()
            for b in rows:
                item = QListWidgetItem(f"{b.title_std}  [{b.isbn or '—'}]")
                item.setData(Qt.UserRole, b.id)
                self.list_widget.addItem(item)
            self.statusBar().showMessage(f"共 {len(rows)} 条记录")
        finally:
            S.close()

    # 选择条目
    def on_select(self, cur: QListWidgetItem, _prev: QListWidgetItem):
        if not cur:
            return
        bid = cur.data(Qt.UserRole)
        self.fill_detail(bid)

    def _load_cover_pixmap(self, b: Book) -> QPixmap:
        # cover_path 存相对路径（如 covers/xxx.jpg）
        if b.cover_path:
            path = Path(b.cover_path)
            if not path.is_absolute():
                path = ROOT_DIR / "data" / path
            if path.exists():
                pm = QPixmap(str(path))
                if not pm.isNull():
                    return pm.scaled(self.cover_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        # 占位
        pm = QPixmap(220, 300)
        pm.fill(Qt.lightGray)
        return pm

    # 填充右侧详情
    def fill_detail(self, bid: int):
        self.current_id = bid
        S = SessionLocal()
        try:
            b = S.get(Book, bid)
            if not b:
                return
            self.cover_label.setPixmap(self._load_cover_pixmap(b))
            self.title_edit.setText(b.title_std or "")
            self.authors_edit.setText(b.authors_std or "")
            self.publisher_edit.setText(b.publisher or "")
            self.year_spin.setValue(int(b.pub_year or 0))
            self.isbn_edit.setText(b.isbn or "")
            self.summary_edit.setPlainText(b.summary or "")
            self.clc_label.setText(b.clc or "—")
            self.bucket_label.setText(clc_bucket(b.clc))
        finally:
            S.close()

    # 保存
    def on_save(self):
        if not self.current_id:
            return
        S = SessionLocal()
        try:
            b = S.get(Book, self.current_id)
            if not b:
                return
            b.title_std = self.title_edit.text().strip()
            b.authors_std = self.authors_edit.text().strip() or None
            b.publisher = self.publisher_edit.text().strip() or None
            y = int(self.year_spin.value())
            b.pub_year = y or None
            b.isbn = self.isbn_edit.text().strip() or None
            b.summary = self.summary_edit.toPlainText() or None
            S.add(b); S.commit()
            self.statusBar().showMessage("✅ 已保存")
            # 更新左侧显示
            cur = self.list_widget.currentItem()
            if cur:
                cur.setText(f"{b.title_std}  [{b.isbn or '—'}]")
        finally:
            S.close()

    # 删除
    def on_delete(self):
        if not self.current_id:
            return
        ret = QMessageBox.question(self, "确认删除", "确定要删除这本书吗？此操作不可撤销。")
        if ret != QMessageBox.Yes:
            return
        S = SessionLocal()
        try:
            b = S.get(Book, self.current_id)
            if b:
                S.delete(b); S.commit()
            self.statusBar().showMessage("🗑️ 已删除")
            self.current_id = None
            self.load_list(self.search_edit.text().strip())
        finally:
            S.close()

    # 重新抓取（用 ISBN）
    def on_reingest(self):
        isbn = self.isbn_edit.text().strip()
        if not isbn:
            QMessageBox.information(self, "提示", "需要 ISBN 才能刷新。")
            return
        self._do_background_ingest(isbn, done_msg="已刷新（如数据源有更新）")

    # 新增（弹出输入框）
    def on_add_dialog(self):
        text, ok = QFileDialog.getSaveFileName  # 占位为了避开 PySide “内联输入”中文法的坑
        # 使用一个简易输入对话（避免依赖额外库）
        kw, ok = QInputDialog.getText(self, "新增图书", "输入 书名/作者/ISBN：")
        if not ok or not kw.strip():
            return
        self._do_background_ingest(kw.strip(), done_msg="已入库")

    # CSV 导入
    def on_import_csv(self):
        file, _ = QFileDialog.getOpenFileName(self, "选择 CSV", str(Path.home()), "CSV Files (*.csv)")
        if not file:
            return
        ok = self._import_csv(file)
        if ok:
            self.load_list(self.search_edit.text().strip())

    # 导入 CSV（轻量实现）
    def _import_csv(self, filename: str) -> bool:
        try:
            total = ok = fail = 0
            with open(filename, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                fieldnames = [c.lower() for c in (reader.fieldnames or [])]
                def pick(keys):
                    for k in keys:
                        if k in fieldnames:
                            return k
                    return None
                k_title = pick({"title","书名","name"})
                k_author = pick({"author","authors","作者"})
                k_isbn = pick({"isbn"})
                for row in reader:
                    total += 1
                    q = ((row.get(k_isbn) or "") if k_isbn else "") or \
                        f"{(row.get(k_title) or '')} {(row.get(k_author) or '')}".strip()
                    if not q.strip():
                        fail += 1; continue
                    bid = search_and_ingest(q.strip())
                    if bid: ok += 1
                    else: fail += 1
            QMessageBox.information(self, "导入完成", f"总计 {total}，成功 {ok}，失败 {fail}")
            return True
        except Exception as e:
            QMessageBox.critical(self, "导入失败", str(e))
            return False

    # 后台抓取，避免卡 UI
    def _do_background_ingest(self, query: str, done_msg: str):
        sig = WorkerSignals()
        def work():
            try:
                bid = search_and_ingest(query)
                if bid:
                    sig.success.emit(f"{done_msg}（ID={bid}）")
                else:
                    sig.error.emit("未从任何数据源获取到元数据。")
            except Exception:
                sig.error.emit(traceback.format_exc())
            finally:
                sig.finished.emit()

        def on_ok(msg: str):
            self.statusBar().showMessage("✅ " + msg)
            # 刷新列表并定位
            self.load_list(self.search_edit.text().strip())
            # 可选：自动选中刚入库的
        def on_err(msg: str):
            QMessageBox.warning(self, "提示", msg)

        sig.success.connect(on_ok)
        sig.error.connect(on_err)

        t = threading.Thread(target=work, daemon=True)
        t.start()
        self.statusBar().showMessage("⌛ 正在抓取，请稍候…")

# 入口
def run():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    run()
