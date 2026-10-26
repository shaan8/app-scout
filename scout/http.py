import hashlib
import http.client
import json
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

import certifi

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
RETRY_STATUSES = {403, 429, 500, 502, 503, 504}
MAX_PAGE_BYTES = 3_000_000
MAX_INTERVAL = 20.0
# Only cache answers that will be the same next run; failures and throttling get retried.
CACHEABLE_PAGE_STATUSES = {200, 404, 410}
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


class Fetcher:
    """GET with a disk cache, per-host pacing and retry on throttling. Safe to share across threads."""

    def __init__(self, cache_dir: Path, min_interval: dict[str, float], use_cache: bool = True,
                 default_interval: float = 1.0):
        self.cache_dir = cache_dir
        self.min_interval = min_interval
        self.default_interval = default_interval
        self.use_cache = use_cache
        self._last_call: dict[str, float] = {}
        self._host_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
        cache_dir.mkdir(parents=True, exist_ok=True)

    def get_json(self, url: str, retries: int = 4, headers: dict | None = None):
        path = self._cache_path(url, "json")
        if self.use_cache and path.exists():
            return json.loads(path.read_text())

        for attempt in range(retries + 1):
            try:
                body, _, _ = self._open(url, {"Accept": "application/json", **(headers or {})}, limit=None)
                data = json.loads(body)
                break
            except urllib.error.HTTPError as e:
                if e.code not in RETRY_STATUSES or attempt == retries:
                    raise
                if e.code == 429:
                    self._slow_down(urllib.parse.urlsplit(url).hostname or "")
                retry_after = e.headers.get("Retry-After", "")
                time.sleep(int(retry_after) if retry_after.isdigit() else 30 * 2 ** attempt)
            except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException):
                if attempt == retries:
                    raise
                time.sleep(5 * 2 ** attempt)

        path.write_text(json.dumps(data))
        return data

    def get_page(self, url: str) -> dict:
        """Fetch an HTML page. Never raises: returns {"url", "final_url", "status", "text"}.

        status is the HTTP code, or 0 when the request failed before a response (DNS, TLS, timeout).
        """
        path = self._cache_path(url, "page")
        if self.use_cache and path.exists():
            return json.loads(path.read_text())

        result = {"url": url, "final_url": url, "status": 0, "text": ""}
        try:
            body, status, final_url = self._open(url, {"Accept": "text/html,*/*;q=0.8"}, limit=MAX_PAGE_BYTES)
            result.update(status=status, final_url=final_url, text=body.decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            result.update(status=e.code)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            pass
        if result["status"] in CACHEABLE_PAGE_STATUSES:
            path.write_text(json.dumps(result))
        return result

    def _open(self, url: str, headers: dict, limit: int | None) -> tuple[bytes, int, str]:
        """limit caps the bytes read, so one huge page can't stall the crawl. API responses are read whole."""
        self._pace(urllib.parse.urlsplit(url).hostname or "")
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})
        with urllib.request.urlopen(req, timeout=20, context=SSL_CONTEXT) as resp:
            return (resp.read() if limit is None else resp.read(limit)), resp.status, resp.url

    def _cache_path(self, url: str, kind: str) -> Path:
        key = url if kind == "json" else f"{kind}:{url}"
        return self.cache_dir / f"{hashlib.sha1(key.encode()).hexdigest()}.json"

    def _slow_down(self, host: str) -> None:
        """After a 429, space this host's calls out further for the rest of the run."""
        with self._host_locks[host]:
            current = self.min_interval.get(host, self.default_interval)
            self.min_interval[host] = min(current * 1.5, MAX_INTERVAL)

    def _pace(self, host: str) -> None:
        with self._host_locks[host]:
            interval = self.min_interval.get(host, self.default_interval)
            wait = interval - (time.monotonic() - self._last_call.get(host, 0))
            if wait > 0:
                time.sleep(wait)
            self._last_call[host] = time.monotonic()
