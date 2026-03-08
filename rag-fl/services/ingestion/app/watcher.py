"""
services/ingestion/app/watcher.py
Folder watcher for /input directory — dev mode only (ENVIRONMENT=development).
Uses watchdog to detect new files, then triggers the ingest pipeline.
Runs as a background thread started at FastAPI startup.
"""
import logging
import os
import time
import threading
import httpx
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent

logger = logging.getLogger("ingestion.watcher")

# Files currently being processed — prevents double-ingestion
_in_flight: set[str] = set()
_lock = threading.Lock()

WATCH_DIR = "/input"
INGEST_URL = os.getenv("INGEST_URL", "http://localhost:8001/ingest")
SETTLE_SECONDS = 2  # wait after creation before reading (file might still be copying)
SUPPORTED_EXTENSIONS = {".pdf", ".xlsx", ".xls", ".pptx", ".docx", ".yaml", ".yml", ".jpg", ".jpeg", ".png"}


class IngestOnCreate(FileSystemEventHandler):

    def on_created(self, event: FileCreatedEvent):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            logger.debug(f"Watcher ignoring unsupported extension: {path.name}")
            return

        with _lock:
            if str(path) in _in_flight:
                return
            _in_flight.add(str(path))

        logger.info(f"Watcher detected: {path.name}, triggering ingestion in {SETTLE_SECONDS}s")
        threading.Thread(target=_ingest_after_settle, args=(path,), daemon=True).start()


def _ingest_after_settle(path: Path):
    try:
        time.sleep(SETTLE_SECONDS)
        if not path.exists():
            logger.warning(f"Watcher: file disappeared before ingestion: {path.name}")
            return

        logger.info(f"Watcher ingesting: {path.name}")
        with open(path, "rb") as f:
            file_bytes = f.read()

        with httpx.Client(timeout=120) as client:
            response = client.post(
                INGEST_URL,
                files={"file": (path.name, file_bytes)},
                params={"source_channel": "folder_watcher"},
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"Watcher ingested {path.name}: doc_id={result.get('doc_id')}, pages={result.get('total_pages')}")
    except Exception as e:
        logger.error(f"Watcher failed to ingest {path.name}: {e}")
    finally:
        with _lock:
            _in_flight.discard(str(path))


def start_watcher():
    """Start the folder watcher in a background thread. Dev mode only."""
    if os.getenv("ENVIRONMENT", "development") != "development":
        logger.info("Watcher disabled (ENVIRONMENT != development)")
        return

    watch_dir = Path(WATCH_DIR)
    if not watch_dir.exists():
        logger.warning(f"Watcher: /input directory does not exist, watcher not started")
        return

    observer = Observer()
    observer.schedule(IngestOnCreate(), str(watch_dir), recursive=False)
    observer.daemon = True
    observer.start()
    logger.info(f"Watcher started on {WATCH_DIR}")
