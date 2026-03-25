# VisionLife

VisionLife's watcher is now a separate testing harness. By default it watches the Google Drive synced inbox at `~/Library/CloudStorage/GoogleDrive-your-account/My Drive/Visionlife inbox`.

## Pre-flight rules

- Images larger than 20 MB are resized locally to a 2048px long edge before any AI/API handoff.
- MP4 files use `ffprobe` to inspect bitrate and `ffmpeg` to extract a single analysis frame.
- High-bitrate videos explicitly avoid full-file upload; lower-bitrate videos are also normalized to a frame because the vision model accepts image input, not video input.
- Every file is hashed into `history.db`, so re-adding the same media will not trigger duplicate processing.
- On Apple Silicon, a local CoreML fast-sort classifier can delete only very high-confidence blurred accidental pocket shots before any cloud call.
- Cloud API calls use exponential backoff retries for transient network, rate-limit, and 5xx failures.
- Each processed entry can be synced into `~/Documents/Life_Dashboard` as a Markdown note with YAML frontmatter.
- If a `log` entry contains actionable items, VisionLife appends them to `TASKS.md` in the dashboard folder.

## Setup

```bash
cd "./visionlife"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python watcher.py
```

You can also copy the publish-safe env template first:

```bash
cp .env.example .env
```

For watcher testing, you can override the inbox path:

```bash
VISIONLIFE_WATCHER_INBOX_DIR="$PWD/test_inbox" python watcher.py
```

Or override the shared runtime default explicitly:

```bash
VISIONLIFE_INBOX_DIR="$PWD/test_inbox" python watcher.py
```

Set `OPENAI_API_KEY` before starting the watcher. Vision analysis defaults to `gpt-5.3-codex`, which currently supports image input on the Responses API.

Override the dashboard folder if needed with `VISIONLIFE_DASHBOARD_DIR`.

`main.py` now holds shared runtime/bootstrap logic, while `watcher.py` is the explicit file-system watcher entrypoint used for local testing.

## Batch Prep

To prepare a Batch API JSONL file from the inbox:

```bash
cd "./visionlife"
source .venv/bin/activate
python batch_setup.py --input-dir "$PWD/test_inbox"
```

This writes:

- `.visionlife/batch/visionlife_batch.jsonl`
- `.visionlife/batch/visionlife_batch_manifest.json`

The JSONL file is designed for the Batch API `input_file`, and the manifest maps `custom_id` values back to source files and prepared derivatives.

To monitor a submitted batch and ingest completed results into the dashboard:

```bash
cd "./visionlife"
source .venv/bin/activate
python batch_ingest.py \
  --batch-id "batch_..." \
  --manifest-file "$PWD/.visionlife/batch/visionlife_batch_manifest.json"
```

When the batch reaches `completed`, the ingest worker downloads the output JSONL, writes per-item result JSON into the workspace `results/` folder, and runs the dashboard sync for every successful item.

## Results App

To browse dashboard notes in a simple local visual app:

```bash
cd "./visionlife"
source .venv/bin/activate
python results_app.py --dashboard-dir "$PWD/test_dashboard"
```

Then open `http://127.0.0.1:8777`.

## Visual Resource Search

To analyze a folder of visual references for dashboard direction and export curated dashboard-image assets:

```bash
cd "./visionlife"
source .venv/bin/activate
python visual_resource_search.py \
  --input-dir "$PWD/app_assets/Visionlife dashboard visual resource" \
  --output-dir "$PWD/app_assets/VisionLife_dashboard_images"
```

## Learned Fast Sort

VisionLife now expects a trained CoreML classifier for the local fast-sort gate. Put the model at [visionlife/models/README.md](./visionlife/models/README.md) or override the model path with `VISIONLIFE_FAST_SORT_MODEL_PATH`.

## External prerequisite

Install both `ffmpeg` and `ffprobe` on your PATH if you want video pre-flight checks to work.

## GitHub Readiness

Before pushing this repository:

- keep `.env` local and untracked
- keep `.venv`, `.visionlife`, test runs, dashboards, and generated analysis artifacts untracked
- review any local `test_inbox` assets for personal or copyrighted content before committing
- review `ID` vault contents separately and do not commit encrypted personal archives unless that is intentional
- verify `pyproject.toml`, `requirements.txt`, and `.env.example` reflect the public setup you want others to use
