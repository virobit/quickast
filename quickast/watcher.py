"""File watcher — monitors the project for changes and re-indexes automatically."""

import os
import signal
import sys
import time
from pathlib import Path
from threading import Lock, Timer

from .indexer import Indexer


DEFAULT_DEBOUNCE = 2.0


class IndexEventHandler:
    """Debounced file change handler for the watcher."""

    def __init__(self, indexer: Indexer, debounce: float = DEFAULT_DEBOUNCE):
        self.indexer = indexer
        self._debounce = debounce
        self._debounce_timers: dict[str, Timer] = {}
        self._index_lock = Lock()

    def _should_process(self, path: str) -> bool:
        if not path.endswith(".py"):
            return False
        return not self.indexer.should_skip(Path(path))

    def _debounced_index(self, filepath: str):
        if filepath in self._debounce_timers:
            self._debounce_timers[filepath].cancel()

        def do_index():
            with self._index_lock:
                try:
                    p = Path(filepath)
                    if p.exists():
                        if self.indexer.index_file(p):
                            rel = p.relative_to(self.indexer.project_root)
                            print(f"  Reindexed: {rel}")
                    else:
                        self.indexer.remove_file(p)
                        rel = filepath.replace(str(self.indexer.project_root) + "/", "")
                        print(f"  Removed: {rel}")
                except Exception as e:
                    print(f"  Index error for {filepath}: {e}", file=sys.stderr)
                finally:
                    self._debounce_timers.pop(filepath, None)

        timer = Timer(self._debounce, do_index)
        self._debounce_timers[filepath] = timer
        timer.start()

    def dispatch(self, event):
        if event.is_directory:
            return
        path = getattr(event, "src_path", "")
        if event.event_type == "moved":
            if self._should_process(path):
                self._debounced_index(path)
            dest = getattr(event, "dest_path", "")
            if self._should_process(dest):
                self._debounced_index(dest)
        elif self._should_process(path):
            self._debounced_index(path)


def _daemonize(project_root: Path):
    """Fork to background as a daemon process. Prints PID before parent exits."""
    child_pid = os.fork()
    if child_pid > 0:
        # Parent — print the daemon PID and exit
        print(f"Watcher daemon started (PID {child_pid}). Use 'quickast stop' to stop.")
        os._exit(0)
    os.setsid()
    if os.fork() > 0:
        os._exit(0)
    sys.stdout.flush()
    sys.stderr.flush()
    devnull = open(os.devnull, "w")
    sys.stdout = devnull
    sys.stderr = devnull


def start_watcher(project_root: Path, db_path: Path | None = None,
                   daemon: bool = False, debounce: float = DEFAULT_DEBOUNCE,
                   nice: bool = False):
    """Start the file watcher. If daemon=True, forks to background."""
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError:
        print("Error: watchdog is required for file watching.", file=sys.stderr)
        print("Install it with: pip install quickast", file=sys.stderr)
        sys.exit(1)

    if daemon:
        _daemonize(project_root)

    if nice:
        os.nice(10)

    indexer = Indexer(project_root, db_path=db_path)

    if not daemon:
        print("Running incremental scan...")
    stats = indexer.build()
    if not daemon:
        print(f"  Scan complete: {stats['indexed']} updated, "
              f"{stats['skipped']} unchanged, {stats['removed']} removed")

    handler = IndexEventHandler(indexer, debounce=debounce)

    class WatchdogAdapter(FileSystemEventHandler):
        def on_any_event(self, event):
            handler.dispatch(event)

    observer = Observer()
    observer.schedule(WatchdogAdapter(), str(project_root), recursive=True)
    observer.start()

    pid_file = project_root / ".quickast.pid"
    pid_file.write_text(str(os.getpid()))

    if not daemon:
        print(f"Watching {project_root} for Python file changes (PID {os.getpid()})...")

    running = True

    def shutdown(signum, frame):
        nonlocal running
        print("\nShutting down watcher...")
        running = False

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    try:
        while running:
            time.sleep(1)
    finally:
        observer.stop()
        observer.join()
        pid_file.unlink(missing_ok=True)
        print("Watcher stopped.")
