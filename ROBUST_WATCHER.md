# Robust NFS Watcher

This enhanced file watcher addresses common issues with NFS file change detection by combining multiple detection strategies.

## The Problem with NFS Watching

Standard filesystem event watchers (like inotify) can miss changes on NFS shares due to:
- Network latency causing delayed notifications
- NFS client caching masking immediate changes  
- Lost events during network interruptions
- Different NFS protocol versions having varying event reliability

## Our Solution: Hybrid Detection

The robust watcher uses a multi-layered approach:

### 1. **Polling Observer** (Primary)
- Uses watchdog's PollingObserver for basic change detection
- More reliable than inotify for NFS shares
- Configurable poll interval (default: 5 seconds)

### 2. **Periodic Full Scans** (Backup)
- SHA256 checksum comparison to catch missed changes
- Scans entire directory tree at intervals (default: 5 minutes)  
- Detects file additions, modifications, and deletions
- SQLite database tracks file states between scans

### 3. **Intelligent Debouncing**
- Prevents excessive reindex calls during batch operations
- Configurable debounce period (default: 60 seconds)
- Per-file stability checking before processing

### 4. **State Persistence**
- SQLite database tracks processed files and their checksums
- Survives container restarts and temporary outages
- Automatic cleanup of deleted files from tracking

## Features

- **Checksum-based change detection** - Catches content changes missed by timestamps
- **Robust error handling** - Continues working despite temporary NFS issues
- **Comprehensive logging** - Detailed stats and monitoring information
- **Configurable intervals** - Tune for your NFS environment
- **File type filtering** - Only processes configured extensions
- **Automatic retry logic** - Resilient to temporary API failures
- **Statistics tracking** - Monitor detection efficiency

## Configuration

### Basic Usage
```bash
./scripts/manage_watcher.sh start
```

### Environment-Specific Settings

Edit `watcher_config.env` for your NFS setup:

```bash
# For busy NFS shares with lots of changes
DEBOUNCE=120
POLL_INTERVAL=10  
SCAN_INTERVAL=600

# For slow/high-latency NFS over WAN
DEBOUNCE=180
POLL_INTERVAL=15
SCAN_INTERVAL=900

# For fast local NFS
DEBOUNCE=30
POLL_INTERVAL=2
SCAN_INTERVAL=150
```

### Manual Configuration
```bash
./scripts/robust_nfs_watcher.py \
  --watch-dir /path/to/docs \
  --endpoint http://localhost:8000/reindex \
  --debounce 60 \
  --poll-interval 5 \
  --scan-interval 300 \
  --db-path /path/to/watcher.db
```

## Management Commands

```bash
# Start the robust watcher
./scripts/manage_watcher.sh start

# Stop all watchers  
./scripts/manage_watcher.sh stop

# Restart watcher
./scripts/manage_watcher.sh restart

# Check status
./scripts/manage_watcher.sh status

# View live logs
./scripts/manage_watcher.sh logs

# Show statistics
./scripts/manage_watcher.sh stats

# Test original watcher for comparison
./scripts/manage_watcher.sh test-original
```

## Monitoring

The watcher provides detailed logging:

```
2025-10-27 15:30:00 INFO Starting periodic scan of /app/markdown_files
2025-10-27 15:30:01 INFO Scan detected change in: /app/markdown_files/new_doc.md  
2025-10-27 15:30:01 INFO Triggering reindex: periodic_scan (file: /app/markdown_files/new_doc.md)
2025-10-27 15:30:02 INFO Reindex request succeeded (status=200)
2025-10-27 15:30:05 INFO Periodic scan completed in 5.23s - 76 files checked, 1 changes
2025-10-27 15:35:00 INFO Watcher stats: polling_events=5, scan_events=1, successful_triggers=1, failed_triggers=0, files_processed=77
```

## Database Schema

The SQLite database tracks:
- File path, size, modification time
- SHA256 checksum for content verification  
- Last processing timestamp
- Processing attempt count
- Creation and update timestamps

## Performance Considerations

### Memory Usage
- Minimal: ~10-20MB for tracking 1000+ files
- Checksums calculated on-demand, not stored in memory
- SQLite database provides efficient state persistence

### CPU Usage  
- Low baseline load from polling
- Periodic CPU spikes during full scans (every 5min by default)
- Checksum calculation scales with file sizes

### Network Impact
- One HTTP POST per detected change batch (debounced)
- No continuous API polling 
- Robust retry logic with exponential backoff

## Troubleshooting

### High False Positives
If too many unnecessary reindexes:
- Increase debounce period
- Increase scan interval  
- Check for timestamp issues on NFS

### Missed Changes
If changes not being detected:
- Decrease poll interval
- Decrease scan interval
- Check NFS mount options (noac, etc.)
- Verify file permissions

### Performance Issues
If watcher using too many resources:
- Increase scan interval
- Exclude large binary files
- Limit file extensions watched

## Comparison with Original Watcher

| Feature | Original Watcher | Robust Watcher |
|---------|------------------|----------------|
| Detection Method | Polling only | Polling + checksums |
| Missed Changes | Possible | Very unlikely |
| State Persistence | None | SQLite database |
| Change Verification | Timestamp/size | SHA256 checksums |
| Deleted File Detection | Limited | Full tracking |  
| Statistics | Basic | Comprehensive |
| Recovery | Manual | Automatic |

## Migration

To switch from the original watcher:

1. Stop current watcher: `./scripts/manage_watcher.sh stop`
2. The robust watcher is now the default
3. Start new watcher: `./scripts/manage_watcher.sh start`
4. Monitor initial scan: `./scripts/manage_watcher.sh logs`

The initial scan will process all existing files and establish baseline state.

## Future Enhancements

Potential improvements:
- Webhook integration for real-time notifications
- Distributed watcher coordination for multiple NFS clients
- Integration with NFS server-side change logs
- Machine learning for optimal interval tuning
- Grafana dashboard for monitoring metrics