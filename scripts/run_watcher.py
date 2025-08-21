import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from pathlib import Path
from app.config import EBOOKS_DIR
from app.pipeline import search_and_ingest

class Handler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory: return
        name = Path(event.src_path).stem
        print("检测到新文件:", name)
        search_and_ingest(name)

if __name__ == "__main__":
    print("监听目录:", EBOOKS_DIR.resolve())
    event_handler = Handler()
    observer = Observer()
    observer.schedule(event_handler, str(EBOOKS_DIR), recursive=False)
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
