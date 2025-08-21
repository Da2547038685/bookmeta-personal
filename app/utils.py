import re
import time
import hashlib
from dataclasses import dataclass
from typing import Optional

ISBN_RE = re.compile(r'(97[89]\d{10}|\d{9}[0-9Xx])')

def normalize_whitespace(s: str) -> str:
    return re.sub(r'\s+', ' ', s or '').strip()

def sha1(s: str) -> str:
    return hashlib.sha1(s.encode('utf-8')).hexdigest()

def find_isbn(text: str) -> Optional[str]:
    if not text: return None
    t = re.sub(r'[-\s]', '', text)
    m = ISBN_RE.search(t)
    return m.group(1) if m else None

class RateLimiter:
    def __init__(self, rps: float):
        self.min_interval = 1.0 / rps
        self.last = 0.0
    def wait(self):
        now = time.time()
        elapsed = now - self.last
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last = time.time()
