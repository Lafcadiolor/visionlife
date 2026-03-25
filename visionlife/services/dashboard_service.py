"""Services for turning canonical analysis records into dashboard notes."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from records import AnalysisRecord, analysis_record_to_dict
from services.tracker_service import derive_timeline_attachment, infer_tracker_rows_from_payload
from utils import ensure_directory


def sync_result_to_dashboard(result: AnalysisRecord | dict[str, object], dashboard_dir: Path) -> Path:
    """Write one processed result as a Markdown dashboard note and task side effects."""
    ensure_directory(dashboard_dir)
    note_name, note_text, category, action_items = build_dashboard_note(result)
    note_path = dashboard_dir / note_name
    note_path.write_text(note_text, encoding="utf-8")
    if category.lower() == "log" and action_items:
        append_tasks(action_items, dashboard_dir / "TASKS.md", note_path)
    return note_path


def build_dashboard_note(
    result: AnalysisRecord | dict[str, object],
    *,
    media_path_override: str | None = None,
) -> tuple[str, str, str, list[str]]:
    """Render one processed result into the Markdown note format used by VisionLife."""
    result = analysis_record_to_dict(result)
    vision_result = _as_dict(result.get("vision_result"))
    exif_data = _as_dict(result.get("exif_data"))
    gps_data = _as_dict(exif_data.get("gps"))
    timestamp = _resolve_timeline_timestamp(result, vision_result, exif_data)
    category = str(vision_result.get("category") or "uncategorized")
    calendar_hint = _as_dict(vision_result.get("calendar_hint"))
    text_analysis = _as_dict(vision_result.get("text_analysis"))
    tracker_rows = infer_tracker_rows_from_payload(
        title=Path(str(result["source_path"])).stem,
        category=category,
        subcategory=str(vision_result.get("subcategory") or ""),
        image_type=str(vision_result.get("image_type") or ""),
        tags=_string_list(vision_result.get("tags")),
        visual_summary=str(vision_result.get("visual_summary") or ""),
        personal_insight=str(vision_result.get("personal_insight") or ""),
        location_context=str(vision_result.get("location_context") or ""),
        raw_text=str(vision_result.get("raw_text") or ""),
        primary_objects=_string_list(vision_result.get("primary_objects")),
        calendar_item_type=str(calendar_hint.get("item_type") or ""),
    )
    tracker_row = tracker_rows[0]
    attachment = derive_timeline_attachment(
        anchor_timestamp=timestamp,
        raw_text=str(vision_result.get("raw_text") or ""),
        source_name=Path(str(result["source_path"])).name,
        calendar_hint=calendar_hint,
        text_analysis=text_analysis,
    )
    tags = _string_list(vision_result.get("tags")) or [category]
    note_name = _slugify(f"{timestamp}_{Path(str(result['source_path'])).stem}") + ".md"
    frontmatter = _build_frontmatter(
        date_value=timestamp,
        category=category,
        gps_data=gps_data,
        tags=tags,
        tracker_row=tracker_row,
        tracker_rows=tracker_rows,
        linked_dates=attachment.linked_dates,
        future_dates=attachment.future_dates,
    )
    body = _build_body(result, vision_result, media_path_override=media_path_override)
    action_items = _string_list(vision_result.get("action_items"))
    return note_name, frontmatter + "\n" + body, category, action_items


def append_tasks(action_items: list[str], tasks_path: Path, note_path: Path) -> None:
    ensure_directory(tasks_path.parent)
    existing = tasks_path.read_text(encoding="utf-8") if tasks_path.exists() else "# Tasks\n\n"
    lines = [existing.rstrip(), ""]
    for item in action_items:
        lines.append(f"- [ ] {item} ({note_path.name})")
    tasks_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_frontmatter(
    *,
    date_value: str,
    category: str,
    gps_data: dict[str, Any],
    tags: list[str],
    tracker_row: str,
    tracker_rows: list[str],
    linked_dates: list[str],
    future_dates: list[str],
) -> str:
    gps_lat = gps_data.get("latitude")
    gps_lon = gps_data.get("longitude")
    lines = [
        "---",
        f'date: "{date_value}"',
        f'category: "{_yaml_escape(category)}"',
        f'tracker_row: "{_yaml_escape(tracker_row)}"',
        "tracker_rows:",
    ]
    for row_value in tracker_rows:
        lines.append(f'  - "{_yaml_escape(row_value)}"')
    lines.extend([
        "gps:",
        f"  latitude: {gps_lat if gps_lat is not None else 'null'}",
        f"  longitude: {gps_lon if gps_lon is not None else 'null'}",
        "linked_dates:",
    ])
    for linked_date in linked_dates:
        lines.append(f'  - "{_yaml_escape(linked_date)}"')
    lines.extend([
        "future_dates:",
    ])
    for future_date in future_dates:
        lines.append(f'  - "{_yaml_escape(future_date)}"')
    lines.extend(["tags:"])
    for tag in tags:
        lines.append(f'  - "{_yaml_escape(tag)}"')
    lines.append("---")
    return "\n".join(lines)


def _build_body(result: dict[str, object], vision_result: dict[str, Any], *, media_path_override: str | None = None) -> str:
    source_path = Path(str(result["source_path"])).expanduser()
    analysis_path = Path(str(result["analysis_path"])).expanduser()
    display_path = media_path_override or str(analysis_path)
    raw_text = str(vision_result.get("raw_text") or "").strip()
    objects = _string_list(vision_result.get("primary_objects"))
    summary = str(vision_result.get("visual_summary") or "").strip()
    location_context = str(vision_result.get("location_context") or "").strip()
    personal_insight = str(vision_result.get("personal_insight") or "").strip()
    subcategory = str(vision_result.get("subcategory") or "").strip()
    image_type = str(vision_result.get("image_type") or "").strip()
    visual_style = _string_list(vision_result.get("visual_style"))
    text_analysis = _as_dict(vision_result.get("text_analysis"))
    metadata_context = _as_dict(vision_result.get("metadata_context"))
    web_enrichment = _as_dict(result.get("web_enrichment"))
    research_results = _string_list(web_enrichment.get("research_results"))
    resolved_entities = _string_list(web_enrichment.get("resolved_entities"))
    calendar_hint = _as_dict(vision_result.get("calendar_hint"))

    text_analysis_lines = [
        f"Contains meaningful text: {text_analysis.get('contains_meaningful_text', False)}",
        f"Detected dates: {', '.join(_string_list(text_analysis.get('detected_dates'))) or 'None'}",
        f"Detected names: {', '.join(_string_list(text_analysis.get('detected_names'))) or 'None'}",
        f"Detected phrases: {', '.join(_string_list(text_analysis.get('detected_phrases'))) or 'None'}",
        f"Significance: {str(text_analysis.get('significance') or 'No significant text analysis available.')}",
    ]
    metadata_lines = [
        f"Best timestamp: {str(metadata_context.get('best_available_timestamp') or 'None')}",
        f"Timestamp type: {str(metadata_context.get('timestamp_type') or 'unavailable')}",
        f"Location available: {metadata_context.get('location_available', False)}",
        f"Location details: {str(metadata_context.get('location_details') or 'No location metadata available.')}",
        f"Device details: {str(metadata_context.get('device_details') or 'No device metadata available.')}",
        f"File metadata notes: {', '.join(_string_list(metadata_context.get('file_metadata_notes'))) or 'None'}",
        f"Metadata significance: {str(metadata_context.get('metadata_significance') or 'No metadata interpretation available.')}",
    ]
    calendar_lines = [
        f"Offer Add To Calendar: {calendar_hint.get('should_offer_add_to_calendar', False)}",
        f"Item Type: {str(calendar_hint.get('item_type') or 'none')}",
        f"Suggested Title: {str(calendar_hint.get('suggested_title') or '')}",
        f"Suggested Start: {str(calendar_hint.get('suggested_start') or '')}",
        f"Suggested End: {str(calendar_hint.get('suggested_end') or '')}",
        f"Suggested Location: {str(calendar_hint.get('suggested_location') or '')}",
        f"Suggested Details: {str(calendar_hint.get('suggested_details') or '')}",
        f"Evidence: {str(calendar_hint.get('evidence') or '')}",
        f"Confidence: {str(calendar_hint.get('confidence') or '')}",
    ]

    sections = [
        f"# {source_path.stem}",
        "",
        f"![Source]({display_path})",
        "",
        "## Visual Summary",
        summary or "No summary available.",
        "",
        "## Personal Insight",
        personal_insight or "No personal insight available.",
        "",
        "## Action Items",
        *(_string_list(vision_result.get("action_items")) or ["No action items extracted."]),
        "",
        "## Classification Details",
        f"Category: {vision_result.get('category') or 'uncategorized'}",
        f"Subcategory: {subcategory or 'None'}",
        f"Image Type: {image_type or 'Unknown'}",
        f"Visual Style: {', '.join(visual_style) if visual_style else 'None'}",
        "",
        "## Location Context",
        location_context or "No location context available.",
        "",
        "## Metadata Context",
        *metadata_lines,
        "",
        "## Calendar Prompt",
        *calendar_lines,
        "",
        "## Primary Objects",
        ", ".join(objects) if objects else "No primary objects detected.",
        "",
        "## Text Analysis",
        *text_analysis_lines,
        "",
        "## Research Results",
        str(web_enrichment.get("search_summary") or "No research summary available."),
        "",
        f"Resolved Entities: {', '.join(resolved_entities) if resolved_entities else 'None'}",
        f"Classification Adjustment: {str(web_enrichment.get('classification_adjustment') or 'None')}",
        f"Style Context: {str(web_enrichment.get('style_context') or 'None')}",
        f"Research Leads: {', '.join(research_results) if research_results else 'None'}",
        "",
        "## Raw Text",
        "```text",
        raw_text or "",
        "```",
    ]
    return "\n".join(sections).rstrip() + "\n"


def _pick_timestamp(exif_data: dict[str, Any]) -> str:
    timestamp_info = _as_dict(exif_data.get("timestamp"))
    raw_value = timestamp_info.get("captured_at") or timestamp_info.get("digitized_at") or timestamp_info.get("modified_at")
    if isinstance(raw_value, str):
        normalized = _normalize_timestamp_string(raw_value)
        if normalized:
            return normalized
    return ""


def _resolve_timeline_timestamp(result: dict[str, object], vision_result: dict[str, Any], exif_data: dict[str, Any]) -> str:
    source_path = Path(str(result.get("source_path") or "")).expanduser()
    analysis_path = Path(str(result.get("analysis_path") or "")).expanduser()
    source_name = Path(str(result.get("source_path") or "")).name
    raw_text = str(vision_result.get("raw_text") or "")
    metadata_context = _as_dict(vision_result.get("metadata_context"))

    if "screen shot" in source_name.lower():
        detected = _detect_generic_date(source_name) or _detect_generic_date(raw_text)
        if detected is not None:
            return _merge_detected_date_with_time(detected, _best_fallback_timestamp(source_path, analysis_path, exif_data, metadata_context))

    detected = _detect_generic_date(source_name) or _detect_generic_date(raw_text)
    if detected is not None:
        return _merge_detected_date_with_time(detected, _best_fallback_timestamp(source_path, analysis_path, exif_data, metadata_context))

    fallback_timestamp = _best_fallback_timestamp(source_path, analysis_path, exif_data, metadata_context)
    if fallback_timestamp:
        return fallback_timestamp
    return datetime.now().isoformat(timespec="seconds")


def _best_fallback_timestamp(source_path: Path, analysis_path: Path, exif_data: dict[str, Any], metadata_context: dict[str, Any]) -> str:
    metadata_timestamp = _normalize_timestamp_string(str(metadata_context.get("best_available_timestamp") or ""))
    if metadata_timestamp:
        return metadata_timestamp
    exif_timestamp = _pick_timestamp(exif_data)
    if exif_timestamp:
        return exif_timestamp
    file_timestamp = _path_timestamp(source_path) or _path_timestamp(analysis_path)
    if file_timestamp:
        return file_timestamp
    return ""


def _detect_generic_date(value: str) -> datetime | None:
    if not value:
        return None
    screenshot_match = re.search(
        r"(?P<date>\d{4}-\d{2}-\d{2})\s+at\s+(?P<time>\d{1,2})[._:](?P<minute>\d{2})(?:[._:](?P<second>\d{2}))?\s*(?P<ampm>AM|PM)",
        value,
        re.IGNORECASE,
    )
    if screenshot_match:
        date_part = screenshot_match.group("date")
        hour = int(screenshot_match.group("time"))
        minute = int(screenshot_match.group("minute"))
        second = int(screenshot_match.group("second") or "0")
        ampm = screenshot_match.group("ampm").upper()
        if ampm == "PM" and hour != 12:
            hour += 12
        if ampm == "AM" and hour == 12:
            hour = 0
        try:
            parsed_date = datetime.strptime(date_part, "%Y-%m-%d")
            return parsed_date.replace(hour=hour, minute=minute, second=second)
        except ValueError:
            pass
    for pattern, formats in (
        (r"\b\d{4}-\d{2}-\d{2}\b", ("%Y-%m-%d",)),
        (r"\b\d{1,2}/\d{1,2}/\d{4}\b", ("%m/%d/%Y", "%d/%m/%Y")),
        (r"\b\d{1,2}-\d{1,2}-\d{4}\b", ("%m-%d-%Y", "%d-%m-%Y")),
        (r"\b[A-Z][a-z]{2,8}\s+\d{1,2},\s+\d{4}\b", ("%B %d, %Y", "%b %d, %Y")),
    ):
        match = re.search(pattern, value)
        if not match:
            continue
        token = match.group(0)
        for fmt in formats:
            try:
                return datetime.strptime(token, fmt)
            except ValueError:
                continue
    return None


def _merge_detected_date_with_time(detected: datetime, fallback_timestamp: str) -> str:
    try:
        fallback = datetime.fromisoformat(fallback_timestamp)
    except ValueError:
        fallback = None
    if fallback is not None:
        merged = detected.replace(
            hour=detected.hour if detected.hour else fallback.hour,
            minute=detected.minute if detected.minute else fallback.minute,
            second=detected.second if detected.second else fallback.second,
        )
        return merged.isoformat(timespec="seconds")
    if detected.hour == 0 and detected.minute == 0 and detected.second == 0:
        detected = detected.replace(hour=12, minute=0, second=0)
    return detected.isoformat(timespec="seconds")


def _normalize_timestamp_string(value: str) -> str:
    raw = (value or "").strip()
    if not raw or raw.lower() == "unavailable":
        return ""
    normalized = raw.replace(":", "-", 2).replace(" ", "T")
    try:
        return datetime.fromisoformat(normalized).isoformat(timespec="seconds")
    except ValueError:
        return ""


def _path_timestamp(path: Path) -> str:
    if not path or not path.exists():
        return ""
    stat = path.stat()
    return datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _slugify(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-").lower()


def _yaml_escape(value: str) -> str:
    return value.replace('"', '\\"')
