#!/usr/bin/env python3
"""
Enhanced NFS-robust watcher that combines polling with checksum-based change detection.

Features:
- Hybrid approach: filesystem polling + periodic full scans
- SHA256 checksums to detect content changes missed by polling
- SQLite database to track processed files and their states
- Configurable scan intervals and retry logic
- Enhanced logging and monitoring
- Graceful handling of NFS temporary unavailability
"""
import time
import argparse
import logging
import os
import sys
import threading
import sqlite3
import hashlib
import json
from pathlib import Path
from typing import Dict, Set, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
import requests

try:
    from watchdog.events import FileSystemEventHandler, FileSystemEvent
    from watchdog.observers.polling import PollingObserver
except Exception as e:
    print("Missing dependency 'watchdog'. Install: pip install watchdog requests", file=sys.stderr)
    raise

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("robust_watcher")

@dataclass
class FileState:
    """Represents the state of a file for change detection."""
    path: str
    size: int
    mtime: float
    checksum: str
    last_processed: datetime
    processing_attempts: int = 0

class FileStateDB:
    """SQLite database to track file states."""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.lock = threading.Lock()
        self._init_db()
    
    def _init_db(self):
        """Initialize the database schema."""
        with self.lock:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS file_states (
                    path TEXT PRIMARY KEY,
                    size INTEGER,
                    mtime REAL,
                    checksum TEXT,
                    last_processed TEXT,
                    processing_attempts INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self.conn.commit()
    
    def get_file_state(self, path: str) -> Optional[FileState]:
        """Get the stored state for a file."""
        with self.lock:
            cursor = self.conn.execute(
                "SELECT path, size, mtime, checksum, last_processed, processing_attempts FROM file_states WHERE path = ?",
                (path,)
            )
            row = cursor.fetchone()
            if row:
                return FileState(
                    path=row[0],
                    size=row[1], 
                    mtime=row[2],
                    checksum=row[3],
                    last_processed=datetime.fromisoformat(row[4]),
                    processing_attempts=row[5]
                )
            return None
    
    def update_file_state(self, state: FileState):
        """Update or insert a file state."""
        with self.lock:
            self.conn.execute("""
                INSERT OR REPLACE INTO file_states 
                (path, size, mtime, checksum, last_processed, processing_attempts, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                state.path,
                state.size,
                state.mtime, 
                state.checksum,
                state.last_processed.isoformat(),
                state.processing_attempts,
                datetime.now().isoformat()
            ))
            self.conn.commit()
    
    def get_all_tracked_files(self) -> Set[str]:
        """Get all file paths currently tracked in the database."""
        with self.lock:
            cursor = self.conn.execute("SELECT path FROM file_states")
            return {row[0] for row in cursor.fetchall()}
    
    def remove_file(self, path: str):
        """Remove a file from tracking (when deleted)."""
        with self.lock:
            self.conn.execute("DELETE FROM file_states WHERE path = ?", (path,))
            self.conn.commit()

class RobustNFSWatcher:
    """Enhanced file watcher with multiple detection strategies."""
    
    def __init__(self, watch_dir: str, endpoint: str, db_path: str = None, 
                 debounce_seconds: int = 60, poll_interval: int = 5,
                 scan_interval: int = 300, verify: bool = True,
                 allowed_extensions: list = None):
        self.watch_dir = Path(watch_dir).resolve()
        self.endpoint = endpoint
        self.debounce_seconds = debounce_seconds
        self.poll_interval = poll_interval
        self.scan_interval = scan_interval
        self.verify = verify
        self.allowed_extensions = allowed_extensions or [
            '.md', '.markdown', '.pdf', '.docx', '.pptx', '.html', '.htm',
            '.txt', '.csv', '.png', '.jpg', '.jpeg', '.tiff', '.tif'
        ]
        
        # Database for state tracking
        db_path = db_path or str(self.watch_dir / ".watcher_state.db")
        self.db = FileStateDB(db_path)
        
        # Control flags
        self.running = False
        self.last_scan = 0
        self.last_trigger = 0
        self.trigger_lock = threading.Lock()
        
        # Statistics
        self.stats = {
            'polling_events': 0,
            'scan_events': 0,
            'successful_triggers': 0,
            'failed_triggers': 0,
            'files_processed': 0
        }
    
    def _should_process_file(self, file_path: Path) -> bool:
        """Check if a file should be processed based on extension and other criteria."""
        if file_path.is_dir():
            return False
        
        # Check extension
        if file_path.suffix.lower() not in self.allowed_extensions:
            return False
        
        # Skip hidden files and system files
        if file_path.name.startswith('.') or file_path.name.startswith('~'):
            return False
            
        # Skip files that are too small (likely empty or corrupted)
        try:
            if file_path.stat().st_size < 10:  # Less than 10 bytes
                return False
        except OSError:
            return False
            
        return True
    
    def _calculate_checksum(self, file_path: Path) -> Optional[str]:
        """Calculate SHA256 checksum of a file."""
        try:
            hasher = hashlib.sha256()
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except OSError as e:
            logger.warning("Failed to calculate checksum for %s: %s", file_path, e)
            return None
    
    def _get_current_file_state(self, file_path: Path) -> Optional[FileState]:
        """Get the current state of a file from the filesystem."""
        try:
            stat = file_path.stat()
            checksum = self._calculate_checksum(file_path)
            if checksum is None:
                return None
                
            return FileState(
                path=str(file_path),
                size=stat.st_size,
                mtime=stat.st_mtime,
                checksum=checksum,
                last_processed=datetime.now()
            )
        except OSError as e:
            logger.debug("Failed to get file state for %s: %s", file_path, e)
            return None
    
    def _has_file_changed(self, file_path: Path) -> bool:
        """Check if a file has changed since last processing."""
        current_state = self._get_current_file_state(file_path)
        if current_state is None:
            return False
            
        stored_state = self.db.get_file_state(str(file_path))
        if stored_state is None:
            # New file
            return True
        
        # Check if file has changed (size, mtime, or checksum)
        if (current_state.size != stored_state.size or 
            current_state.mtime != stored_state.mtime or 
            current_state.checksum != stored_state.checksum):
            return True
            
        return False
    
    def _wait_for_file_stable(self, file_path: Path, timeout: int = 300) -> bool:
        """Wait for a file to become stable (not changing)."""
        if not file_path.exists():
            return False
            
        stable_checks = 3  # Number of consecutive stable checks required
        check_interval = 1  # Seconds between checks
        
        last_state = None
        stable_count = 0
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                current_state = self._get_current_file_state(file_path)
                if current_state is None:
                    time.sleep(check_interval)
                    continue
                    
                if last_state and (current_state.size == last_state.size and 
                                 current_state.mtime == last_state.mtime):
                    stable_count += 1
                    if stable_count >= stable_checks:
                        return True
                else:
                    stable_count = 0
                    
                last_state = current_state
                time.sleep(check_interval)
                
            except OSError:
                time.sleep(check_interval)
                continue
        
        logger.warning("File did not stabilize within timeout: %s", file_path)
        return False
    
    def _should_trigger_reindex(self) -> bool:
        """Check if we should trigger reindex (debounce logic)."""
        now = time.time()
        with self.trigger_lock:
            if now - self.last_trigger < self.debounce_seconds:
                logger.debug("Debounce: last trigger was %.1fs ago", now - self.last_trigger)
                return False
            self.last_trigger = now
        return True
    
    def _trigger_reindex(self, trigger_reason: str, file_path: str = None):
        """Trigger the reindex endpoint."""
        if not self._should_trigger_reindex():
            return
            
        logger.info("Triggering reindex: %s %s", trigger_reason, 
                   f"(file: {file_path})" if file_path else "")
        
        success = self._call_endpoint()
        if success:
            self.stats['successful_triggers'] += 1
        else:
            self.stats['failed_triggers'] += 1
    
    def _call_endpoint(self, max_attempts: int = 3) -> bool:
        """Call the reindex endpoint with retry logic."""
        attempt = 0
        backoff = 1
        
        while attempt < max_attempts:
            attempt += 1
            try:
                # Use /reindex instead of /index for full reindex
                endpoint = self.endpoint.replace('/index', '/reindex')
                resp = requests.post(endpoint, json={}, timeout=120, verify=self.verify)
                
                if resp.ok:
                    logger.info("Reindex request succeeded (status=%s)", resp.status_code)
                    return True
                else:
                    logger.warning("Reindex request returned status=%s: %s", 
                                 resp.status_code, resp.text[:200])
            except requests.exceptions.RequestException as e:
                logger.warning("Reindex request attempt %d failed: %s", attempt, e)
            
            if attempt < max_attempts:
                time.sleep(backoff)
                backoff *= 2
        
        logger.error("All attempts to call reindex endpoint failed")
        return False
    
    def _periodic_scan(self):
        """Perform a periodic full scan of the directory."""
        logger.info("Starting periodic scan of %s", self.watch_dir)
        scan_start = time.time()
        
        try:
            # Get all current files
            current_files = set()
            changed_files = []
            
            for file_path in self.watch_dir.rglob('*'):
                if not self._should_process_file(file_path):
                    continue
                
                current_files.add(str(file_path))
                
                if self._has_file_changed(file_path):
                    logger.info("Scan detected change in: %s", file_path)
                    changed_files.append(file_path)
                    self.stats['scan_events'] += 1
                    
                    # Update the file state
                    current_state = self._get_current_file_state(file_path)
                    if current_state:
                        self.db.update_file_state(current_state)
                        self.stats['files_processed'] += 1
            
            # Check for deleted files
            tracked_files = self.db.get_all_tracked_files()
            deleted_files = tracked_files - current_files
            
            for deleted_path in deleted_files:
                logger.info("Scan detected deleted file: %s", deleted_path)
                self.db.remove_file(deleted_path)
                changed_files.append(Path(deleted_path))
            
            # If any changes detected, trigger reindex
            if changed_files:
                self._trigger_reindex("periodic_scan", f"{len(changed_files)} files changed")
            
            scan_duration = time.time() - scan_start
            logger.info("Periodic scan completed in %.2fs - %d files checked, %d changes", 
                       scan_duration, len(current_files), len(changed_files))
            
        except Exception as e:
            logger.error("Error during periodic scan: %s", e)
    
    def _scan_thread(self):
        """Background thread for periodic scanning."""
        while self.running:
            try:
                time.sleep(self.scan_interval)
                if self.running:  # Check again after sleep
                    self._periodic_scan()
            except Exception as e:
                logger.error("Error in scan thread: %s", e)
                time.sleep(60)  # Wait before retrying
    
    def _log_stats(self):
        """Log current statistics."""
        logger.info("Watcher stats: polling_events=%d, scan_events=%d, "
                   "successful_triggers=%d, failed_triggers=%d, files_processed=%d",
                   self.stats['polling_events'], self.stats['scan_events'],
                   self.stats['successful_triggers'], self.stats['failed_triggers'],
                   self.stats['files_processed'])
    
    def start(self):
        """Start the watcher with both polling and scanning."""
        if not self.watch_dir.exists():
            raise ValueError(f"Watch directory does not exist: {self.watch_dir}")
        
        logger.info("Starting robust NFS watcher on %s", self.watch_dir)
        logger.info("Config: debounce=%ds, poll_interval=%ds, scan_interval=%ds", 
                   self.debounce_seconds, self.poll_interval, self.scan_interval)
        
        self.running = True
        
        # Start periodic scanning thread
        scan_thread = threading.Thread(target=self._scan_thread, daemon=True)
        scan_thread.start()
        
        # Start watchdog polling observer as backup
        observer = PollingObserver(timeout=self.poll_interval)
        handler = PollingEventHandler(self)
        observer.schedule(handler, str(self.watch_dir), recursive=True)
        
        # Start stats logging thread
        stats_thread = threading.Thread(target=self._stats_thread, daemon=True)
        stats_thread.start()
        
        try:
            # Initial scan
            self._periodic_scan()
            
            observer.start()
            logger.info("Watcher started successfully")
            
            while self.running:
                time.sleep(1)
                
        except KeyboardInterrupt:
            logger.info("Stopping watcher (KeyboardInterrupt)")
        finally:
            self.running = False
            observer.stop()
            observer.join()
    
    def _stats_thread(self):
        """Background thread for periodic stats logging."""
        while self.running:
            time.sleep(300)  # Log stats every 5 minutes
            if self.running:
                self._log_stats()

class PollingEventHandler(FileSystemEventHandler):
    """Event handler for the polling observer."""
    
    def __init__(self, watcher: RobustNFSWatcher):
        super().__init__()
        self.watcher = watcher
    
    def on_any_event(self, event: FileSystemEvent):
        """Handle any filesystem event."""
        if event.is_directory:
            return
            
        file_path = Path(event.src_path)
        
        if not self.watcher._should_process_file(file_path):
            return
        
        logger.debug("Polling event: %s on %s", event.event_type, file_path)
        self.watcher.stats['polling_events'] += 1
        
        # Wait for file to stabilize before processing
        if self.watcher._wait_for_file_stable(file_path):
            if self.watcher._has_file_changed(file_path):
                logger.info("Polling detected change in: %s", file_path)
                
                # Update file state
                current_state = self.watcher._get_current_file_state(file_path)
                if current_state:
                    self.watcher.db.update_file_state(current_state)
                    self.watcher.stats['files_processed'] += 1
                
                # Trigger reindex
                self.watcher._trigger_reindex("polling_event", str(file_path))

def wait_for_health(endpoint_health: str, timeout: int = 60, verify: bool = True):
    """Poll a health URL until it returns 200 or timeout."""
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
    parser = argparse.ArgumentParser(description="Robust NFS file watcher with checksums")
    parser.add_argument("--watch-dir", required=True, help="Directory to watch")
    parser.add_argument("--endpoint", default="http://localhost:8000/index", 
                       help="Index endpoint to POST to")
    parser.add_argument("--db-path", help="Path to SQLite state database (default: <watch-dir>/.watcher_state.db)")
    parser.add_argument("--debounce", type=int, default=60, 
                       help="Seconds to debounce index calls")
    parser.add_argument("--poll-interval", type=int, default=5, 
                       help="Polling interval for filesystem events (seconds)")
    parser.add_argument("--scan-interval", type=int, default=300,
                       help="Interval for full directory scans (seconds)")
    parser.add_argument("--insecure", action="store_true", 
                       help="Disable TLS verification (not recommended)")
    parser.add_argument("--allowed-extensions", nargs="*",
                       default=['.md', '.markdown', '.pdf', '.docx', '.pptx', 
                               '.html', '.htm', '.txt', '.csv', '.png', '.jpg', 
                               '.jpeg', '.tiff', '.tif'],
                       help="File extensions to watch")
    
    args = parser.parse_args()
    
    # Validate watch directory
    watch_dir = Path(args.watch_dir).resolve()
    if not watch_dir.exists() or not watch_dir.is_dir():
        logger.error("Watch directory does not exist: %s", watch_dir)
        sys.exit(2)
    
    verify = not args.insecure
    
    # Wait for API health
    health_url = args.endpoint.replace("/index", "/health")
    wait_for_health(health_url, timeout=60, verify=verify)
    
    # Create and start watcher
    watcher = RobustNFSWatcher(
        watch_dir=str(watch_dir),
        endpoint=args.endpoint,
        db_path=args.db_path,
        debounce_seconds=args.debounce,
        poll_interval=args.poll_interval,
        scan_interval=args.scan_interval,
        verify=verify,
        allowed_extensions=args.allowed_extensions
    )
    
    watcher.start()

if __name__ == "__main__":
    main()