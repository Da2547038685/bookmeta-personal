# app/config.py
from pathlib import Path

# 项目与数据目录
ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# SQLite 路径（db.py 需要）
DB_PATH = DATA_DIR / "app.db"

# 封面保存目录
COVERS_DIR = DATA_DIR / "covers"
COVERS_DIR.mkdir(parents=True, exist_ok=True)

# 仅启用豆瓣 & 京东（按顺序尝试）
PROVIDERS = ["douban", "jd"]

# 请求参数
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# 超时：连接超时/读取超时（秒）
REQUEST_TIMEOUT = (8, 12)         # 详情页/封面
REQUEST_TIMEOUT_FAST = (5, 8)     # 搜索页/探测

# 可选：离线目录（未启用时不影响）
OFFLINE_JSON = DATA_DIR / "offline_catalog.json"
