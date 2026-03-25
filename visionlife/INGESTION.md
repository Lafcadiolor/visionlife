# VisionLife Ingestion Guide

This document explains the ingestion side of VisionLife in human-readable terms.

It focuses on what happens from the moment a file appears until a dashboard note
or protected vault bundle is produced.

## 1. What “Ingestion” Means Here

In VisionLife, ingestion means:

1. detect a new file
2. make sure it is stable and readable
3. decide whether it should be processed
4. normalize it into an analysis-friendly form
5. analyze it
6. decide whether it is sensitive
7. publish it either to the dashboard or to the protected `ID` vault

So ingestion is not only “watch a folder.”
It is the whole pipeline from file arrival to durable output.

## 2. Entry Points

There are several ways files can enter the system.

### Watcher path

- [watcher.py](./visionlife/watcher.py)

This is the local testing-oriented entrypoint.
It watches a Desktop shortcut that points to the test inbox.

### Shared runtime bootstrap

- [main.py](./visionlife/main.py)

This file sets up:
- paths
- logging
- observer backend
- history store
- analyzer
- fast-sort service
- pipeline coordinator

### Batch-style or explicit runs

Other scripts like:
- [run_rich_batch.py](./visionlife/run_rich_batch.py)
- [batch_setup.py](./visionlife/batch_setup.py)
- [batch_ingest.py](./visionlife/batch_ingest.py)

use the same underlying analysis/publishing ideas, but not always the watcher path.

## 3. Core Ingestion Stages

The main pipeline lives in:
- [pipeline/orchestrator.py](./visionlife/pipeline/orchestrator.py)

The important stages are:

### Stage 1: Stabilize

Purpose:
- avoid reading a file before the OS or another app is done writing it

If a dropped file is still changing, VisionLife waits.

### Stage 2: Dedupe

Purpose:
- avoid re-processing the same file if it comes back into the inbox

How:
- compute a file hash
- check SQLite history
- if already seen, mark it as duplicate and skip deeper processing

Main storage:
- [db.py](./visionlife/db.py)

### Stage 3: Prepare

Purpose:
- convert many source file types into one normalized analysis asset

Examples:
- large images may be resized
- videos may be reduced to a representative frame
- HEIC/HEIF may be converted to JPEG
- PDFs may be turned into an image-like analysis target

Main helper:
- [utils.py](./visionlife/utils.py)

The output of this stage is a `PreparedAsset`.

### Stage 4: Fast Sort

Purpose:
- cheaply discard obvious junk before paying for cloud analysis

Current use:
- Apple Silicon local fast-sort path
- can auto-delete likely accidental low-value images when confidence is high enough

Main file:
- [fast_sort.py](./visionlife/fast_sort.py)

If fast sort deletes an item, the pipeline stops there and records the outcome.

### Stage 5: Analyze

Purpose:
- call the OpenAI-backed vision layer and get structured meaning back

Main file:
- [vision.py](./visionlife/vision.py)

What the model currently tries to extract:
- OCR text
- objects
- category and subcategory
- image type
- visual style
- personal insight
- metadata interpretation
- calendar-worthy event hints
- action items
- text significance
- optional web-assisted enrichment

### Stage 6: Sensitive-vs-Public Decision

Purpose:
- prevent private or identifying documents from going into the public dashboard

Main file:
- [services/sensitivity_service.py](./visionlife/services/sensitivity_service.py)

The service uses:
- category/subcategory/tag hints
- OCR text
- PII-style regex patterns

If sensitive:
- bundle and encrypt into `ID`

If not sensitive:
- continue to public results/dashboard publishing

### Stage 7: Publish

If public:
- save structured JSON result
- write dashboard Markdown note

If sensitive:
- write encrypted archive bundle into `ID`

Main publishing logic:
- [services/dashboard_service.py](./visionlife/services/dashboard_service.py)
- [services/sensitivity_service.py](./visionlife/services/sensitivity_service.py)

## 4. Key Data Models

### PreparedAsset

Produced during media preparation.

Represents:
- normalized analysis file path
- source file
- notes about transformations
- metadata gathered locally

### AnalysisRecord

Produced by the AI analysis layer.

Represents:
- source path
- prepared analysis path
- local metadata / EXIF
- model output
- optional web enrichment
- pipeline notes

Main typed record layer:
- [records.py](./visionlife/records.py)

### PipelineOutcome

Produced by the orchestrator.

Represents:
- final status for that candidate
- where outputs were written
- whether it was protected, deleted, duplicated, or failed

## 5. How Watcher-Based Ingestion Works

The watcher path uses:
- [main.py](./visionlife/main.py)

Important pieces:

### VisionLifeConfig

This central config defines:
- inbox dir
- workspace dir
- prepared dir
- results dir
- history DB path
- dashboard dir
- `ID` vault dir

### VisionInboxHandler

This is the thin adapter between filesystem events and the async pipeline.

It does not itself analyze files.
It only:
- filters for supported media
- submits supported files into the async processing pipeline
- marks failures via the pipeline

### Observer backend

VisionLife uses polling observer by default because the native macOS event backend was unreliable in this environment.

That means:
- slightly less elegant than native OS change events
- but more robust for local testing

## 6. How OpenAI Analysis Works

The analysis layer in:
- [vision.py](./visionlife/vision.py)

does several things at once:

### Builds a multimodal request

The request uses:
- prepared image/frame
- local EXIF/metadata context
- system instruction describing the extraction goals
- a JSON schema for structured output

### Handles retries

The analysis layer includes retry/backoff for:
- rate limits
- timeouts
- API connection problems
- 5xx style transient failures

### Optional web enrichment

After the main vision result, a secondary step may use web-assisted reasoning to:
- disambiguate place/product/entity clues
- validate likely identities
- enrich results with search-backed context

This is useful for:
- reservations
- signage
- products
- places
- screenshots of external services

## 7. How Sensitive Protection Works

Sensitive handling is intentionally strict.

The flow is:

1. inspect result category/tags/subcategory
2. inspect OCR text
3. match common PII/PDD-style patterns
4. if sensitive, refuse public dashboard publication
5. package result, note, and media into a staging bundle
6. encrypt the bundle
7. save it into the `ID` directory

Current encryption path:
- OpenSSL AES-256-CBC + PBKDF2

Important operational dependency:
- `VISIONLIFE_ID_PASSWORD`

If the password is missing, the system refuses to publish sensitive material publicly.

## 8. What Gets Stored Where

### SQLite history

Used for:
- dedupe
- status tracking
- knowing whether a file was processed already

### Workspace prepared/results

Used for:
- normalized media for analysis
- JSON result output for non-sensitive results

### Dashboard directory

Used for:
- public Markdown note outputs
- `TASKS.md`

### `ID` vault

Used for:
- encrypted sensitive bundles only

## 9. Common Outcome States

A candidate can end up as:

- `duplicate`
  hash already seen

- `deleted_fast_sort`
  removed locally before cloud analysis

- `processed`
  analyzed and published to public dashboard/results

- `protected_sensitive`
  analyzed and moved into encrypted vault

- `failed`
  pipeline exception or unrecoverable processing failure

- `skipped_unstable`
  file never stabilized after arrival

## 10. What to Change When

If you want to change:

- file watching behavior:
  look in [watcher.py](./visionlife/watcher.py) and [main.py](./visionlife/main.py)

- processing order:
  look in [pipeline/orchestrator.py](./visionlife/pipeline/orchestrator.py)

- media preparation rules:
  look in [utils.py](./visionlife/utils.py)

- AI extraction behavior:
  look in [vision.py](./visionlife/vision.py)

- dashboard note output:
  look in [services/dashboard_service.py](./visionlife/services/dashboard_service.py)

- sensitivity rules:
  look in [services/sensitivity_service.py](./visionlife/services/sensitivity_service.py)

## 11. Current Design Principle

The ingestion side is designed to follow this rule:

Normalize early, decide carefully, publish deliberately.

That means:
- stabilize the file before touching it
- normalize into a prepared asset
- make one structured analysis record
- protect sensitive content before public publication
- preserve enough metadata and notes that the result remains explainable later
