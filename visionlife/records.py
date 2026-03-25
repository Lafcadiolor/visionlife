"""Canonical typed records shared across VisionLife pipeline stages."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping


@dataclass(slots=True)
class TextAnalysisRecord:
    """Normalized OCR-derived text findings."""
    contains_meaningful_text: bool = False
    detected_dates: list[str] = field(default_factory=list)
    detected_names: list[str] = field(default_factory=list)
    detected_phrases: list[str] = field(default_factory=list)
    significance: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> TextAnalysisRecord:
        payload = value or {}
        return cls(
            contains_meaningful_text=bool(payload.get("contains_meaningful_text", False)),
            detected_dates=_string_list(payload.get("detected_dates")),
            detected_names=_string_list(payload.get("detected_names")),
            detected_phrases=_string_list(payload.get("detected_phrases")),
            significance=str(payload.get("significance") or ""),
        )


@dataclass(slots=True)
class MetadataContextRecord:
    """Normalized interpretation of capture-time and device metadata."""
    best_available_timestamp: str = ""
    timestamp_type: str = ""
    location_available: bool = False
    location_details: str = ""
    device_details: str = ""
    file_metadata_notes: list[str] = field(default_factory=list)
    metadata_significance: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> MetadataContextRecord:
        payload = value or {}
        return cls(
            best_available_timestamp=str(payload.get("best_available_timestamp") or ""),
            timestamp_type=str(payload.get("timestamp_type") or ""),
            location_available=bool(payload.get("location_available", False)),
            location_details=str(payload.get("location_details") or ""),
            device_details=str(payload.get("device_details") or ""),
            file_metadata_notes=_string_list(payload.get("file_metadata_notes")),
            metadata_significance=str(payload.get("metadata_significance") or ""),
        )


@dataclass(slots=True)
class CalendarHintRecord:
    """Structured calendar/event extraction attached to a visual result."""
    should_offer_add_to_calendar: bool = False
    item_type: str = ""
    suggested_title: str = ""
    suggested_start: str = ""
    suggested_end: str = ""
    suggested_location: str = ""
    suggested_details: str = ""
    evidence: str = ""
    confidence: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> CalendarHintRecord:
        payload = value or {}
        return cls(
            should_offer_add_to_calendar=bool(payload.get("should_offer_add_to_calendar", False)),
            item_type=str(payload.get("item_type") or ""),
            suggested_title=str(payload.get("suggested_title") or ""),
            suggested_start=str(payload.get("suggested_start") or ""),
            suggested_end=str(payload.get("suggested_end") or ""),
            suggested_location=str(payload.get("suggested_location") or ""),
            suggested_details=str(payload.get("suggested_details") or ""),
            evidence=str(payload.get("evidence") or ""),
            confidence=str(payload.get("confidence") or ""),
        )


@dataclass(slots=True)
class VisionResultRecord:
    """Primary AI analysis payload for an asset."""
    raw_text: str = ""
    primary_objects: list[str] = field(default_factory=list)
    location_context: str = ""
    visual_summary: str = ""
    category: str = "uncategorized"
    subcategory: str = ""
    image_type: str = ""
    visual_style: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    personal_insight: str = ""
    action_items: list[str] = field(default_factory=list)
    calendar_hint: CalendarHintRecord = field(default_factory=CalendarHintRecord)
    metadata_context: MetadataContextRecord = field(default_factory=MetadataContextRecord)
    text_analysis: TextAnalysisRecord = field(default_factory=TextAnalysisRecord)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> VisionResultRecord:
        payload = value or {}
        return cls(
            raw_text=str(payload.get("raw_text") or ""),
            primary_objects=_string_list(payload.get("primary_objects")),
            location_context=str(payload.get("location_context") or ""),
            visual_summary=str(payload.get("visual_summary") or ""),
            category=str(payload.get("category") or "uncategorized"),
            subcategory=str(payload.get("subcategory") or ""),
            image_type=str(payload.get("image_type") or ""),
            visual_style=_string_list(payload.get("visual_style")),
            tags=_string_list(payload.get("tags")),
            personal_insight=str(payload.get("personal_insight") or ""),
            action_items=_string_list(payload.get("action_items")),
            calendar_hint=CalendarHintRecord.from_mapping(_as_mapping(payload.get("calendar_hint"))),
            metadata_context=MetadataContextRecord.from_mapping(_as_mapping(payload.get("metadata_context"))),
            text_analysis=TextAnalysisRecord.from_mapping(_as_mapping(payload.get("text_analysis"))),
        )


@dataclass(slots=True)
class AnalysisRecord:
    """Canonical end-to-end result for a processed asset."""
    source_path: str
    analysis_path: str
    media_type: str
    transformed: bool = False
    notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    exif_data: dict[str, Any] = field(default_factory=dict)
    vision_result: VisionResultRecord = field(default_factory=VisionResultRecord)
    web_enrichment: dict[str, Any] | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> AnalysisRecord:
        return cls(
            source_path=str(value.get("source_path") or ""),
            analysis_path=str(value.get("analysis_path") or ""),
            media_type=str(value.get("media_type") or ""),
            transformed=bool(value.get("transformed", False)),
            notes=_string_list(value.get("notes")),
            metadata=dict(value.get("metadata") or {}),
            exif_data=dict(value.get("exif_data") or {}),
            vision_result=VisionResultRecord.from_mapping(_as_mapping(value.get("vision_result"))),
            web_enrichment=dict(value.get("web_enrichment") or {}) if value.get("web_enrichment") else None,
        )

    @classmethod
    def from_parts(
        cls,
        *,
        source_path: Path | str,
        analysis_path: Path | str,
        media_type: str,
        transformed: bool,
        notes: list[str],
        metadata: dict[str, Any],
        exif_data: dict[str, Any],
        vision_result: Mapping[str, Any],
        web_enrichment: dict[str, Any] | None,
    ) -> AnalysisRecord:
        return cls(
            source_path=str(source_path),
            analysis_path=str(analysis_path),
            media_type=media_type,
            transformed=transformed,
            notes=list(notes),
            metadata=dict(metadata),
            exif_data=dict(exif_data),
            vision_result=VisionResultRecord.from_mapping(vision_result),
            web_enrichment=dict(web_enrichment or {}) if web_enrichment else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def coerce_analysis_record(value: AnalysisRecord | Mapping[str, Any]) -> AnalysisRecord:
    """Accept typed or legacy dict payloads and return a canonical record."""
    if isinstance(value, AnalysisRecord):
        return value
    return AnalysisRecord.from_mapping(value)


def analysis_record_to_dict(value: AnalysisRecord | Mapping[str, Any]) -> dict[str, Any]:
    """Convert a typed result back to the dict shape used by existing outputs."""
    if isinstance(value, AnalysisRecord):
        return value.to_dict()
    return AnalysisRecord.from_mapping(value).to_dict()


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _as_mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None
