# main.py
import os, sys, webbrowser
from pathlib import Path

def load_env_file(env_path: Path):
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"): 
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

def resolve_app_root() -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # PyInstaller 解包目录
    return Path(__file__).resolve().parent

def main():
    app_root = resolve_app_root()
    os.chdir(app_root)                         # data 持久化在 EXE 同级
    os.environ["PYTHONPATH"] = str(app_root)
    load_env_file(app_root / ".env")
    (app_root / "data" / "covers").mkdir(parents=True, exist_ok=True)
    try:
        webbrowser.open("http://localhost:8501", new=1, autoraise=True)
    except Exception:
        pass
    from streamlit.web.bootstrap import run as st_run
    script = str(app_root / "ui" / "web.py")
    flag_options = {
        "server.port": 8501,
        "server.headless": True,
        "browser.gatherUsageStats": False,
        "client.toolbarMode": "viewer",
        # 如需局域网访问可加："server.address": "0.0.0.0"
    }
    st_run(script, "", [], flag_options=flag_options)

if __name__ == "__main__":
    main()
