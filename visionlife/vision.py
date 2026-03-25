"""OpenAI-backed visual analysis and web-enrichment services."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from pathlib import Path
from typing import Any, Mapping

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, RateLimitError
from records import AnalysisRecord, coerce_analysis_record
from utils import PreparedAsset
from utils import extract_exif_data, image_file_to_data_url


LOGGER = logging.getLogger(__name__)
DEFAULT_MODEL = os.getenv("VISIONLIFE_OPENAI_MODEL", "gpt-5.3-codex")
DEFAULT_WEB_MODEL = os.getenv("VISIONLIFE_WEB_MODEL", "gpt-5")
DEFAULT_CONCURRENCY = int(os.getenv("VISIONLIFE_MAX_CONCURRENT_ANALYSIS", "4"))
DEFAULT_MAX_RETRIES = int(os.getenv("VISIONLIFE_API_MAX_RETRIES", "5"))
DEFAULT_INITIAL_BACKOFF_SECONDS = float(os.getenv("VISIONLIFE_API_INITIAL_BACKOFF", "1.0"))
DEFAULT_MAX_BACKOFF_SECONDS = float(os.getenv("VISIONLIFE_API_MAX_BACKOFF", "16.0"))
DEFAULT_ENABLE_WEB_ENRICHMENT = os.getenv("VISIONLIFE_ENABLE_WEB_ENRICHMENT", "1") != "0"

VISION_SYSTEM_INSTRUCTION = (
    # This prompt is intentionally broad because VisionLife wants one
    # structured pass to cover OCR, categorization, metadata interpretation,
    # actionable-item extraction, and calendar hints. If this grows too much,
    # it should eventually be split into layered enrichments rather than
    # continuing to expand one schema forever.
    "You are VisionLife's visual analyst. Perform OCR and object detection on the provided image. "
    "Assign a high-level category, subcategory, image type, and visual style tags. "
    "Provide a personal insight that explains why you categorized it that way. "
    "If the image contains text, analyze the copy for dates, names, notable phrases, and why the text matters. "
    "Detect whether the image appears to represent a calendar-worthy item such as an event, ticket, invitation, reservation, boarding pass, deadline, or appointment. "
    "If so, extract the most likely calendar details and explain the evidence. "
    "Inspect the provided metadata carefully and report the best available timestamp, whether it is capture time or only modified time, "
    "whether GPS/location metadata is present, what device/software metadata is available, and what the metadata does or does not prove. "
    "If the image is a log, board, note, or document with actionable tasks, extract those tasks. "
    "Use the EXIF metadata as supporting context when it is present, but do not invent facts. "
    "Return only valid JSON that matches the requested schema."
)

WEB_ENRICHMENT_INSTRUCTION = (
    # This second-stage prompt exists to validate or sharpen the first vision pass.
    # It is not a reverse-image search; it is clue-based web reasoning from the
    # extracted visual/text context.
    "You are a web research assistant supporting image classification. "
    "Use web search to validate likely identities, brands, landmarks, product families, or place context "
    "suggested by the image analysis. Return only JSON matching the requested schema. "
    "Do not invent certainty. If the clues are weak, say so."
)

VISION_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "raw_text": {
            "type": "string",
            "description": "All legible text visible in the image, preserving line breaks when useful.",
        },
        "primary_objects": {
            "type": "array",
            "items": {"type": "string"},
            "description": "The most important visible objects or entities in the scene.",
        },
        "location_context": {
            "type": "string",
            "description": "Best-effort location context from image content and EXIF metadata.",
        },
        "visual_summary": {
            "type": "string",
            "description": "A concise summary of the full scene.",
        },
        "category": {
            "type": "string",
            "description": "A high-level category such as memory, travel, receipt, log, workspace, prototype, spiritual, touchpoint, reference, screenshot, event, person, product, landscape, or misc.",
        },
        "subcategory": {
            "type": "string",
            "description": "A more specific secondary classification that narrows the category.",
        },
        "image_type": {
            "type": "string",
            "description": "The visual asset type, such as photo, screenshot, whiteboard, scan, slide, prototype photo, landscape photo, portrait, document capture, poster, UI capture, or video frame.",
        },
        "visual_style": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Descriptors for the image's look or presentation such as editorial, documentary, candid, minimal, diagrammatic, presentation-style, atmospheric, archival, or technical.",
        },
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Short queryable tags for dashboard search.",
        },
        "personal_insight": {
            "type": "string",
            "description": "Explain why the image was categorized this way in plain language.",
        },
        "action_items": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Actionable to-do items found in logs, whiteboards, or documents. Return an empty array if none.",
        },
        "calendar_hint": {
            "type": "object",
            "properties": {
                "should_offer_add_to_calendar": {
                    "type": "boolean",
                    "description": "Whether the dashboard should prompt the user to add this item to a calendar.",
                },
                "item_type": {
                    "type": "string",
                    "description": "One of event, ticket, reservation, boarding_pass, appointment, deadline, reminder, or none.",
                },
                "suggested_title": {
                    "type": "string",
                    "description": "Suggested calendar event title.",
                },
                "suggested_start": {
                    "type": "string",
                    "description": "Best available start timestamp or date in ISO 8601 or YYYY-MM-DD format, or an empty string.",
                },
                "suggested_end": {
                    "type": "string",
                    "description": "Best available end timestamp or date in ISO 8601 or YYYY-MM-DD format, or an empty string.",
                },
                "suggested_location": {
                    "type": "string",
                    "description": "Suggested location or venue for the calendar entry.",
                },
                "suggested_details": {
                    "type": "string",
                    "description": "Helpful description/details for the event creation dialog.",
                },
                "evidence": {
                    "type": "string",
                    "description": "Why the model thinks this should be added to a calendar.",
                },
                "confidence": {
                    "type": "string",
                    "description": "Short confidence note such as high, medium, low, or why confidence is limited.",
                },
            },
            "required": [
                "should_offer_add_to_calendar",
                "item_type",
                "suggested_title",
                "suggested_start",
                "suggested_end",
                "suggested_location",
                "suggested_details",
                "evidence",
                "confidence",
            ],
            "additionalProperties": False,
        },
        "metadata_context": {
            "type": "object",
            "properties": {
                "best_available_timestamp": {
                    "type": "string",
                    "description": "Best available timestamp from metadata, or an empty string if none is available.",
                },
                "timestamp_type": {
                    "type": "string",
                    "description": "Whether the timestamp is captured_at, digitized_at, modified_at, GPS date, or unavailable.",
                },
                "location_available": {
                    "type": "boolean",
                    "description": "Whether any reliable GPS/location metadata is present.",
                },
                "location_details": {
                    "type": "string",
                    "description": "Coordinates or location summary from metadata, or a clear statement that none is available.",
                },
                "device_details": {
                    "type": "string",
                    "description": "Important device/software details from metadata.",
                },
                "file_metadata_notes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Other relevant metadata facts, such as orientation, format, prepared frame, bitrate, or transformations.",
                },
                "metadata_significance": {
                    "type": "string",
                    "description": "Explain how the metadata supports or limits interpretation of the image.",
                },
            },
            "required": [
                "best_available_timestamp",
                "timestamp_type",
                "location_available",
                "location_details",
                "device_details",
                "file_metadata_notes",
                "metadata_significance",
            ],
            "additionalProperties": False,
        },
        "text_analysis": {
            "type": "object",
            "properties": {
                "contains_meaningful_text": {"type": "boolean"},
                "detected_dates": {"type": "array", "items": {"type": "string"}},
                "detected_names": {"type": "array", "items": {"type": "string"}},
                "detected_phrases": {"type": "array", "items": {"type": "string"}},
                "significance": {
                    "type": "string",
                    "description": "Explain why any visible text matters in context, or say that no significant text is present.",
                },
            },
            "required": [
                "contains_meaningful_text",
                "detected_dates",
                "detected_names",
                "detected_phrases",
                "significance",
            ],
            "additionalProperties": False,
        },
    },
    "required": [
        "raw_text",
        "primary_objects",
        "location_context",
        "visual_summary",
        "category",
        "subcategory",
        "image_type",
        "visual_style",
        "tags",
        "personal_insight",
        "action_items",
        "calendar_hint",
        "metadata_context",
        "text_analysis",
    ],
    "additionalProperties": False,
}

WEB_ENRICHMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "search_summary": {
            "type": "string",
            "description": "Short summary of what web search suggests about the image subject or context.",
        },
        "resolved_entities": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Brands, landmarks, product names, places, or entities supported by web search.",
        },
        "classification_adjustment": {
            "type": "string",
            "description": "How the web findings should refine or confirm the image classification.",
        },
        "research_results": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Specific research findings or leads that deepen understanding of the image subject.",
        },
        "style_context": {
            "type": "string",
            "description": "How external context helps explain the style, subject, era, or significance of the image.",
        },
        "confidence_note": {
            "type": "string",
            "description": "Brief note on confidence and ambiguity.",
        },
        "citations": {
            "type": "array",
            "items": {"type": "string"},
            "description": "URLs cited by the web search response.",
        },
    },
    "required": [
        "search_summary",
        "resolved_entities",
        "classification_adjustment",
        "research_results",
        "style_context",
        "confidence_note",
        "citations",
    ],
    "additionalProperties": False,
}


class VisionAnalyzer:
    """Coordinates async visual analysis with retries and optional web enrichment."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        web_model: str = DEFAULT_WEB_MODEL,
        enable_web_enrichment: bool = DEFAULT_ENABLE_WEB_ENRICHMENT,
        max_concurrency: int = DEFAULT_CONCURRENCY,
        max_retries: int = DEFAULT_MAX_RETRIES,
        initial_backoff_seconds: float = DEFAULT_INITIAL_BACKOFF_SECONDS,
        max_backoff_seconds: float = DEFAULT_MAX_BACKOFF_SECONDS,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self.model = model
        self.web_model = web_model
        self.enable_web_enrichment = enable_web_enrichment
        self.client = client or AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.max_retries = max_retries
        self.initial_backoff_seconds = initial_backoff_seconds
        self.max_backoff_seconds = max_backoff_seconds

    async def analyze_asset(self, asset: PreparedAsset) -> AnalysisRecord:
        """Bound concurrency and return a canonical typed analysis record."""
        async with self.semaphore:
            return await self._analyze_asset_impl(asset)

    async def _analyze_asset_impl(self, asset: PreparedAsset) -> AnalysisRecord:
        if asset.media_type != "image":
            raise ValueError(
                f"Vision API analysis expects an image input, received media_type={asset.media_type!r}."
            )

        LOGGER.info("Handing asset to AI layer: %s", asset.analysis_path)
        exif_data = await asyncio.to_thread(extract_exif_data, asset.analysis_path)
        image_data_url = await asyncio.to_thread(image_file_to_data_url, asset.analysis_path)

        response = await self._create_response_with_retry(
            exif_data=exif_data,
            image_data_url=image_data_url,
            asset_metadata=asset.metadata,
            source_filename=Path(str(asset.source_path)).name,
        )
        model_output = _parse_model_output(response.output_text)
        web_enrichment = None
        if self.enable_web_enrichment:
            web_enrichment = await self._enrich_with_web_search(
                asset=asset,
                exif_data=exif_data,
                model_output=model_output,
            )

        return AnalysisRecord.from_parts(
            source_path=asset.source_path,
            analysis_path=asset.analysis_path,
            media_type=asset.media_type,
            transformed=asset.transformed,
            notes=asset.notes,
            metadata=asset.metadata,
            exif_data=exif_data,
            vision_result=model_output,
            web_enrichment=web_enrichment,
        )

    async def _create_response_with_retry(
        self,
        *,
        exif_data: dict[str, Any],
        image_data_url: str,
        asset_metadata: dict[str, Any],
        source_filename: str,
    ) -> Any:
        for attempt in range(self.max_retries + 1):
            try:
                metadata_payload = {
                    "source_filename": source_filename,
                    "exif_data": exif_data,
                    "prepared_asset_metadata": asset_metadata,
                }
                return await self.client.responses.create(
                    model=self.model,
                    instructions=VISION_SYSTEM_INSTRUCTION,
                    input=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_text",
                                    "text": (
                                        "Analyze this photo for OCR and object detection. "
                                        "Use this metadata as supporting context and explicitly report what it tells you about time, place, device, and file handling: "
                                        f"{json.dumps(metadata_payload)}"
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
                            "name": "visionlife_analysis",
                            "strict": True,
                            "schema": VISION_RESPONSE_SCHEMA,
                        }
                    },
                )
            except (APIConnectionError, APITimeoutError, RateLimitError, APIStatusError) as exc:
                if not _is_retryable_error(exc) or attempt >= self.max_retries:
                    raise

                backoff_seconds = min(
                    self.initial_backoff_seconds * (2**attempt),
                    self.max_backoff_seconds,
                )
                sleep_seconds = backoff_seconds * (1.0 + random.uniform(0.0, 0.25))
                LOGGER.warning(
                    "Vision API call failed with %s on attempt %s/%s. Retrying in %.2fs.",
                    exc.__class__.__name__,
                    attempt + 1,
                    self.max_retries + 1,
                    sleep_seconds,
                )
                await asyncio.sleep(sleep_seconds)

    async def _enrich_with_web_search(
        self,
        *,
        asset: PreparedAsset,
        exif_data: dict[str, Any],
        model_output: dict[str, Any],
    ) -> dict[str, Any] | None:
        try:
            response = await self._create_web_enrichment_response(asset, exif_data, model_output)
            payload = _parse_model_output(response.output_text)
            payload["citations"] = _extract_citation_urls(response)
            return payload
        except Exception as exc:
            LOGGER.warning("Web enrichment failed for %s: %s", asset.analysis_path, exc)
            return {
                "search_summary": "",
                "resolved_entities": [],
                "classification_adjustment": "Web enrichment unavailable.",
                "research_results": [],
                "style_context": "",
                "confidence_note": str(exc),
                "citations": [],
            }

    async def _create_web_enrichment_response(
        self,
        asset: PreparedAsset,
        exif_data: dict[str, Any],
        model_output: dict[str, Any],
    ) -> Any:
        search_prompt = _build_web_search_prompt(asset, exif_data, model_output)
        for attempt in range(self.max_retries + 1):
            try:
                return await self.client.responses.create(
                    model=self.web_model,
                    instructions=WEB_ENRICHMENT_INSTRUCTION,
                    tools=[{"type": "web_search"}],
                    input=search_prompt,
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "visionlife_web_enrichment",
                            "strict": True,
                            "schema": WEB_ENRICHMENT_SCHEMA,
                        }
                    },
                )
            except (APIConnectionError, APITimeoutError, RateLimitError, APIStatusError) as exc:
                if not _is_retryable_error(exc) or attempt >= self.max_retries:
                    raise

                backoff_seconds = min(
                    self.initial_backoff_seconds * (2**attempt),
                    self.max_backoff_seconds,
                )
                sleep_seconds = backoff_seconds * (1.0 + random.uniform(0.0, 0.25))
                LOGGER.warning(
                    "Web enrichment failed with %s on attempt %s/%s. Retrying in %.2fs.",
                    exc.__class__.__name__,
                    attempt + 1,
                    self.max_retries + 1,
                    sleep_seconds,
                )
                await asyncio.sleep(sleep_seconds)


def describe_result(result: AnalysisRecord | Mapping[str, Any]) -> str:
    """Format a compact human-readable log line for processed assets."""
    record = coerce_analysis_record(result)
    notes = record.notes
    note_suffix = f" Notes: {' '.join(notes)}" if notes else ""
    summary = record.vision_result.visual_summary
    summary_suffix = f" Summary: {summary}" if summary else ""
    web_enrichment = record.web_enrichment or {}
    web_suffix = ""
    if isinstance(web_enrichment, dict) and web_enrichment.get("resolved_entities"):
        web_suffix = f" Web: {', '.join(str(item) for item in web_enrichment['resolved_entities'][:3])}"
    return (
        f"Prepared {Path(record.source_path).name} as "
        f"{Path(record.analysis_path).name}.{note_suffix}{summary_suffix}{web_suffix}"
    )


def _parse_model_output(output_text: str) -> dict[str, Any]:
    payload = json.loads(output_text)
    if not isinstance(payload, dict):
        raise ValueError("Vision response was not a JSON object.")
    return payload


def _is_retryable_error(exc: Exception) -> bool:
    if isinstance(exc, (APIConnectionError, APITimeoutError, RateLimitError)):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code >= 500
    return False


def _build_web_search_prompt(
    asset: PreparedAsset,
    exif_data: dict[str, Any],
    model_output: dict[str, Any],
) -> str:
    gps_data = exif_data.get("gps") if isinstance(exif_data.get("gps"), dict) else {}
    prompt_payload = {
        "filename": Path(str(asset.source_path)).name,
        "category": model_output.get("category"),
        "subcategory": model_output.get("subcategory"),
        "image_type": model_output.get("image_type"),
        "visual_style": model_output.get("visual_style"),
        "tags": model_output.get("tags"),
        "raw_text": model_output.get("raw_text"),
        "metadata_context": model_output.get("metadata_context"),
        "calendar_hint": model_output.get("calendar_hint"),
        "text_analysis": model_output.get("text_analysis"),
        "primary_objects": model_output.get("primary_objects"),
        "location_context": model_output.get("location_context"),
        "visual_summary": model_output.get("visual_summary"),
        "gps": gps_data,
        "device": exif_data.get("device"),
        "timestamp": exif_data.get("timestamp"),
    }
    return (
        "Use web search to validate or enrich this image classification. "
        "Look for likely matches to brands, landmarks, product prototypes, storefronts, place names, "
        "or OCR text. Prefer precision over speculation.\n\n"
        f"Image clues:\n{json.dumps(prompt_payload, indent=2)}"
    )


def _extract_citation_urls(response: Any) -> list[str]:
    citations: list[str] = []
    for item in getattr(response, "output", []) or []:
        content_items = getattr(item, "content", None)
        if not content_items:
            continue
        for content in content_items:
            for annotation in getattr(content, "annotations", []) or []:
                url = getattr(annotation, "url", None)
                if url and url not in citations:
                    citations.append(url)
    return citations


def build_vision_request_payload(
    image_data_url: str,
    exif_data: dict[str, Any],
    model: str,
    asset_metadata: dict[str, Any] | None = None,
    source_filename: str = "",
) -> dict[str, Any]:
    metadata_payload = {
        "source_filename": source_filename,
        "exif_data": exif_data,
        "prepared_asset_metadata": asset_metadata or {},
    }
    return {
        "model": model,
        "instructions": VISION_SYSTEM_INSTRUCTION,
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "Analyze this photo for OCR and object detection. "
                            "Use this metadata as supporting context and explicitly report what it tells you about time, place, device, and file handling: "
                            f"{json.dumps(metadata_payload)}"
                        ),
                    },
                    {
                        "type": "input_image",
                        "image_url": image_data_url,
                    },
                ],
            }
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "visionlife_analysis",
                "strict": True,
                "schema": VISION_RESPONSE_SCHEMA,
            }
        },
    }
