# VisionLife

Source-only GitHub export for VisionLife.

Included:
- `visionlife/`: Python ingestion pipeline, local dashboard server, watcher, and dashboard front end
- `VisionLifeiOS/`: SwiftUI iOS client

Excluded on purpose:
- media files
- `.env` and secrets
- generated runs and dashboards
- local databases and caches
- encrypted ID vault contents
- personal dashboard state

## Repo Layout

- `visionlife/README.md`: Python app setup and usage
- `VisionLifeiOS/README.md`: iOS app setup and usage

## Publish Notes

This export has been sanitized to remove personal filesystem paths and local media references. Before pushing to GitHub, review the files once more for anything environment-specific you do not want public.
