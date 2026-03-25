"""Calendar/event inference rules shared across ingestion and presentation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(slots=True)
class CalendarPrompt:
    """Normalized prompt data for opening a prefilled calendar draft."""

    offer: bool
    item_type: str
    title: str
    start: str
    end: str
    location: str
    details: str
    evidence: str
    reason: str


class CalendarPromptSource(Protocol):
    """Minimal note-like interface required by the calendar prompt service."""

    title: str
    date: str
    future_dates: list[str]
    category: str
    tags: list[str]
    visual_summary: str
    personal_insight: str
    location_context: str
    raw_text: str
    calendar_offer: bool
    calendar_item_type: str
    calendar_title: str
    calendar_start: str
    calendar_end: str
    calendar_location: str
    calendar_details: str
    calendar_evidence: str


def infer_calendar_prompt(note: CalendarPromptSource) -> CalendarPrompt:
    """Build a calendar prompt from explicit extraction or fallback heuristics."""
    explicit_start = normalize_event_timestamp(note.calendar_start)
    explicit_end = normalize_event_timestamp(note.calendar_end)
    explicit_title = (note.calendar_title or "").strip()
    explicit_location = (note.calendar_location or "").strip()
    explicit_details = (note.calendar_details or "").strip()
    explicit_evidence = (note.calendar_evidence or "").strip()
    explicit_type = (note.calendar_item_type or "").strip() or "event"
    future_dates = [normalize_event_timestamp(item) for item in getattr(note, "future_dates", []) or []]
    future_dates = [item for item in future_dates if item]

    if note.calendar_offer or explicit_title or explicit_start:
        return CalendarPrompt(
            offer=True,
            item_type=explicit_type,
            title=explicit_title or note.title,
            start=explicit_start or normalize_event_timestamp(note.date),
            end=explicit_end,
            location=explicit_location or note.location_context,
            details=explicit_details or note.personal_insight,
            evidence=explicit_evidence or "Structured event details were extracted during ingestion.",
            reason=f"{explicit_type.replace('_', ' ').title()} detected from image text or metadata.",
        )

    if future_dates:
        start = future_dates[0]
        return CalendarPrompt(
            offer=True,
            item_type=explicit_type if explicit_type != "event" else heuristic_item_type([]),
            title=explicit_title or note.title,
            start=start,
            end=explicit_end,
            location=explicit_location or note.location_context,
            details=explicit_details or (note.raw_text.strip() or note.personal_insight.strip() or note.visual_summary.strip()),
            evidence=explicit_evidence or "Future-dated text was detected during ingestion.",
            reason="One or more future dates were extracted from the artifact.",
        )

    haystack = " ".join(
        [
            note.title,
            note.category,
            " ".join(note.tags),
            note.visual_summary,
            note.personal_insight,
            note.location_context,
            note.raw_text,
        ]
    ).lower()
    keyword_hits = [
        keyword
        for keyword in (
            "ticket",
            "tickets",
            "concert",
            "show",
            "festival",
            "admission",
            "seat",
            "row",
            "gate",
            "boarding",
            "flight",
            "reservation",
            "booking",
            "calendar",
            "meeting",
            "board meeting",
            "appointment",
            "event",
            "invitation",
            "conference",
            "summit",
            "deadline",
            "due",
        )
        if keyword in haystack
    ]
    if not keyword_hits:
        return CalendarPrompt(False, "", "", "", "", "", "", "", "")

    detected_start = first_detected_date(note.raw_text) or first_detected_date(note.title) or normalize_event_timestamp(note.date)
    if not detected_start:
        return CalendarPrompt(False, "", "", "", "", "", "", "", "")

    item_type = heuristic_item_type(keyword_hits)
    details = note.raw_text.strip() or note.personal_insight.strip() or note.visual_summary.strip()
    return CalendarPrompt(
        offer=True,
        item_type=item_type,
        title=note.title,
        start=detected_start,
        end="",
        location=note.location_context,
        details=details[:600],
        evidence=f"Detected calendar-like cues: {', '.join(keyword_hits[:4])}.",
        reason=f"{item_type.replace('_', ' ').title()} cues and a date were found in the note content.",
    )


def heuristic_item_type(keyword_hits: list[str]) -> str:
    joined = " ".join(keyword_hits)
    if "boarding" in joined or "flight" in joined or "gate" in joined:
        return "boarding_pass"
    if "reservation" in joined or "booking" in joined:
        return "reservation"
    if "deadline" in joined or "due" in joined:
        return "deadline"
    if "meeting" in joined:
        return "appointment"
    if "ticket" in joined or "admission" in joined or "seat" in joined or "row" in joined:
        return "ticket"
    return "event"


def normalize_event_timestamp(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return raw
    candidate = raw.replace("Z", "")
    try:
        return datetime.fromisoformat(candidate).isoformat(timespec="seconds")
    except ValueError:
        pass
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(raw, fmt)
            if fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y"):
                return parsed.strftime("%Y-%m-%d")
            return parsed.isoformat(timespec="seconds")
        except ValueError:
            continue
    return ""


def first_detected_date(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""

    screenshot_match = re.search(
        r"(?P<date>\d{4}-\d{2}-\d{2})\s+at\s+(?P<hour>\d{1,2})[._:](?P<minute>\d{2})(?:[._:](?P<second>\d{2}))?\s*(?P<ampm>AM|PM)",
        text,
        re.IGNORECASE,
    )
    if screenshot_match:
        date_part = screenshot_match.group("date")
        hour = int(screenshot_match.group("hour"))
        minute = int(screenshot_match.group("minute"))
        second = int(screenshot_match.group("second") or "0")
        ampm = screenshot_match.group("ampm").upper()
        if ampm == "PM" and hour != 12:
            hour += 12
        if ampm == "AM" and hour == 12:
            hour = 0
        return f"{date_part}T{hour:02d}:{minute:02d}:{second:02d}"

    for pattern, formats in (
        (r"\b\d{4}-\d{2}-\d{2}\b", ("%Y-%m-%d",)),
        (r"\b\d{1,2}/\d{1,2}/\d{4}\b", ("%m/%d/%Y", "%d/%m/%Y")),
        (r"\b\d{1,2}-\d{1,2}-\d{4}\b", ("%m-%d-%Y", "%d-%m-%Y")),
        (r"\b[A-Z][a-z]{2,8}\s+\d{1,2},\s+\d{4}\b", ("%B %d, %Y", "%b %d, %Y")),
    ):
        match = re.search(pattern, text)
        if not match:
            continue
        token = match.group(0)
        for fmt in formats:
            try:
                parsed = datetime.strptime(token, fmt)
                return parsed.strftime("%Y-%m-%d")
            except ValueError:
                continue
    return ""
