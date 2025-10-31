#!/usr/bin/env python3
"""
Intelligent filesystem watcher that performs incremental indexing operations.

This watcher analyzes file system events and calls appropriate endpoints:
- File created/modified -> POST /index_file (incremental update)
- File deleted -> POST /delete_file (remove from index)
- Only falls back to full reindex for bulk operations or errors

Key improvements over the basic watcher:
- Event-specific operations (add/update/delete instead of full reindex)
- File extension filtering before making API calls
- Better event handling for move operations
- Configurable fallback to full reindex for bulk changes
"""
import time
import argparse
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Set, Optional
import requests
import json

try:
    from watchdog.events import (
        FileSystemEventHandler, 
        FileSystemEvent,
        FileCreatedEvent,
        FileModifiedEvent, 
        FileDeletedEvent,
        FileMovedEvent,
        DirCreatedEvent,
        DirModifiedEvent,
        DirDeletedEvent,
        DirMovedEvent
    )
    from watchdog.observers.polling import PollingObserver
except Exception as e:
    print("Missing dependency 'watchdog'. Install: pip install watchdog requests", file=sys.stderr)
    raise

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("smart_watcher")


class IntelligentHandler(FileSystemEventHandler):
    """Smart event handler that performs incremental operations."""
    
    def __init__(self, 
                 base_url: str,
                 watch_dir: Path,
                 allowed_extensions: Set[str],
                 debounce_seconds: int = 5,
                 wait_stable: int = 2,
                 bulk_threshold: int = 10,
                 verify: bool = True):
        super().__init__()
        self.base_url = base_url.rstrip('/')
        self.watch_dir = watch_dir
        self.allowed_extensions = allowed_extensions
        self.debounce_seconds = debounce_seconds
        self.wait_stable = wait_stable
        self.bulk_threshold = bulk_threshold
        self.verify = verify
        
        # Event tracking
        self._lock = threading.Lock()
        self._pending_events: Set[str] = set()  # Track pending files
        self._event_timer: Optional[threading.Timer] = None
        
    def _is_allowed_file(self, file_path: Path) -> bool:
        """Check if file has an allowed extension."""
        return file_path.suffix.lower() in self.allowed_extensions
    
    def _get_relative_path(self, absolute_path: str) -> str:
        """Convert absolute path to relative path within watch directory."""
        try:
            path = Path(absolute_path)
            return str(path.relative_to(self.watch_dir))
        except ValueError:
            # Path is not within watch directory
            return str(Path(absolute_path).name)
    
    def _wait_for_stable(self, path: str, timeout: int = 300) -> bool:
        """Wait for file to be stable (size unchanged)."""
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
    
    def _make_request(self, endpoint: str, payload: dict, operation_name: str) -> bool:
        """Make HTTP request with retry logic."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        max_attempts = 3
        backoff = 1
        
        for attempt in range(1, max_attempts + 1):
            try:
                response = requests.post(
                    url, 
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=120,
                    verify=self.verify
                )
                
                if response.ok:
                    result = response.json()
                    logger.info(f"{operation_name} succeeded: {result.get('message', 'OK')}")
                    return True
                else:
                    logger.warning(f"{operation_name} returned status {response.status_code}: {response.text[:200]}")
                    
            except requests.exceptions.RequestException as e:
                logger.warning(f"{operation_name} attempt {attempt} failed: {e}")
                
            if attempt < max_attempts:
                time.sleep(backoff)
                backoff *= 2
                
        logger.error(f"All attempts failed for {operation_name}")
        return False
    
    def _process_file_event(self, file_path: str, event_type: str):
        """Process a single file event."""
        path = Path(file_path)
        
        # Skip non-allowed files
        if not self._is_allowed_file(path):
            logger.debug(f"Skipping {file_path} - not an allowed file type")
            return
            
        relative_path = self._get_relative_path(file_path)
        
        if event_type in ["created", "modified"]:
            # Wait for file to be stable before indexing
            if not self._wait_for_stable(file_path):
                logger.warning(f"File not stable, skipping: {file_path}")
                return
                
            # Index or update the file
            success = self._make_request(
                "index_file",
                {"file_path": relative_path},
                f"Index file {relative_path}"
            )
            
            if not success:
                logger.warning(f"Failed to index {relative_path}, triggering full reindex")
                self._trigger_full_reindex()
                
        elif event_type == "deleted":
            # Remove from index
            success = self._make_request(
                "delete_file", 
                {"file_path": relative_path},
                f"Delete file {relative_path}"
            )
            
            if not success:
                logger.warning(f"Failed to delete {relative_path} from index")
    
    def _trigger_full_reindex(self):
        """Trigger a full reindex as fallback."""
        logger.info("Triggering full reindex")
        self._make_request(
            "reindex",
            {},
            "Full reindex"
        )
    
    def _schedule_batch_processing(self):
        """Schedule batch processing of pending events."""
        with self._lock:
            if self._event_timer:
                self._event_timer.cancel()
            
            self._event_timer = threading.Timer(
                self.debounce_seconds,
                self._process_pending_events
            )
            self._event_timer.start()
    
    def _process_pending_events(self):
        """Process all pending events."""
        with self._lock:
            pending = self._pending_events.copy()
            self._pending_events.clear()
            self._event_timer = None
        
        if not pending:
            return
            
        logger.info(f"Processing {len(pending)} pending events")
        
        # If too many events, do a full reindex
        if len(pending) > self.bulk_threshold:
            logger.info(f"Bulk operation detected ({len(pending)} files), triggering full reindex")
            self._trigger_full_reindex()
            return
        
        # Process individual events
        for event_info in pending:
            try:
                file_path, event_type = event_info.split("::", 1)
                self._process_file_event(file_path, event_type)
            except Exception as e:
                logger.error(f"Error processing event {event_info}: {e}")
    
    def _add_event(self, file_path: str, event_type: str):
        """Add an event to the pending queue."""
        path = Path(file_path)
        
        # Only process files, not directories
        if path.is_dir():
            return
            
        # Skip if not an allowed file type
        if not self._is_allowed_file(path):
            return
            
        event_info = f"{file_path}::{event_type}"
        
        with self._lock:
            self._pending_events.add(event_info)
            
        self._schedule_batch_processing()
    
    # Event handlers
    def on_created(self, event: FileSystemEvent):
        if not event.is_directory:
            logger.debug(f"File created: {event.src_path}")
            self._add_event(event.src_path, "created")
    
    def on_modified(self, event: FileSystemEvent):
        if not event.is_directory:
            logger.debug(f"File modified: {event.src_path}")
            self._add_event(event.src_path, "modified")
    
    def on_deleted(self, event: FileSystemEvent):
        if not event.is_directory:
            logger.debug(f"File deleted: {event.src_path}")
            self._add_event(event.src_path, "deleted")
    
    def on_moved(self, event: FileSystemEvent):
        if not event.is_directory:
            logger.debug(f"File moved: {event.src_path} -> {event.dest_path}")
            # Treat move as delete old + create new
            self._add_event(event.src_path, "deleted")
            self._add_event(event.dest_path, "created")


def parse_extensions(ext_string: str) -> Set[str]:
    """Parse comma-separated extension list."""
    if not ext_string:
        return {".md", ".markdown", ".txt", ".pdf", ".docx", ".pptx", ".html", ".htm", ".csv", 
                ".png", ".jpg", ".jpeg", ".tiff", ".tif"}
    
    extensions = set()
    for ext in ext_string.split(","):
        ext = ext.strip()
        if ext and not ext.startswith("."):
            ext = "." + ext
        if ext:
            extensions.add(ext.lower())
    return extensions


def wait_for_health(health_url: str, timeout: int = 60, verify: bool = True) -> bool:
    """Wait for health endpoint to be available."""
    start = time.time()
    backoff = 1
    
    while time.time() - start < timeout:
        try:
            response = requests.get(health_url, timeout=5, verify=verify)
            if response.ok:
                logger.info("Health check passed")
                return True
        except Exception as e:
            logger.debug(f"Health check failed: {e}")
            
        time.sleep(backoff)
        backoff = min(backoff * 2, 5)
    
    logger.warning(f"Health check timed out after {timeout}s")
    return False


def main():
    parser = argparse.ArgumentParser(description="Intelligent filesystem watcher for RAG indexing")
    parser.add_argument("--watch-dir", required=True, help="Directory to watch")
    parser.add_argument("--base-url", default="http://localhost:8000", 
                       help="Base URL of the API (e.g., https://rag.example.com)")
    parser.add_argument("--allowed-extensions", default="", 
                       help="Comma-separated list of allowed file extensions (e.g., md,txt,pdf)")
    parser.add_argument("--debounce", type=int, default=5, 
                       help="Seconds to debounce events before processing")
    parser.add_argument("--poll-interval", type=int, default=5, 
                       help="Polling interval for filesystem observer")
    parser.add_argument("--wait-stable", type=int, default=2,
                       help="Seconds file must be stable before processing")
    parser.add_argument("--bulk-threshold", type=int, default=10,
                       help="Number of files that triggers full reindex instead of incremental")
    parser.add_argument("--insecure", action="store_true", 
                       help="Disable TLS verification")
    
    args = parser.parse_args()
    
    # Validate watch directory
    watch_dir = Path(args.watch_dir).resolve()
    if not watch_dir.exists() or not watch_dir.is_dir():
        logger.error(f"Watch directory does not exist: {watch_dir}")
        return 1
    
    # Parse configuration
    base_url = args.base_url.rstrip('/')
    allowed_extensions = parse_extensions(args.allowed_extensions)
    verify = not args.insecure
    
    logger.info(f"Starting intelligent watcher")
    logger.info(f"  Watch directory: {watch_dir}")
    logger.info(f"  API base URL: {base_url}")
    logger.info(f"  Allowed extensions: {sorted(allowed_extensions)}")
    logger.info(f"  Debounce: {args.debounce}s")
    logger.info(f"  Bulk threshold: {args.bulk_threshold} files")
    
    # Wait for API to be ready
    health_url = f"{base_url}/health"
    if not wait_for_health(health_url, verify=verify):
        logger.error("API health check failed, starting anyway...")
    
    # Set up observer
    observer = PollingObserver(timeout=args.poll_interval)
    handler = IntelligentHandler(
        base_url=base_url,
        watch_dir=watch_dir,
        allowed_extensions=allowed_extensions,
        debounce_seconds=args.debounce,
        wait_stable=args.wait_stable,
        bulk_threshold=args.bulk_threshold,
        verify=verify
    )
    
    observer.schedule(handler, str(watch_dir), recursive=True)
    
    try:
        observer.start()
        logger.info("Watcher started successfully")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stopping watcher...")
    finally:
        observer.stop()
        observer.join()
        logger.info("Watcher stopped")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())