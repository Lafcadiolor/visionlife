"""Shared tracker/timeline placement rules for ingestion and presentation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import re
from typing import Any, Mapping


TRACKER_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("friend_family", ("selfie", "two people", "group photo", "friend", "friends", "friendship", "family", "parents", "sibling", "call mom", "call dad")),
    ("relationship", ("relationship", "partner", "date night", "boyfriend", "girlfriend", "wife", "husband", "couple", "romantic")),
    ("fun", ("adventure", "fun", "play", "celebration", "vacation", "weekend", "outing", "airplane", "flight", "aerial view", "sightseeing", "road trip", "bike ride", "ride")),
    ("meditate", ("meditate", "meditation", "mindfulness", "breathwork")),
    ("journal", ("journal", "journaling", "reflection", "write in journal", "diary")),
    ("vitamins", ("vitamin", "supplement", "supplements")),
    ("sobriety", ("sobriety", "sober", "recovery", "aa", "na")),
    ("movement", ("climbing", "yoga", "cardio", "run", "gym", "workout", "exercise", "movement", "hike", "walk")),
    ("client_work", ("client", "deliverable", "invoice", "proposal", "project work", "statement of work")),
    ("lec_consulting", ("lec", "consulting")),
    ("network_search", ("network", "job search", "resume", "interview", "application", "recruiter", "linkedin")),
    ("ai_experiment", ("ai", "openai", "model", "prototype", "experiment", "prompt", "agent")),
    ("mentor", ("mentor", "mentee", "advice call", "coaching")),
    ("home", ("home", "house", "apartment", "campground", "reservation", "booking", "maintenance", "cleaning", "furniture")),
    ("todo", ("ticket", "reservation", "booking", "appointment", "deadline", "todo", "order confirmation", "follow-up")),
    ("priority_thing", ("priority", "first priority")),
]


TYPE_TO_ROW: dict[str, str] = {
    "ticket": "todo",
    "reservation": "todo",
    "boarding_pass": "todo",
    "appointment": "todo",
    "deadline": "todo",
    "event": "todo",
    "pet": "home",
    "document": "todo",
    "reference": "todo",
    "product": "todo",
    "person": "relationship",
    "travel": "fun",
}


@dataclass(slots=True)
class TimelineAttachment:
    """Normalized timeline attachment metadata derived during ingestion."""

    anchor_date: str
    linked_dates: list[str]
    future_dates: list[str]


def infer_tracker_rows_from_payload(
    *,
    title: str = "",
    category: str = "",
    subcategory: str = "",
    image_type: str = "",
    tags: list[str] | None = None,
    visual_summary: str = "",
    personal_insight: str = "",
    location_context: str = "",
    raw_text: str = "",
    primary_objects: list[str] | None = None,
    calendar_item_type: str = "",
) -> list[str]:
    """Return ordered tracker-row matches for artifacts that belong in more than one lane."""
    lowered = " ".join(
        [
            title,
            category,
            subcategory,
            image_type,
            " ".join(tags or []),
            visual_summary,
            personal_insight,
            location_context,
            raw_text,
            " ".join(primary_objects or []),
            calendar_item_type,
        ]
    ).lower()

    matches: list[str] = []
    if calendar_item_type and calendar_item_type in TYPE_TO_ROW:
        matches.append(TYPE_TO_ROW[calendar_item_type])

    for row_id, keywords in TRACKER_KEYWORDS:
        if any(_contains_keyword(lowered, keyword) for keyword in keywords) and row_id not in matches:
            matches.append(row_id)

    if category.lower() in TYPE_TO_ROW:
        hinted = TYPE_TO_ROW[category.lower()]
        if hinted != "todo" and hinted not in matches:
            matches.append(hinted)

    if "movement" in matches and "exercise" not in matches:
        matches.append("exercise")
    if any(row in matches for row in ("movement", "friend_family")) and "fun" not in matches:
        if any(_contains_keyword(lowered, keyword) for keyword in ("hike", "trail", "bike", "ride", "outdoors", "aerial", "flight", "scenic", "adventure")):
            matches.append("fun")

    if not matches:
        matches.append("todo")
    return matches


def infer_tracker_row_from_payload(
    *,
    title: str = "",
    category: str = "",
    subcategory: str = "",
    image_type: str = "",
    tags: list[str] | None = None,
    visual_summary: str = "",
    personal_insight: str = "",
    location_context: str = "",
    raw_text: str = "",
    primary_objects: list[str] | None = None,
    calendar_item_type: str = "",
) -> str:
    """Map an analyzed artifact onto the most plausible tracker row."""
    return infer_tracker_rows_from_payload(
        title=title,
        category=category,
        subcategory=subcategory,
        image_type=image_type,
        tags=tags,
        visual_summary=visual_summary,
        personal_insight=personal_insight,
        location_context=location_context,
        raw_text=raw_text,
        primary_objects=primary_objects,
        calendar_item_type=calendar_item_type,
    )[0]


def infer_tracker_row_from_note(note: Any) -> str:
    """Dashboard-friendly adapter around the shared tracker row inference."""
    explicit_row = str(getattr(note, "tracker_row", "") or "").strip()
    if explicit_row:
        return explicit_row
    return infer_tracker_row_from_payload(
        title=str(getattr(note, "title", "") or ""),
        category=str(getattr(note, "category", "") or ""),
        tags=list(getattr(note, "tags", []) or []),
        visual_summary=str(getattr(note, "visual_summary", "") or ""),
        personal_insight=str(getattr(note, "personal_insight", "") or ""),
        location_context=str(getattr(note, "location_context", "") or ""),
        raw_text=str(getattr(note, "raw_text", "") or ""),
        calendar_item_type=str(getattr(note, "calendar_item_type", "") or ""),
    )


def derive_timeline_attachment(
    *,
    anchor_timestamp: str,
    raw_text: str,
    source_name: str,
    calendar_hint: Mapping[str, Any] | None,
    text_analysis: Mapping[str, Any] | None,
    today_value: date | None = None,
) -> TimelineAttachment:
    """Split detected dates into past attachments and future event candidates."""
    today_value = today_value or date.today()
    discovered: list[str] = []
    for candidate in _extract_dates_from_text(source_name):
        if candidate not in discovered:
            discovered.append(candidate)
    for candidate in _extract_dates_from_text(raw_text):
        if candidate not in discovered:
            discovered.append(candidate)
    for candidate in _string_list((text_analysis or {}).get("detected_dates")):
        normalized = _normalize_date_only(candidate)
        if normalized and normalized not in discovered:
            discovered.append(normalized)

    for key in ("suggested_start", "suggested_end"):
        normalized = _normalize_date_only(str((calendar_hint or {}).get(key) or ""))
        if normalized and normalized not in discovered:
            discovered.append(normalized)

    anchor_date = _normalize_date_only(anchor_timestamp) or anchor_timestamp[:10]
    past_dates: list[str] = []
    future_dates: list[str] = []
    for candidate in discovered:
        try:
            candidate_date = datetime.strptime(candidate, "%Y-%m-%d").date()
        except ValueError:
            continue
        if candidate_date > today_value:
            future_dates.append(candidate)
        else:
            past_dates.append(candidate)

    if anchor_date and anchor_date not in past_dates:
        past_dates.append(anchor_date)

    past_dates = sorted(set(filter(None, past_dates)))
    future_dates = sorted(set(filter(None, future_dates)))
    return TimelineAttachment(anchor_date=anchor_date, linked_dates=past_dates, future_dates=future_dates)


def _extract_dates_from_text(value: str) -> list[str]:
    text = (value or "").strip()
    if not text:
        return []
    results: list[str] = []

    screenshot_match = re.search(
        r"(?P<date>\d{4}-\d{2}-\d{2})\s+at\s+(?P<hour>\d{1,2})[._:](?P<minute>\d{2})(?:[._:](?P<second>\d{2}))?\s*(?P<ampm>AM|PM)",
        text,
        re.IGNORECASE,
    )
    if screenshot_match:
        results.append(screenshot_match.group("date"))

    patterns = (
        (r"\b\d{4}-\d{2}-\d{2}\b", ("%Y-%m-%d",)),
        (r"\b\d{1,2}/\d{1,2}/\d{4}\b", ("%m/%d/%Y", "%d/%m/%Y")),
        (r"\b\d{1,2}-\d{1,2}-\d{4}\b", ("%m-%d-%Y", "%d-%m-%Y")),
        (r"\b[A-Z][a-z]{2,8}\s+\d{1,2},\s+\d{4}\b", ("%B %d, %Y", "%b %d, %Y")),
    )
    for pattern, formats in patterns:
        for match in re.finditer(pattern, text):
            token = match.group(0)
            for fmt in formats:
                try:
                    results.append(datetime.strptime(token, fmt).strftime("%Y-%m-%d"))
                    break
                except ValueError:
                    continue
    return results


def _normalize_date_only(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return raw
    if len(raw) >= 10 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw[:10]):
        return raw[:10]
    normalized = raw.replace(":", "-", 2).replace(" ", "T")
    try:
        return datetime.fromisoformat(normalized).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _contains_keyword(haystack: str, keyword: str) -> bool:
    escaped = re.escape(keyword.lower())
    pattern = rf"(?<![a-z0-9]){escaped}(?![a-z0-9])"
    return re.search(pattern, haystack.lower()) is not None
