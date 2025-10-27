#!/bin/bash
# Watcher management utility

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

usage() {
    echo "Usage: $0 {start|stop|restart|status|logs|stats|test-original|test-robust}"
    echo ""
    echo "Commands:"
    echo "  start         - Start the robust watcher"
    echo "  stop          - Stop all watchers"
    echo "  restart       - Restart the robust watcher"
    echo "  status        - Show watcher container status"
    echo "  logs          - Show watcher logs"
    echo "  stats         - Show watcher statistics from logs"
    echo "  test-original - Test with the original watcher"
    echo "  test-robust   - Test with the robust watcher (default)"
    exit 1
}

start_watcher() {
    echo "Starting robust NFS watcher..."
    cd "$PROJECT_DIR"
    docker compose up watcher -d
    echo "Watcher started. Use '$0 logs' to see output."
}

stop_watcher() {
    echo "Stopping all watchers..."
    cd "$PROJECT_DIR"
    docker compose stop watcher watcher-original 2>/dev/null || true
    echo "Watchers stopped."
}

restart_watcher() {
    stop_watcher
    sleep 2
    start_watcher
}

show_status() {
    echo "Watcher container status:"
    cd "$PROJECT_DIR"
    docker compose ps watcher watcher-original 2>/dev/null || echo "No watcher containers found."
}

show_logs() {
    cd "$PROJECT_DIR"
    echo "Watcher logs (press Ctrl+C to exit):"
    docker compose logs -f watcher 2>/dev/null || echo "No watcher logs available."
}

show_stats() {
    cd "$PROJECT_DIR"
    echo "Extracting watcher statistics from logs..."
    docker compose logs watcher 2>/dev/null | grep -E "(stats|Watcher stats|scan completed|changes|triggered)" | tail -20
}

test_original() {
    echo "Starting original watcher for testing..."
    cd "$PROJECT_DIR"
    docker compose --profile original-watcher up watcher-original -d
    echo "Original watcher started. Use 'docker compose logs watcher-original' to see output."
}

test_robust() {
    echo "Starting robust watcher for testing..."
    start_watcher
}

case "${1:-}" in
    start)
        start_watcher
        ;;
    stop)
        stop_watcher
        ;;
    restart)
        restart_watcher
        ;;
    status)
        show_status
        ;;
    logs)
        show_logs
        ;;
    stats)
        show_stats
        ;;
    test-original)
        test_original
        ;;
    test-robust)
        test_robust
        ;;
    *)
        usage
        ;;
esac