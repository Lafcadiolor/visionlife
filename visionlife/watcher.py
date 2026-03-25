"""Executable watcher entrypoint used for local file-drop testing."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from main import DEFAULT_GOOGLE_DRIVE_INBOX, VisionLifeConfig, run


def watcher_config() -> VisionLifeConfig:
    """Build watcher config with the Google Drive inbox as the default path."""
    inbox_dir = Path(
        os.getenv("VISIONLIFE_WATCHER_INBOX_DIR", os.getenv("VISIONLIFE_INBOX_DIR", str(DEFAULT_GOOGLE_DRIVE_INBOX)))
    ).expanduser()
    workspace_dir = Path(
        os.getenv(
            "VISIONLIFE_WATCHER_WORKSPACE_DIR",
            str(Path(__file__).resolve().parent / ".visionlife"),
        )
    ).expanduser()
    return VisionLifeConfig(inbox_dir=inbox_dir, workspace_dir=workspace_dir)


def main() -> None:
    """Run the local watcher until interrupted."""
    try:
        asyncio.run(run(watcher_config()))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
