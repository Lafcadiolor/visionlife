"""Shared runtime bootstrap for the VisionLife watcher and pipeline."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from dataclasses import dataclass
from pathlib import Path

from db import HistoryStore
from fast_sort import FastSortService
from pipeline import PipelineConfig, VisionProcessingPipeline
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

from utils import (
    ensure_directory,
    is_supported_media,
    running_on_apple_silicon,
)
from vision import VisionAnalyzer


LOG_LEVEL = os.getenv("VISIONLIFE_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
LOGGER = logging.getLogger("visionlife")
OBSERVER_BACKEND = os.getenv("VISIONLIFE_OBSERVER_BACKEND", "polling").lower()
DEFAULT_GOOGLE_DRIVE_INBOX = (
    Path.home() / "VisionLife_Inbox"
)


@dataclass(slots=True)
class VisionLifeConfig:
    """Central filesystem configuration shared by local runtime entrypoints."""

    inbox_dir: Path = Path(
        os.getenv("VISIONLIFE_INBOX_DIR", str(DEFAULT_GOOGLE_DRIVE_INBOX))
    )
    workspace_dir: Path = Path(__file__).resolve().parent / ".visionlife"

    @property
    def prepared_dir(self) -> Path:
        return self.workspace_dir / "prepared"

    @property
    def results_dir(self) -> Path:
        return self.workspace_dir / "results"

    @property
    def history_db_path(self) -> Path:
        return self.workspace_dir / "history.db"

    @property
    def dashboard_dir(self) -> Path:
        return Path(
            os.getenv("VISIONLIFE_DASHBOARD_DIR", str(Path.home() / "Documents" / "Life_Dashboard"))
        )

    @property
    def id_dir(self) -> Path:
        return self.dashboard_dir / "ID"


class VisionInboxHandler(FileSystemEventHandler):
    """Thin watchdog adapter that forwards supported files into the pipeline."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        pipeline: VisionProcessingPipeline,
    ) -> None:
        self.loop = loop
        self.pipeline = pipeline
        self.pending_tasks: set[asyncio.Future[None]] = set()

    def on_created(self, event: FileSystemEvent) -> None:
        self._handle_event(event)

    def on_moved(self, event: FileSystemEvent) -> None:
        self._handle_event(event)

    def _handle_event(self, event: FileSystemEvent) -> None:
        # The watcher intentionally stays thin. It does not interpret files
        # beyond basic support filtering; all real ingestion logic belongs
        # in the async pipeline coordinator.
        if event.is_directory:
            return

        candidate = Path(getattr(event, "dest_path", event.src_path)).expanduser()
        if not is_supported_media(candidate):
            LOGGER.debug("Ignoring unsupported file: %s", candidate)
            return

        LOGGER.info("Detected new media: %s", candidate)
        future = asyncio.run_coroutine_threadsafe(
            self._process_candidate(candidate),
            self.loop,
        )
        self.pending_tasks.add(future)
        future.add_done_callback(self.pending_tasks.discard)

    async def _process_candidate(self, candidate: Path) -> None:
        try:
            await self.pipeline.process_candidate(candidate)
        except Exception as exc:
            await self.pipeline.mark_failure(candidate, exc)


def bootstrap(config: VisionLifeConfig) -> None:
    """Ensure the runtime directories exist before any pipeline work begins.

    This is the point where local filesystem assumptions become concrete.
    If inbox or workspace paths are invalid, the system should fail here
    rather than later inside the processing pipeline.
    """
    try:
        ensure_directory(config.inbox_dir)
    except PermissionError as exc:
        raise PermissionError(
            f"Cannot create or access inbox directory {config.inbox_dir}. "
            "Set VISIONLIFE_INBOX_DIR to a writable location for testing, or create the folder manually."
        ) from exc
    ensure_directory(config.workspace_dir)
    ensure_directory(config.prepared_dir)
    ensure_directory(config.results_dir)
    HistoryStore(config.history_db_path)

async def run(config: VisionLifeConfig) -> None:
    """Start the observer loop and hand file events to the processing pipeline.

    Runtime setup is deliberately centralized here:
    - bootstrap directories
    - create analyzer/history/fast-sort services
    - build the pipeline
    - connect the watcher to that pipeline
    """
    bootstrap(config)
    analyzer = VisionAnalyzer()
    history_store = HistoryStore(config.history_db_path)
    fast_sorter = FastSortService() if running_on_apple_silicon() else None
    loop = asyncio.get_running_loop()
    pipeline = VisionProcessingPipeline(
        config=PipelineConfig(
            workspace_dir=config.workspace_dir,
            results_dir=config.results_dir,
            dashboard_dir=config.dashboard_dir,
            id_dir=config.id_dir,
        ),
        analyzer=analyzer,
        history_store=history_store,
        fast_sorter=fast_sorter,
    )

    observer = create_observer()
    handler = VisionInboxHandler(loop, pipeline)
    observer.schedule(handler, str(config.inbox_dir), recursive=False)
    observer.start()
    LOGGER.info("VisionLife is watching %s", config.inbox_dir)
    if fast_sorter is None:
        LOGGER.warning("Fast sort is disabled because this machine is not Apple Silicon.")
    shutdown_event = asyncio.Event()

    def shutdown_handler() -> None:
        LOGGER.info("Shutting down watcher.")
        observer.stop()
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown_handler)

    try:
        while observer.is_alive() and not shutdown_event.is_set():
            await asyncio.sleep(0.5)
    finally:
        observer.stop()
        observer.join(timeout=5)
        if handler.pending_tasks:
            await asyncio.gather(
                *(asyncio.wrap_future(task) for task in list(handler.pending_tasks)),
                return_exceptions=True,
            )


def create_observer() -> Observer:
    """Build a filesystem observer suitable for the local runtime environment."""
    if OBSERVER_BACKEND == "polling":
        return PollingObserver()
    return Observer()
