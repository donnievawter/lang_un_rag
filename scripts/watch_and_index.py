#!/usr/bin/env python3
"""
Watch a docs directory and call the indexing endpoint when new/changed files appear.

Key behavior changes for HTTPS endpoint:
 - Posts JSON body '{}' (requests.post(endpoint, json={})) with Content-Type: application/json
 - Retries a few times with exponential backoff on transient network/errors
 - Optional --insecure flag to disable TLS verification (only for testing)
"""
import time
import argparse
import logging
import os
import sys
import threading
from pathlib import Path
import requests

try:
    from watchdog.events import FileSystemEventHandler, FileSystemEvent
    from watchdog.observers.polling import PollingObserver
except Exception as e:
    print("Missing dependency 'watchdog'. Install: pip install watchdog requests", file=sys.stderr)
    raise

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("watch_and_index")

class DebouncedHandler(FileSystemEventHandler):
    def __init__(self, trigger_fn, debounce_seconds=60, wait_stable=2):
        super().__init__()
        self.trigger_fn = trigger_fn
        self.debounce_seconds = debounce_seconds
        self.wait_stable = wait_stable
        self._lock = threading.Lock()
        self._last_trigger = 0

    def _should_trigger(self):
        now = time.time()
        with self._lock:
            if now - self._last_trigger < self.debounce_seconds:
                logger.debug("Debounce: last trigger was %.1fs ago (< %ds); skipping", now - self._last_trigger, self.debounce_seconds)
                return False
            self._last_trigger = now
        return True

    def _wait_for_stable(self, path: str, timeout: int = 300) -> bool:
        p = Path(path)
        if not p.exists():
            return False
        if p.is_dir():
            return True

        last_size = -1
        stable_since = None
        start = time.time()
        while True:
            try:
                size = p.stat().st_size
            except OSError:
                time.sleep(0.5)
                if time.time() - start > timeout:
                    return False
                continue
            now = time.time()
            if size == last_size:
                if stable_since is None:
                    stable_since = now
                elif now - stable_since >= self.wait_stable:
                    return True
            else:
                stable_since = None
                last_size = size
            if now - start > timeout:
                logger.warning("Timeout waiting for file to stabilize: %s", path)
                return False
            time.sleep(0.5)

    def _on_event_core(self, src_path: str):
        logger.info("Filesystem event observed: %s", src_path)
        if not self._wait_for_stable(src_path):
            logger.info("Not triggering index for %s (not stable or timed out)", src_path)
            return
        if not self._should_trigger():
            return
        threading.Thread(target=self.trigger_fn, args=(src_path,), daemon=True).start()

    def on_created(self, event: FileSystemEvent):
        self._on_event_core(event.src_path)

    def on_modified(self, event: FileSystemEvent):
        self._on_event_core(event.src_path)

    def on_moved(self, event: FileSystemEvent):
        self._on_event_core(event.dest_path)

def trigger_index(endpoint: str, src_path: str, verify: bool = True, max_attempts: int = 3):
    logger.info("Triggering index endpoint %s due to change in %s", endpoint, src_path)
    attempt = 0
    backoff = 1
    headers = {"Content-Type": "application/json"}
    while attempt < max_attempts:
        attempt += 1
        try:
            resp = requests.post(endpoint, json={}, headers=headers, timeout=120, verify=verify)
            if resp.ok:
                logger.info("Index request succeeded (status=%s)", resp.status_code)
                return True
            else:
                logger.warning("Index request returned status=%s: %s", resp.status_code, resp.text[:200])
        except requests.exceptions.RequestException as e:
            logger.warning("Index request attempt %d failed: %s", attempt, e)
        if attempt < max_attempts:
            time.sleep(backoff)
            backoff *= 2
    logger.error("All attempts to call index endpoint failed for %s", src_path)
    return False
# health-check helper - add to watch_and_index.py
def wait_for_health(endpoint_health: str, timeout: int = 60, verify: bool = True):
    """Poll a health URL (GET) until it returns 200 or timeout (seconds)."""
    start = time.time()
    backoff = 1
    while True:
        try:
            r = requests.get(endpoint_health, timeout=5, verify=verify)
            if r.ok:
                logger.info("Health check passed at %s", endpoint_health)
                return True
        except Exception as e:
            logger.debug("Health check attempt failed: %s", e)
        if time.time() - start > timeout:
            logger.warning("Health check timed out after %ds for %s", timeout, endpoint_health)
            return False
        time.sleep(backoff)
        backoff = min(backoff * 2, 5)
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch-dir", required=True, help="Directory to watch")
    parser.add_argument("--endpoint", default="http://localhost:8000/index", help="Index endpoint to POST to (use https://rag.hlab.com/index)")
    parser.add_argument("--debounce", type=int, default=60, help="Seconds to debounce index calls")
    parser.add_argument("--poll-interval", type=int, default=5, help="Polling interval for the PollingObserver (seconds)")
    parser.add_argument("--wait-stable", type=int, default=2, help="Seconds file size must be stable before triggering")
    parser.add_argument("--insecure", action="store_true", help="Disable TLS verification (not recommended)")
    args = parser.parse_args()

    watch_dir = Path(args.watch_dir).resolve()
    if not watch_dir.exists() or not watch_dir.is_dir():
        logger.error("Watch directory does not exist or is not a directory: %s", watch_dir)
        raise SystemExit(2)

    verify = not args.insecure
    logger.info("Starting watcher on %s (endpoint=%s) (debounce=%ds, poll=%ds, verify=%s)", watch_dir, args.endpoint, args.debounce, args.poll_interval, verify)

    # Use polling observer (robust with NFS)
    observer = PollingObserver(timeout=args.poll_interval)
    handler = DebouncedHandler(lambda path: trigger_index(args.endpoint, path, verify=verify), debounce_seconds=args.debounce, wait_stable=args.wait_stable)
    observer.schedule(handler, str(watch_dir), recursive=True)

    try:
        health_url = args.endpoint.replace("/index", "/health")  # if app supports /health
        wait_for_health(health_url, timeout=60, verify=verify)
        observer.start()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stopping watcher (KeyboardInterrupt)")
    finally:
        observer.stop()
        observer.join()

if __name__ == "__main__":
    main()