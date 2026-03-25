"""Prepare OpenAI Batch API input files from local VisionLife assets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from main import VisionLifeConfig, bootstrap
from utils import (
    compute_file_hash,
    ensure_directory,
    extract_exif_data,
    image_file_to_data_url,
    is_supported_media,
    prepare_media_for_analysis,
)
from vision import DEFAULT_MODEL, build_vision_request_payload


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for batch file preparation."""
    parser = argparse.ArgumentParser(
        description="Prepare an OpenAI Batch API JSONL input file for VisionLife media."
    )
    parser.add_argument(
        "--input-dir",
        default=None,
        help="Directory of source media. Defaults to VISIONLIFE_INBOX_DIR or ~/Pictures/VisionLife_Inbox.",
    )
    parser.add_argument(
        "--workspace-dir",
        default=None,
        help="Working directory for prepared media and batch artifacts. Defaults to VisionLife workspace.",
    )
    parser.add_argument(
        "--output-file",
        default=None,
        help="Target JSONL path. Defaults to <workspace>/batch/visionlife_batch.jsonl.",
    )
    parser.add_argument(
        "--manifest-file",
        default=None,
        help="Target manifest JSON path. Defaults to <workspace>/batch/visionlife_batch_manifest.json.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Model to place in each batch request body. Defaults to {DEFAULT_MODEL}.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = VisionLifeConfig()

    input_dir = Path(args.input_dir).expanduser().resolve() if args.input_dir else config.inbox_dir.resolve()
    workspace_dir = (
        Path(args.workspace_dir).expanduser().resolve() if args.workspace_dir else config.workspace_dir.resolve()
    )

    bootstrap(VisionLifeConfig(inbox_dir=input_dir, workspace_dir=workspace_dir))

    batch_dir = ensure_directory(workspace_dir / "batch")
    output_file = (
        Path(args.output_file).expanduser().resolve()
        if args.output_file
        else batch_dir / "visionlife_batch.jsonl"
    )
    manifest_file = (
        Path(args.manifest_file).expanduser().resolve()
        if args.manifest_file
        else batch_dir / "visionlife_batch_manifest.json"
    )

    records: list[dict[str, Any]] = []
    supported_files = sorted(path for path in input_dir.iterdir() if path.is_file() and is_supported_media(path))

    with output_file.open("w", encoding="utf-8") as handle:
        for source_path in supported_files:
            prepared_asset = prepare_media_for_analysis(source_path, workspace_dir)
            exif_data = extract_exif_data(prepared_asset.analysis_path)
            image_data_url = image_file_to_data_url(prepared_asset.analysis_path)
            file_hash = compute_file_hash(source_path)
            custom_id = f"visionlife-{file_hash[:16]}-{source_path.stem}"

            request_body = build_vision_request_payload(
                image_data_url=image_data_url,
                exif_data=exif_data,
                model=args.model,
            )
            batch_line = {
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/responses",
                "body": request_body,
            }
            handle.write(json.dumps(batch_line) + "\n")

            records.append(
                {
                    "custom_id": custom_id,
                    "source_path": str(source_path),
                    "analysis_path": str(prepared_asset.analysis_path),
                    "media_type": prepared_asset.media_type,
                    "transformed": prepared_asset.transformed,
                    "notes": prepared_asset.notes,
                    "metadata": prepared_asset.metadata,
                    "exif_data": exif_data,
                }
            )

    manifest_file.write_text(json.dumps({"items": records}, indent=2), encoding="utf-8")

    print(f"Prepared {len(records)} batch requests")
    print(f"JSONL: {output_file}")
    print(f"Manifest: {manifest_file}")


if __name__ == "__main__":
    main()
