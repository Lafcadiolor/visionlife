"""Analyze visual reference folders and export dashboard design research artifacts."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, RateLimitError

from utils import (
    ensure_directory,
    extract_exif_data,
    image_file_to_data_url,
    is_supported_media,
    prepare_media_for_analysis,
)


DEFAULT_MODEL = os.getenv("VISIONLIFE_VISUAL_RESOURCE_MODEL", "gpt-5.4")
DEFAULT_MAX_RETRIES = int(os.getenv("VISIONLIFE_API_MAX_RETRIES", "5"))
DEFAULT_INITIAL_BACKOFF_SECONDS = float(os.getenv("VISIONLIFE_API_INITIAL_BACKOFF", "1.0"))
DEFAULT_MAX_BACKOFF_SECONDS = float(os.getenv("VISIONLIFE_API_MAX_BACKOFF", "16.0"))
DEFAULT_CONCURRENCY = int(os.getenv("VISIONLIFE_MAX_CONCURRENT_ANALYSIS", "3"))

VISUAL_RESOURCE_INSTRUCTION = (
    "You are a design research analyst helping build a restrained but distinctive dashboard. "
    "Analyze the image for layout inspiration, composition patterns, mood, material cues, typography feel, "
    "color relationships, iconography, interaction density, and any motifs worth translating into a digital product. "
    "Focus on understated, contrarian cool style instead of glossy consumer-app clichés. "
    "Return only valid JSON matching the requested schema."
)

VISUAL_RESOURCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "asset_type": {"type": "string"},
        "visual_summary": {"type": "string"},
        "style_direction": {"type": "string"},
        "layout_patterns": {"type": "array", "items": {"type": "string"}},
        "palette": {"type": "array", "items": {"type": "string"}},
        "typography_mood": {"type": "string"},
        "materials_and_texture": {"type": "array", "items": {"type": "string"}},
        "component_ideas": {"type": "array", "items": {"type": "string"}},
        "do_not_do": {"type": "array", "items": {"type": "string"}},
        "dashboard_translation": {"type": "string"},
    },
    "required": [
        "title",
        "asset_type",
        "visual_summary",
        "style_direction",
        "layout_patterns",
        "palette",
        "typography_mood",
        "materials_and_texture",
        "component_ideas",
        "do_not_do",
        "dashboard_translation",
    ],
    "additionalProperties": False,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze local visual resources for dashboard design direction.")
    parser.add_argument("--input-dir", required=True, help="Folder containing source images or videos.")
    parser.add_argument("--output-dir", required=True, help="Folder to write curated dashboard image assets and analyses.")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    input_dir = Path(args.input_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    staging_dir = ensure_directory(output_dir / "prepared")
    analyses_dir = ensure_directory(output_dir / "analysis")
    selected_dir = ensure_directory(output_dir / "images")

    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    semaphore = asyncio.Semaphore(DEFAULT_CONCURRENCY)

    candidates = sorted(path for path in input_dir.iterdir() if path.is_file() and is_supported_media(path))
    results: list[dict[str, Any]] = []

    async def process(path: Path) -> None:
        async with semaphore:
            prepared = await asyncio.to_thread(prepare_media_for_analysis, path, staging_dir)
            exif_data = await asyncio.to_thread(extract_exif_data, prepared.analysis_path)
            image_data_url = await asyncio.to_thread(image_file_to_data_url, prepared.analysis_path)
            response = await create_response_with_retry(
                client=client,
                model=args.model,
                exif_data=exif_data,
                image_data_url=image_data_url,
                filename=path.name,
            )
            payload = json.loads(response.output_text)
            target_image_path = selected_dir / prepared.analysis_path.name
            if prepared.analysis_path != target_image_path:
                shutil.copy2(prepared.analysis_path, target_image_path)

            analysis_record = {
                "source_path": str(path),
                "prepared_path": str(prepared.analysis_path),
                "curated_image_path": str(target_image_path),
                "exif_data": exif_data,
                "analysis": payload,
            }
            analysis_path = analyses_dir / f"{path.stem}.json"
            analysis_path.write_text(json.dumps(analysis_record, indent=2), encoding="utf-8")
            results.append(analysis_record)
            print(f"ANALYZED {path.name}")

    await asyncio.gather(*(process(path) for path in candidates))
    summary_path = output_dir / "dashboard_image_research.json"
    summary_path.write_text(json.dumps({"items": results}, indent=2), encoding="utf-8")
    print(f"SUMMARY {summary_path}")


async def create_response_with_retry(
    *,
    client: AsyncOpenAI,
    model: str,
    exif_data: dict[str, Any],
    image_data_url: str,
    filename: str,
) -> Any:
    for attempt in range(DEFAULT_MAX_RETRIES + 1):
        try:
            return await client.responses.create(
                model=model,
                instructions=VISUAL_RESOURCE_INSTRUCTION,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": (
                                    "Analyze this visual resource for dashboard design inspiration. "
                                    f"Filename: {filename}. "
                                    f"Use this EXIF metadata as weak supporting context only: {json.dumps(exif_data)}"
                                ),
                            },
                            {
                                "type": "input_image",
                                "image_url": image_data_url,
                            },
                        ],
                    }
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "visionlife_visual_resource",
                        "strict": True,
                        "schema": VISUAL_RESOURCE_SCHEMA,
                    }
                },
            )
        except (APIConnectionError, APITimeoutError, RateLimitError, APIStatusError):
            if attempt >= DEFAULT_MAX_RETRIES:
                raise
            await asyncio.sleep(min(DEFAULT_INITIAL_BACKOFF_SECONDS * (2**attempt), DEFAULT_MAX_BACKOFF_SECONDS))


if __name__ == "__main__":
    asyncio.run(main())
