"""Typed view models for the VisionLife command-desk front end."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class DashboardNote:
    """Parsed note model used by the local dashboard renderer."""

    filename: str
    path: Path
    title: str
    date: str
    linked_dates: list[str]
    future_dates: list[str]
    tracker_row: str
    tracker_rows: list[str]
    category: str
    tags: list[str]
    gps_latitude: str
    gps_longitude: str
    image_path: str
    visual_summary: str
    personal_insight: str
    location_context: str
    primary_objects: str
    raw_text: str
    calendar_offer: bool
    calendar_item_type: str
    calendar_title: str
    calendar_start: str
    calendar_end: str
    calendar_location: str
    calendar_details: str
    calendar_evidence: str
    calendar_confidence: str
    action_items: list[str]


@dataclass(slots=True)
class ResearchAsset:
    """Design-reference asset used to theme the dashboard presentation."""

    title: str
    image_path: str
    style_direction: str
    typography_mood: str
    palette: list[str]
    layout_patterns: list[str]


@dataclass(slots=True)
class TrackerRow:
    """Editable tracker row shown in the command-desk grid."""

    id: str
    label: str
    mode: str = "standard"
    capacity_hours: float = 0.0


@dataclass(slots=True)
class TrackerGroup:
    """Editable row grouping used to structure the command desk."""

    id: str
    label: str
    color: str
    rows: list[TrackerRow]


@dataclass(slots=True)
class DashboardIdentity:
    """Editable command-desk copy and background settings."""

    inscription: str
    affirmation: str
    rotating_phrase: str
    background_caption: str
    background_image_path: str


@dataclass(slots=True)
class DashboardConfig:
    """Local configuration that defines the tracker schema and identity."""

    identity: DashboardIdentity
    groups: list[TrackerGroup]


@dataclass(slots=True)
class ArtifactAssignment:
    """Persistent local assignment state for one analyzed artifact."""

    row_id: str
    approved: bool = False
    highlighted: bool = False
    archived: bool = False
    save_for_later: bool = False
    label: str = ""


@dataclass(slots=True)
class CellState:
    """Persistent tracker state for a single row/date cell."""

    status: str = ""
    note: str = ""


@dataclass(slots=True)
class TodoItem:
    """Small v1 task record stored in local dashboard state."""

    id: str
    source_day: str
    text: str
    type: str
    estimate: str
    suggested_row_id: str
    suggested_day: str
    approved: bool = False
    done: bool = False


@dataclass(slots=True)
class TimeSlice:
    """One visible time slice in the tracker, from full day to compressed band."""

    key: str
    label: str
    mode: str
    kind: str
    days: list[str]
    width_units: float
