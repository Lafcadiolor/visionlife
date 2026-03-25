"""Local HTML dashboard for browsing VisionLife notes and artifacts."""

from __future__ import annotations

import argparse
import html
import json
import mimetypes
import os
from collections import defaultdict
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from presentation.web.view_models import (
    ArtifactAssignment,
    CellState,
    DashboardConfig,
    DashboardIdentity,
    DashboardNote,
    ResearchAsset,
    TimeSlice,
    TodoItem,
    TrackerGroup,
    TrackerRow,
)
from presentation.web.view_builders import (
    build_command_desk_context,
    build_drawer_context,
    build_standard_drawer_context,
    build_todo_drawer_context,
    build_tracker_grid_context,
)
from services.calendar_service import infer_calendar_prompt
from services.tracker_service import infer_tracker_row_from_note


def get_temporal_context(entry_date_str: str) -> dict[str, str | int]:
    """Map an entry date onto the compressed/expanded timeline visual system."""
    timestamp = (entry_date_str or "").strip()
    try:
        entry_date = datetime.strptime(timestamp[:10], "%Y-%m-%d").date()
    except (ValueError, IndexError):
        return {
            "status": "undated",
            "class": "time-slice undated",
            "label": "Undated",
            "width_weight": 4,
        }

    today = date.today()
    delta = (entry_date - today).days

    if delta < 0:
        days_ago = abs(delta)
        if days_ago > 30:
            compression_class = "past-distant"
        elif days_ago > 7:
            compression_class = "past-recent"
        else:
            compression_class = "past-week"

        return {
            "status": "past",
            "class": f"time-slice past {compression_class}",
            "label": entry_date.strftime("%b %d"),
            "width_weight": max(1, 10 - (days_ago // 10)),
        }

    if delta == 0:
        return {
            "status": "today",
            "class": "time-slice today active-moment",
            "label": "Today",
            "width_weight": 20,
        }

    return {
        "status": "future",
        "class": "time-slice future",
        "label": entry_date.strftime("%A"),
        "width_weight": 15,
    }


def is_artifact_entry(note: DashboardNote) -> bool:
    category = note.category.strip().lower()
    return category in {"spiritual", "touchpoint"}


def artifact_frame_class(note: DashboardNote) -> str:
    category = note.category.strip().lower()
    if category == "touchpoint":
        return "artifact-frame touchpoint-frame"
    if category == "spiritual":
        return "artifact-frame spiritual-frame"
    return "artifact-frame"


def parse_args() -> argparse.Namespace:
    """Parse local server options for dashboard browsing."""
    parser = argparse.ArgumentParser(description="Serve VisionLife dashboard notes as a simple local web app.")
    parser.add_argument(
        "--dashboard-dir",
        default=os.getenv("VISIONLIFE_DASHBOARD_DIR", str(Path.cwd() / "test_dashboard")),
        help="Directory containing dashboard markdown notes and TASKS.md.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8777)
    parser.add_argument(
        "--config-file",
        default=os.getenv(
            "VISIONLIFE_DASHBOARD_CONFIG",
            str(Path(__file__).resolve().parent / "app_assets" / "dashboard_config.json"),
        ),
        help="Local editable dashboard schema and identity config JSON.",
    )
    parser.add_argument(
        "--state-file",
        default=os.getenv(
            "VISIONLIFE_DASHBOARD_STATE",
            str(Path(__file__).resolve().parent / "app_assets" / "dashboard_state.json"),
        ),
        help="Local dashboard UI state JSON for approvals, assignments, and cell statuses.",
    )
    parser.add_argument(
        "--research-file",
        default=os.getenv(
            "VISIONLIFE_RESEARCH_FILE",
            str(Path(__file__).resolve().parent / "app_assets" / "VisionLife_dashboard_images" / "dashboard_image_research.json"),
        ),
        help="Optional visual research summary JSON used to theme the dashboard.",
    )
    parser.add_argument(
        "--inbox-dir",
        default=os.getenv(
            "VISIONLIFE_INBOX_DIR",
            str(
                Path.home()
                / "Library"
                / "CloudStorage"
                / "GoogleDrive-your-account"
                / "My Drive"
                / "Visionlife inbox"
            ),
        ),
        help="Filesystem inbox used by mobile uploads and local ingestion.",
    )
    parser.add_argument("--dump-html", action="store_true", help="Print the rendered index HTML and exit.")
    return parser.parse_args()


STATIC_DIR = Path(__file__).resolve().parent / "presentation" / "web" / "static"
TEMPLATE_DIR = Path(__file__).resolve().parent / "presentation" / "web" / "templates"


DEFAULT_CONFIG: dict[str, Any] = {
    "identity": {
        "inscription": "Think About It In A Different Way. Ask Questions. I Shall",
        "affirmation": "I Deserve It!",
        "rotating_phrase": "If not now, when",
        "background_caption": "If not now, when",
        "background_image_path": "",
    },
    "groups": [
        {
            "id": "morning",
            "label": "Morning",
            "color": "#f3c74d",
            "rows": [
                {"id": "meditate", "label": "Meditate", "mode": "streak"},
                {"id": "journal", "label": "Write in journal", "mode": "streak"},
                {"id": "vitamins", "label": "Vitamins", "mode": "streak"},
            ],
        },
        {
            "id": "work",
            "label": "Do The Work",
            "color": "#ef6a4a",
            "rows": [
                {"id": "exercise", "label": "Exercise", "mode": "standard"},
                {"id": "client_work", "label": "Client work", "mode": "standard", "capacity_hours": 4},
                {"id": "ai_experiment", "label": "Spend one hour a day experimenting with AI", "mode": "analysis", "capacity_hours": 1},
                {"id": "lec_consulting", "label": "LEC Consulting", "mode": "standard", "capacity_hours": 2},
                {"id": "network_search", "label": "Network/Job Search", "mode": "standard", "capacity_hours": 1},
                {"id": "priority_thing", "label": "Do 1st priority thing on my project list today", "mode": "standard", "capacity_hours": 1},
            ],
        },
        {
            "id": "social",
            "label": "Social",
            "color": "#c98ae0",
            "rows": [
                {"id": "friend_family", "label": "Reach out to friend or family", "mode": "standard"},
                {"id": "mentor", "label": "Reach out to mentor or mentee", "mode": "standard"},
            ],
        },
        {
            "id": "admin",
            "label": "Admin",
            "color": "#d8d6d0",
            "rows": [
                {"id": "todo", "label": "To-Do list", "mode": "todo"},
            ],
        },
        {
            "id": "health",
            "label": "Health",
            "color": "#d7e6ef",
            "rows": [
                {"id": "sobriety", "label": "Sobriety", "mode": "streak"},
                {"id": "movement", "label": "Movement", "mode": "streak", "capacity_hours": 1},
                {"id": "home", "label": "Home", "mode": "standard", "capacity_hours": 1},
            ],
        },
        {
            "id": "heart",
            "label": "Heart",
            "color": "#dfe7d4",
            "rows": [
                {"id": "relationship", "label": "Relationship", "mode": "analysis", "capacity_hours": 1},
            ],
        },
        {
            "id": "fun",
            "label": "Fun",
            "color": "#f0d7b8",
            "rows": [
                {"id": "fun", "label": "Fun", "mode": "standard"},
            ],
        },
    ],
}


DEFAULT_STATE: dict[str, Any] = {
    "note_assignments": {},
    "cells": {},
    "todos": [],
}


def load_dashboard_notes(dashboard_dir: Path) -> list[DashboardNote]:
    """Load and sort Markdown note files into view models."""
    notes: list[DashboardNote] = []
    for path in sorted(dashboard_dir.glob("*.md")):
        if path.name == "TASKS.md":
            continue
        notes.append(parse_dashboard_note(path))
    return sorted(notes, key=lambda note: note.date, reverse=True)


def load_dashboard_config(config_file: Path, research_assets: list[ResearchAsset]) -> DashboardConfig:
    """Load the editable dashboard schema, creating a default file when missing."""
    if not config_file.exists():
        ensure_parent(config_file)
        payload = json.loads(json.dumps(DEFAULT_CONFIG))
        payload["identity"]["background_image_path"] = first_research_image(research_assets)
        config_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    payload = json.loads(config_file.read_text(encoding="utf-8"))
    identity_data = payload.get("identity", {})
    configured_background = str(identity_data.get("background_image_path") or "")
    configured_path = Path(configured_background).expanduser() if configured_background else Path()
    local_research = first_research_image(research_assets)
    if configured_path and "Desktop" in str(configured_path) and local_research:
        background_image = local_research
    elif configured_path and configured_path.exists():
        background_image = str(configured_path)
    else:
        background_image = local_research
    identity = DashboardIdentity(
        inscription=str(identity_data.get("inscription") or DEFAULT_CONFIG["identity"]["inscription"]),
        affirmation=str(identity_data.get("affirmation") or DEFAULT_CONFIG["identity"]["affirmation"]),
        rotating_phrase=str(identity_data.get("rotating_phrase") or DEFAULT_CONFIG["identity"]["rotating_phrase"]),
        background_caption=str(identity_data.get("background_caption") or DEFAULT_CONFIG["identity"]["background_caption"]),
        background_image_path=background_image,
    )
    groups: list[TrackerGroup] = []
    for group_data in payload.get("groups", []):
        rows = [
            TrackerRow(
                id=str(row_data.get("id") or slugify_text(str(row_data.get("label") or "row"))),
                label=str(row_data.get("label") or "Row"),
                mode=str(row_data.get("mode") or "standard"),
                capacity_hours=float(row_data.get("capacity_hours") or 0.0),
            )
            for row_data in group_data.get("rows", [])
        ]
        groups.append(
            TrackerGroup(
                id=str(group_data.get("id") or slugify_text(str(group_data.get("label") or "group"))),
                label=str(group_data.get("label") or "Group"),
                color=str(group_data.get("color") or "#d8d6d0"),
                rows=rows,
            )
        )
    return DashboardConfig(identity=identity, groups=groups)


def load_dashboard_state(state_file: Path) -> dict[str, Any]:
    """Load persistent local UI state for approvals, assignments, and cell statuses."""
    if not state_file.exists():
        ensure_parent(state_file)
        state_file.write_text(json.dumps(DEFAULT_STATE, indent=2), encoding="utf-8")
    return json.loads(state_file.read_text(encoding="utf-8"))


def save_json(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON to disk with parent creation."""
    ensure_parent(path)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def first_research_image(research_assets: list[ResearchAsset]) -> str:
    for asset in research_assets:
        if asset.image_path:
            return asset.image_path
    return ""


def slugify_text(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in value).strip("_") or "item"


def load_dashboard_css() -> str:
    css_path = STATIC_DIR / "dashboard.css"
    if css_path.exists():
        return css_path.read_text(encoding="utf-8")
    return BASE_STYLES + COMMAND_DESK_STYLES


def load_dashboard_js() -> str:
    js_path = STATIC_DIR / "dashboard.js"
    if js_path.exists():
        return js_path.read_text(encoding="utf-8")
    return ""


def render_template(name: str, context: dict[str, str]) -> str:
    template_path = TEMPLATE_DIR / name
    content = template_path.read_text(encoding="utf-8")
    for key, value in context.items():
        content = content.replace(f"{{{{{key}}}}}", value)
    return content


def parse_dashboard_note(path: Path) -> DashboardNote:
    """Parse one dashboard note into the fields used by the HTML renderer."""
    text = path.read_text(encoding="utf-8")
    frontmatter, body = split_frontmatter(text)
    frontmatter_map = parse_simple_yaml(frontmatter)
    sections = parse_sections(body)
    image_path = extract_image_path(body)
    title = body.splitlines()[0].lstrip("# ").strip() if body.strip() else path.stem
    gps_map = frontmatter_map.get("gps", {})
    calendar_prompt = parse_labeled_section(sections.get("Calendar Prompt", ""))

    return DashboardNote(
        filename=path.name,
        path=path,
        title=title,
        date=str(frontmatter_map.get("date", "")),
        linked_dates=[str(item) for item in frontmatter_map.get("linked_dates", []) if str(item).strip()],
        future_dates=[str(item) for item in frontmatter_map.get("future_dates", []) if str(item).strip()],
        tracker_row=str(frontmatter_map.get("tracker_row", "")),
        tracker_rows=[str(item) for item in frontmatter_map.get("tracker_rows", []) if str(item).strip()],
        category=str(frontmatter_map.get("category", "uncategorized")),
        tags=list(frontmatter_map.get("tags", [])),
        gps_latitude=str(gps_map.get("latitude", "")),
        gps_longitude=str(gps_map.get("longitude", "")),
        image_path=image_path,
        visual_summary=sections.get("Visual Summary", ""),
        personal_insight=sections.get("Personal Insight", ""),
        location_context=sections.get("Location Context", ""),
        primary_objects=sections.get("Primary Objects", ""),
        raw_text=sections.get("Raw Text", ""),
        calendar_offer=_truthy(calendar_prompt.get("Offer Add To Calendar", "")),
        calendar_item_type=calendar_prompt.get("Item Type", ""),
        calendar_title=calendar_prompt.get("Suggested Title", ""),
        calendar_start=calendar_prompt.get("Suggested Start", ""),
        calendar_end=calendar_prompt.get("Suggested End", ""),
        calendar_location=calendar_prompt.get("Suggested Location", ""),
        calendar_details=calendar_prompt.get("Suggested Details", ""),
        calendar_evidence=calendar_prompt.get("Evidence", ""),
        calendar_confidence=calendar_prompt.get("Confidence", ""),
        action_items=[
            line.strip("- ").strip()
            for line in sections.get("Action Items", "").splitlines()
            if line.strip() and line.strip("- ").strip() != "No action items extracted."
        ],
    )


def suggested_row_id(note: DashboardNote) -> str:
    """Infer the best tracker row for a note before user approval."""
    return infer_tracker_row_from_note(note)


def all_rows(config: DashboardConfig) -> list[TrackerRow]:
    return [row for group in config.groups for row in group.rows]


def row_lookup(config: DashboardConfig) -> dict[str, TrackerRow]:
    return {row.id: row for row in all_rows(config)}


def group_lookup(config: DashboardConfig) -> dict[str, TrackerGroup]:
    return {group.id: group for group in config.groups}


def get_assignment(note: DashboardNote, state: dict[str, Any]) -> ArtifactAssignment:
    raw = state.get("note_assignments", {}).get(note.filename, {})
    return ArtifactAssignment(
        row_id=str(raw.get("row_id") or suggested_row_id(note)),
        approved=bool(raw.get("approved", False)),
        highlighted=bool(raw.get("highlighted", False)),
        archived=bool(raw.get("archived", False)),
        save_for_later=bool(raw.get("save_for_later", False)),
        label=str(raw.get("label") or ""),
    )


def get_cell_state(state: dict[str, Any], day_key: str, row_id: str) -> CellState:
    raw = state.get("cells", {}).get(f"{day_key}|{row_id}", {})
    return CellState(status=str(raw.get("status") or ""), note=str(raw.get("note") or ""))


def artifact_type(note: DashboardNote) -> str:
    prompt = infer_calendar_prompt(note)
    if prompt.offer:
        return "event"
    if note.image_path.lower().endswith((".mov", ".mp4")):
        return "video"
    if note.image_path.lower().endswith((".jpg", ".jpeg", ".png", ".heic", ".heif")):
        return "photo"
    if "link" in " ".join(note.tags).lower():
        return "link"
    return "note"


def notes_for_row_and_day(notes: list[DashboardNote], state: dict[str, Any], day_key: str, row_id: str) -> list[DashboardNote]:
    matches: list[DashboardNote] = []
    for note in notes:
        linked_days = [normalize_day(item) for item in (note.linked_dates or [note.date])]
        if day_key not in linked_days:
            continue
        raw_assignment = state.get("note_assignments", {}).get(note.filename, {})
        assignment = get_assignment(note, state)
        if assignment.archived:
            continue
        if "row_id" in raw_assignment:
            if assignment.row_id == row_id:
                matches.append(note)
            continue
        note_rows = note.tracker_rows or [note.tracker_row] or [assignment.row_id]
        if row_id in note_rows:
            matches.append(note)
    return sorted(matches, key=lambda item: (not get_assignment(item, state).approved, item.title.lower()))


def derived_cell_status(day_key: str, row_id: str, notes: list[DashboardNote], state: dict[str, Any]) -> str:
    """Infer a completion status from past-linked artifacts when no manual state exists."""
    explicit = get_cell_state(state, day_key, row_id).status
    if explicit:
        return explicit
    if day_key >= date.today().isoformat():
        return ""
    if notes_for_row_and_day(notes, state, day_key, row_id):
        return "done"
    return ""


def derived_cell_summary(day_key: str, row_id: str, notes: list[DashboardNote], state: dict[str, Any]) -> str:
    """Return a short artifact-derived summary for a cell when no manual note exists."""
    explicit = get_cell_state(state, day_key, row_id).note.strip()
    if explicit:
        return explicit
    cell_notes = notes_for_row_and_day(notes, state, day_key, row_id)
    if not cell_notes:
        return ""
    first = cell_notes[0]
    assignment = get_assignment(first, state)
    if row_id in {"movement", "exercise"}:
        if assignment.label.strip():
            return assignment.label.strip()
        return infer_activity_summary(first)
    if row_id == "friend_family":
        return "Friends"
    return ""


def infer_activity_summary(note: DashboardNote) -> str:
    """Best-effort one-word activity label for movement/exercise tracker cells."""
    text = " ".join(
        [
            note.title,
            " ".join(note.tags),
            note.visual_summary,
            note.personal_insight,
            note.location_context,
            note.primary_objects,
            note.raw_text,
        ]
    ).lower()
    mapping = [
        ("bike", "Bike"),
        ("bicycle", "Bike"),
        ("cycling", "Bike"),
        ("ride", "Ride"),
        ("climb", "Climb"),
        ("climbing", "Climb"),
        ("yoga", "Yoga"),
        ("run", "Run"),
        ("running", "Run"),
        ("walk", "Walk"),
        ("hike", "Hike"),
        ("hiking", "Hike"),
        ("cardio", "Cardio"),
        ("gym", "Workout"),
        ("workout", "Workout"),
        ("exercise", "Exercise"),
    ]
    for keyword, label in mapping:
        if keyword in text:
            return label
    return "Move"


def normalize_day(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if len(raw) >= 10:
        return raw[:10]
    return raw


TODO_TYPES = ["admin", "work", "health", "relationship", "home", "event", "follow-up", "idea"]
TIME_PRESETS = ["15m", "30m", "1h", "2h", "4h"]


def load_todos(state: dict[str, Any]) -> list[TodoItem]:
    """Convert persisted todo payloads into typed items."""
    items: list[TodoItem] = []
    for raw in state.get("todos", []):
        items.append(
            TodoItem(
                id=str(raw.get("id") or ""),
                source_day=str(raw.get("source_day") or ""),
                text=str(raw.get("text") or ""),
                type=str(raw.get("type") or "admin"),
                estimate=str(raw.get("estimate") or "30m"),
                suggested_row_id=str(raw.get("suggested_row_id") or "todo"),
                suggested_day=str(raw.get("suggested_day") or ""),
                approved=bool(raw.get("approved", False)),
                done=bool(raw.get("done", False)),
            )
        )
    return items


def todo_to_dict(item: TodoItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "source_day": item.source_day,
        "text": item.text,
        "type": item.type,
        "estimate": item.estimate,
        "suggested_row_id": item.suggested_row_id,
        "suggested_day": item.suggested_day,
        "approved": item.approved,
        "done": item.done,
    }


def estimate_hours(value: str) -> float:
    mapping = {"15m": 0.25, "30m": 0.5, "1h": 1.0, "2h": 2.0, "4h": 4.0}
    return mapping.get((value or "").strip(), 0.5)


def suggested_row_for_todo(text: str, todo_type: str, config: DashboardConfig) -> str:
    text_lower = (text or "").lower()
    if todo_type == "relationship":
        return "relationship"
    if todo_type == "health":
        if any(keyword in text_lower for keyword in ("run", "yoga", "cardio", "climb", "climbing", "walk", "gym")):
            return "movement"
        return "sobriety" if "sober" in text_lower else "movement"
    if todo_type == "home":
        return "home"
    if todo_type == "event":
        return "todo"
    if todo_type == "follow-up":
        if any(keyword in text_lower for keyword in ("friend", "family")):
            return "friend_family"
        if any(keyword in text_lower for keyword in ("mentor", "mentee")):
            return "mentor"
        return "todo"
    if todo_type == "work":
        if "lec" in text_lower:
            return "lec_consulting"
        if any(keyword in text_lower for keyword in ("job", "network", "resume", "application", "interview")):
            return "network_search"
        if "ai" in text_lower:
            return "ai_experiment"
        if "priority" in text_lower:
            return "priority_thing"
        return "client_work"
    if todo_type == "idea":
        return "ai_experiment"
    return "todo" if "todo" in row_lookup(config) else all_rows(config)[0].id


def scheduled_hours_for_day(row_id: str, day_key: str, todos: list[TodoItem]) -> float:
    return sum(
        estimate_hours(item.estimate)
        for item in todos
        if item.suggested_row_id == row_id and item.suggested_day == day_key and not item.done
    )


def suggest_todo_day(source_day: str, row: TrackerRow, estimate: str, todos: list[TodoItem]) -> str:
    try:
        base_day = datetime.strptime(source_day or date.today().isoformat(), "%Y-%m-%d").date()
    except ValueError:
        base_day = date.today()
    required = estimate_hours(estimate)
    capacity = row.capacity_hours or 1.0
    for offset in range(1, 15):
        candidate = base_day.fromordinal(base_day.toordinal() + offset).isoformat()
        if scheduled_hours_for_day(row.id, candidate, todos) + required <= capacity + 1e-9:
            return candidate
    return base_day.fromordinal(base_day.toordinal() + 1).isoformat()


def todos_for_day(day_key: str, todos: list[TodoItem]) -> list[TodoItem]:
    return [item for item in todos if item.source_day == day_key and not item.done]


def todos_for_cell(day_key: str, row_id: str, todos: list[TodoItem]) -> list[TodoItem]:
    return [item for item in todos if item.suggested_day == day_key and item.suggested_row_id == row_id and not item.done]


def split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---\n"):
        return "", text
    parts = text.split("\n---\n", 1)
    if len(parts) != 2:
        return "", text
    return parts[0][4:], parts[1]


def parse_simple_yaml(frontmatter: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    current_key: str | None = None
    list_keys = {"tags", "linked_dates", "future_dates", "tracker_rows"}

    for raw_line in frontmatter.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue

        if line.startswith("  - ") and current_key:
            result.setdefault(current_key, []).append(line[4:].strip().strip('"'))
            continue

        if line.startswith("  ") and current_key == "gps":
            key, value = line.strip().split(":", 1)
            result.setdefault("gps", {})[key.strip()] = value.strip().strip('"')
            continue

        if ":" in line:
            key, value = line.split(":", 1)
            current_key = key.strip()
            stripped = value.strip()
            if not stripped:
                result[current_key] = [] if current_key in list_keys else {}
            else:
                result[current_key] = stripped.strip('"')

    return result


def parse_sections(body: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current_section: str | None = None
    buffer: list[str] = []

    for line in body.splitlines():
        if line.startswith("## "):
            if current_section is not None:
                sections[current_section] = "\n".join(buffer).strip().strip("```text").strip("```").strip()
            current_section = line[3:].strip()
            buffer = []
        elif current_section is not None:
            buffer.append(line)

    if current_section is not None:
        sections[current_section] = "\n".join(buffer).strip().strip("```text").strip("```").strip()

    return sections


def parse_labeled_section(section: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in section.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()
    return data


def extract_image_path(body: str) -> str:
    for line in body.splitlines():
        if line.startswith("![Source](") and line.endswith(")"):
            return line[len("![Source](") : -1]
    return ""


def load_tasks(tasks_path: Path) -> list[str]:
    if not tasks_path.exists():
        return []
    tasks: list[str] = []
    for line in tasks_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("- [ ] "):
            tasks.append(line[6:].strip())
    return tasks


def load_research_assets(research_file: Path) -> list[ResearchAsset]:
    if not research_file.exists():
        return []
    payload = json.loads(research_file.read_text(encoding="utf-8"))
    assets: list[ResearchAsset] = []
    for item in payload.get("items", []):
        analysis = item.get("analysis", {})
        image_path = resolve_research_image_path(research_file.parent, str(item.get("curated_image_path", "")))
        assets.append(
            ResearchAsset(
                title=str(analysis.get("title", Path(item.get("source_path", "")).stem)),
                image_path=image_path,
                style_direction=str(analysis.get("style_direction", "")),
                typography_mood=str(analysis.get("typography_mood", "")),
                palette=[str(value) for value in analysis.get("palette", [])],
                layout_patterns=[str(value) for value in analysis.get("layout_patterns", [])],
            )
        )
    return assets


def resolve_research_image_path(base_dir: Path, raw_path: str) -> str:
    """Prefer in-project research assets over stale Desktop absolute paths."""
    candidate = Path(raw_path).expanduser() if raw_path else Path()
    if candidate and candidate.exists():
        return str(candidate)
    local_copy = base_dir / "images" / candidate.name
    if candidate.name and local_copy.exists():
        return str(local_copy)
    fallback = Path(__file__).resolve().parent / "app_assets" / "VisionLife_dashboard_images" / "images" / candidate.name
    if candidate.name and fallback.exists():
        return str(fallback)
    return raw_path


def render_index(notes: list[DashboardNote], tasks: list[str], dashboard_dir: Path, research_assets: list[ResearchAsset]) -> str:
    lead_note = notes[0] if notes else None
    remaining_notes = notes[1:] if len(notes) > 1 else []
    lead_html = render_lead_note(lead_note) if lead_note else ""
    cards = render_card_grid(remaining_notes) if remaining_notes else '<div class="empty">No dashboard notes yet.</div>'
    tasks_html = "\n".join(f"<li>{html.escape(task)}</li>" for task in tasks) or "<li>Nothing pending.</li>"
    category_options = build_category_options(notes)
    hero_metric = str(len(notes)).zfill(2)
    research_strip = render_research_strip(research_assets)
    guidance = render_guidance_panel(research_assets)
    manifesto = render_manifesto_panel(research_assets)
    timeline = render_timeline(notes)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>VisionLife Ledger</title>
  <style>{BASE_STYLES}</style>
</head>
<body>
  {render_top_menu("dashboard")}
  <main class="shell">
    <section class="frame">
    <section class="masthead">
      <div class="title-panel hero-panel">
        <div class="eyebrow">VisionLife Ledger</div>
        <div class="hero-metric">{hero_metric}</div>
        <h1>Quiet evidence. Earned meaning. No glossy dashboard theatre.</h1>
        <div class="subtitle">
          A reading surface for memory, identity, achievement, and the hard lessons that stay after the noise drops away. VisionLife remains searchable, but it presents its evidence like a personal archive, not a control panel.
        </div>
        <div class="hero-rule"></div>
        <div class="hero-microcopy">Framed editorial shells, warm paper, walnut, brushed metal, and selective boxed emphasis adapted from your visual reference study.</div>
      </div>
      <aside class="tasks-panel">
        <div class="eyebrow">Open Loop</div>
        <h2>Tasks</h2>
        <ul>{tasks_html}</ul>
        {guidance}
      </aside>
    </section>
    {manifesto}
    {timeline}
    {research_strip}
    <form class="filters" method="get" action="/">
      <input type="search" name="q" value="" placeholder="Search titles, summaries, insight, raw text">
      <select name="category">
        <option value="">All categories</option>
        {category_options}
      </select>
      <input type="search" name="tag" value="" placeholder="Filter by tag">
      <div style="display:flex; gap:10px;">
        <button type="submit">Filter</button>
        <a href="/">Reset</a>
      </div>
    </form>
    <section class="ledger">
      {lead_html}
      <div class="archive-column">{cards}</div>
    </section>
    <div class="footer">Source: {html.escape(str(dashboard_dir))}</div>
    </section>
  </main>
  {render_calendar_dialog()}
</body>
</html>"""


def render_card(note: DashboardNote, variant: str = "standard") -> str:
    media_html = (
        f'<img src="/media?path={html.escape(note.image_path)}" alt="{html.escape(note.title)}">'
        if note.image_path
        else ""
    )
    tags_html = "\n".join(f"<li>{html.escape(tag)}</li>" for tag in note.tags)
    gps = ""
    if note.gps_latitude or note.gps_longitude:
        gps = f"GPS {html.escape(note.gps_latitude)}, {html.escape(note.gps_longitude)}"
    note_link = f"/note?file={html.escape(note.filename)}"
    temporal_context = get_temporal_context(note.date)
    artifact_open = f'<div class="{artifact_frame_class(note)}">' if is_artifact_entry(note) else ""
    artifact_close = "</div>" if artifact_open else ""
    calendar_action = render_calendar_button(note)
    return f"""
    <div class="{html.escape(str(temporal_context['class']))}" data-time-status="{html.escape(str(temporal_context['status']))}" style="flex-grow: {int(temporal_context['width_weight'])};">
      <div class="time-label">{html.escape(str(temporal_context['label']))}</div>
      {artifact_open}
      <article class="card {variant}">
      <div class="media">{media_html}</div>
      <div class="body">
        <div class="meta">
          <span>{html.escape(note.category)}</span>
          <span>{html.escape(note.date)}</span>
        </div>
        <h3><a href="{note_link}" style="color:inherit; text-decoration:none;">{html.escape(note.title)}</a></h3>
        <div class="summary">{html.escape(note.visual_summary or note.location_context or "No summary yet.")}</div>
        <div class="insight">{html.escape(note.personal_insight or "No personal insight yet.")}</div>
        {calendar_action}
        <ul class="tags">{tags_html}</ul>
        <div class="footer">{html.escape(gps)}</div>
      </div>
      </article>
      {artifact_close}
    </div>
    """


def render_card_grid(notes: list[DashboardNote]) -> str:
    fragments: list[str] = []
    for index, note in enumerate(notes):
        variant = "marginal" if index % 3 == 2 else "standard"
        fragments.append(render_card(note, variant=variant))
    return f'<section class="grid">{"" .join(fragments)}</section>'


def render_lead_note(note: DashboardNote | None) -> str:
    if note is None:
        return ""
    media_html = (
        f'<img src="/media?path={html.escape(note.image_path)}" alt="{html.escape(note.title)}">'
        if note.image_path
        else ""
    )
    note_link = f"/note?file={html.escape(note.filename)}"
    tags_html = "\n".join(f"<li>{html.escape(tag)}</li>" for tag in note.tags[:6])
    temporal_context = get_temporal_context(note.date)
    artifact_open = f'<div class="{artifact_frame_class(note)}">' if is_artifact_entry(note) else ""
    artifact_close = "</div>" if artifact_open else ""
    calendar_action = render_calendar_button(note)
    return f"""
    <div class="{html.escape(str(temporal_context['class']))} lead-slice" data-time-status="{html.escape(str(temporal_context['status']))}" style="flex-grow: {int(temporal_context['width_weight'])};">
      <div class="time-label">{html.escape(str(temporal_context['label']))}</div>
      {artifact_open}
      <article class="lead-note">
      <div class="lead-note-media">{media_html}</div>
      <div class="lead-note-body">
        <div class="eyebrow">Featured Entry</div>
        <div class="meta">
          <span>{html.escape(note.category)}</span>
          <span>{html.escape(note.date)}</span>
        </div>
        <h2><a href="{note_link}" style="color:inherit; text-decoration:none;">{html.escape(note.title)}</a></h2>
        <p class="lead-summary">{html.escape(note.visual_summary or "No summary available.")}</p>
        {calendar_action}
        <div class="insight-panel">
          <div class="insight-label">Personal Insight</div>
          <p>{html.escape(note.personal_insight or "No personal insight yet.")}</p>
        </div>
        <div class="lead-support">
          <div class="support-block">
            <div class="support-label">Location Context</div>
            <div>{html.escape(note.location_context or "No location context available.")}</div>
          </div>
          <div class="support-block">
            <div class="support-label">Tags</div>
            <ul class="tags">{tags_html}</ul>
          </div>
        </div>
      </div>
      </article>
      {artifact_close}
    </div>
    """


def render_timeline(notes: list[DashboardNote]) -> str:
    if not notes:
        return ""
    slices: list[str] = []
    for note in sorted(notes, key=lambda item: item.date):
        temporal_context = get_temporal_context(note.date)
        note_link = f"/note?file={html.escape(note.filename)}"
        slices.append(
            f"""
            <a class="{html.escape(str(temporal_context['class']))} timeline-segment" href="{note_link}" style="flex-grow: {int(temporal_context['width_weight'])};">
              <span class="timeline-label">{html.escape(str(temporal_context['label']))}</span>
              <span class="timeline-title">{html.escape(note.title)}</span>
            </a>
            """
        )
    return f"""
    <section class="timeline" aria-label="VisionLife timeline">
      <div class="timeline-header">
        <div class="eyebrow">Timeline</div>
        <div class="timeline-copy">Past compresses, today anchors, future opens out.</div>
      </div>
      <div class="timeline-track">{''.join(slices)}</div>
    </section>
    """


def render_calendar_button(note: DashboardNote) -> str:
    prompt = infer_calendar_prompt(note)
    if not prompt.offer:
        return ""

    return (
        '<div class="calendar-action">'
        f'<button type="button" class="calendar-button" '
        f'data-title="{html.escape(prompt.title, quote=True)}" '
        f'data-start="{html.escape(prompt.start, quote=True)}" '
        f'data-end="{html.escape(prompt.end, quote=True)}" '
        f'data-location="{html.escape(prompt.location, quote=True)}" '
        f'data-details="{html.escape(prompt.details, quote=True)}" '
        f'data-note="{html.escape(note.title, quote=True)}" '
        f'data-type="{html.escape(prompt.item_type, quote=True)}" '
        f'data-evidence="{html.escape(prompt.evidence, quote=True)}" '
        f'onclick="openCalendarDialog(this)">Add to calendar</button>'
        f'<div class="calendar-reason">{html.escape(prompt.reason)}</div>'
        "</div>"
    )


def render_top_menu(active: str) -> str:
    items = [
        ("Dashboard", "/", "dashboard"),
        ("Tracker", "https://docs.google.com/spreadsheets/d/1GIr3g8ba6vLMt-Ave8caYbfjQcs7P4_8LzGeWhXi8Eo/edit?usp=sharing", "tracker"),
        ("ID", "/?panel=id", "id"),
        ("Calendar", "https://calendar.google.com/", "calendar"),
        ("Links", "/?panel=links", "links"),
        ("Journal", "/?panel=journal", "journal"),
    ]
    links: list[str] = []
    for label, href, key in items:
        class_name = "menu-link active" if key == active else "menu-link"
        links.append(f'<a class="{class_name}" href="{href}">{html.escape(label)}</a>')
    return f"""
    <header class="top-header">
      <div class="top-header-label">VisionLife Navigation</div>
      <nav class="top-menu" aria-label="Primary">{"" .join(links)}</nav>
    </header>
    """


def render_research_strip(assets: list[ResearchAsset]) -> str:
    if not assets:
        return ""
    featured = assets[:4]
    figures = []
    for asset in featured:
        image = (
            f'<img src="/media?path={html.escape(asset.image_path)}" alt="{html.escape(asset.title)}">'
            if asset.image_path
            else ""
        )
        figures.append(
            f"""
            <figure class="reference">
              <div class="reference-media">{image}</div>
              <figcaption>
                <div class="reference-title">{html.escape(asset.title)}</div>
                <div class="reference-copy">{html.escape((asset.style_direction or '')[:170])}</div>
              </figcaption>
            </figure>
            """
        )
    return f'<section class="reference-strip">{"".join(figures)}</section>'


def render_guidance_panel(assets: list[ResearchAsset]) -> str:
    if not assets:
        return ""
    first = assets[0]
    no_lines = []
    for item in first.layout_patterns[:2]:
        no_lines.append(f"<li>{html.escape(item)}</li>")
    palette = " · ".join(html.escape(value) for value in first.palette[:5])
    return f"""
    <div class="guidance-panel">
      <div class="eyebrow">Reference Notes</div>
      <div class="guidance-copy">{html.escape(first.typography_mood)}</div>
      <ul class="guidance-list">{''.join(no_lines)}</ul>
      <div class="palette-line">{palette}</div>
    </div>
    """


def render_manifesto_panel(assets: list[ResearchAsset]) -> str:
    if not assets:
        return ""
    title = html.escape(assets[0].title)
    return f"""
    <section class="manifesto">
      <div class="manifesto-block">
        <div class="eyebrow">Inspiration</div>
        <p>Editorial framing, hand-marked surfaces, and object-like hierarchy. The interface treats memory as something mounted and reread, not endlessly refreshed.</p>
      </div>
      <div class="manifesto-block">
        <div class="eyebrow">Identity</div>
        <p>Self-authored, textured, and revised through use. The page allows asymmetry and human friction instead of sanding everything into product smoothness.</p>
      </div>
      <div class="manifesto-block">
        <div class="eyebrow">Achievement</div>
        <p>Milestones appear as artifacts, not applause. The oversized numeral and framed surfaces borrow from <span class="manifesto-source">{title}</span> to give accomplishment weight without vanity.</p>
      </div>
      <div class="manifesto-block">
        <div class="eyebrow">Hard Lessons</div>
        <p>Meaning needs space. Not every signal deserves equal emphasis. The layout favors editing, restraint, and the quiet authority of what remains after easier interpretations have been discarded.</p>
      </div>
    </section>
    """


def build_command_window(selected_day: str) -> list[TimeSlice]:
    """Build a scale-aware time window centered on today with compressed bands further out."""
    try:
        anchor = datetime.strptime(selected_day, "%Y-%m-%d").date()
    except ValueError:
        anchor = date.today()

    def day(offset: int, label: str, width_units: float, mode: str) -> TimeSlice:
        value = anchor.fromordinal(anchor.toordinal() + offset).isoformat()
        return TimeSlice(
            key=value,
            label=label,
            mode=mode,
            kind="day",
            days=[value],
            width_units=width_units,
        )

    last_week_days = [
        anchor.fromordinal(anchor.toordinal() + offset).isoformat()
        for offset in range(-14, -7)
    ]
    next_week_days = [
        anchor.fromordinal(anchor.toordinal() + offset).isoformat()
        for offset in range(7, 14)
    ]

    return [
        TimeSlice("last-week", "Last Week", "week-band", "week", last_week_days, 0.5),
        day(-3, anchor.fromordinal(anchor.toordinal() - 3).strftime("%a"), 0.45, "compressed"),
        day(-2, anchor.fromordinal(anchor.toordinal() - 2).strftime("%a"), 0.6, "compressed"),
        day(-1, "Yesterday", 1.0, "near"),
        day(0, "Today", 2.0, "focus"),
        day(1, "Tomorrow", 1.0, "near"),
        day(2, anchor.fromordinal(anchor.toordinal() + 2).strftime("%a"), 0.6, "compressed"),
        day(3, anchor.fromordinal(anchor.toordinal() + 3).strftime("%a"), 0.45, "compressed"),
        TimeSlice("next-week", "Next Week", "week-band", "week", next_week_days, 0.5),
    ]


def day_label(day_key: str) -> str:
    try:
        current = datetime.strptime(day_key, "%Y-%m-%d").date()
    except ValueError:
        return day_key
    if current == date.today():
        return "Today"
    if current == date.today().fromordinal(date.today().toordinal() + 1):
        return "Tomorrow"
    return current.strftime("%a %d")


def build_selected_day(raw_notes: list[DashboardNote], query: dict[str, list[str]]) -> str:
    requested = query.get("day", [""])[0]
    if requested:
        return requested
    today_key = date.today().isoformat()
    return today_key if any(normalize_day(note.date) == today_key for note in raw_notes) or not raw_notes else today_key


def summarize_status_for_days(row_id: str, days: list[str], notes: list[DashboardNote], state: dict[str, Any], todos: list[TodoItem]) -> str:
    """Collapse multiple days into one dominant visual status for compressed bands."""
    counts = {"done": 0, "excused": 0, "oops": 0, "missed": 0}
    for day in days:
        status = derived_cell_status(day, row_id, notes, state)
        if status in counts:
            counts[status] += 1
    if any(item.suggested_row_id == row_id and item.suggested_day in days and not item.done for item in todos):
        return "scheduled"
    if counts["done"]:
        return "done"
    if counts["excused"]:
        return "excused"
    if counts["oops"]:
        return "oops"
    if counts["missed"]:
        return "missed"
    return ""


def timeline_anchor_class(day_key: str) -> str:
    return str(get_temporal_context(day_key)["class"])


def render_command_desk(
    filtered_notes: list[DashboardNote],
    raw_notes: list[DashboardNote],
    tasks: list[str],
    dashboard_dir: Path,
    research_assets: list[ResearchAsset],
    config: DashboardConfig,
    state: dict[str, Any],
    query: dict[str, list[str]],
) -> str:
    """Render the immersive command-desk homepage."""
    styles = load_dashboard_css()
    script = load_dashboard_js()
    selected_day = build_selected_day(raw_notes, query)
    selected_row = query.get("row", [""])[0] or config.groups[0].rows[0].id
    selected_window = build_command_window(selected_day)
    todos = load_todos(state)
    timeline_html = render_command_timeline(raw_notes, selected_day, selected_window)
    grid_html = render_tracker_grid(raw_notes, config, state, selected_window, selected_day, selected_row, todos)
    drawer_html = render_right_drawer(raw_notes, tasks, config, state, selected_day, selected_row)
    weekly_cards = render_weekly_analysis_cards(raw_notes, config, state)
    background_media = ""
    if config.identity.background_image_path:
        background_media = f'<img class="background-art" src="/media?path={html.escape(config.identity.background_image_path)}" alt="{html.escape(config.identity.background_caption)}">'
    return render_template(
        "command_desk.html",
        build_command_desk_context(
            styles=styles,
            background_media=background_media,
            background_caption=html.escape(config.identity.background_caption),
            inscription=html.escape(config.identity.inscription),
            affirmation=html.escape(config.identity.affirmation),
            rotating_phrase=html.escape(config.identity.rotating_phrase),
            timeline_html=timeline_html,
            grid_html=grid_html,
            weekly_cards=weekly_cards,
            drawer_html=drawer_html,
            dashboard_source=html.escape(str(dashboard_dir)),
            calendar_dialog=render_calendar_dialog(),
            bootstrap_script=render_command_desk_script(config, selected_day, selected_row),
            script=script,
        ),
    )


def render_command_timeline(notes: list[DashboardNote], selected_day: str, slices: list[TimeSlice]) -> str:
    links: list[str] = []
    for slice_item in slices:
        representative = slice_item.days[0]
        context = get_temporal_context(representative)
        active = " selected" if representative == selected_day else ""
        links.append(
            f'<a class="command-timeline-segment {html.escape(slice_item.mode)} {html.escape(str(context["class"]))}{active}" '
            f'href="/?day={html.escape(representative)}" style="flex-grow:{slice_item.width_units};">'
            f'<span class="timeline-day">{html.escape(slice_item.label)}</span>'
            f'<span class="timeline-date">{html.escape(representative if slice_item.kind == "day" else slice_item.days[0] + " → " + slice_item.days[-1])}</span>'
            "</a>"
        )
    return f"""
    <section class="command-timeline">
      <div class="command-timeline-copy">Past compresses. Today anchors. Future opens.</div>
      <div class="command-timeline-track">{''.join(links)}</div>
    </section>
    """


def render_tracker_grid(
    notes: list[DashboardNote],
    config: DashboardConfig,
    state: dict[str, Any],
    day_window: list[TimeSlice],
    selected_day: str,
    selected_row: str,
    todos: list[TodoItem],
) -> str:
    header = "".join(
        render_slice_header(slice_item, selected_day)
        for slice_item in day_window
    )
    groups_html: list[str] = []
    for group in config.groups:
        rows_html: list[str] = []
        for row in group.rows:
            row_label = (
                f'<div class="row-label editable-text" data-row-id="{html.escape(row.id)}" contenteditable="true" spellcheck="false">{html.escape(row.label)}</div>'
            )
            cells = "".join(render_cell(slice_item, row, notes, state, selected_day, selected_row, todos) for slice_item in day_window)
            rows_html.append(
                f'<div class="tracker-row" data-row-id="{html.escape(row.id)}" data-mode="{html.escape(row.mode)}" data-capacity-hours="{row.capacity_hours}">{row_label}<div class="row-cells">{cells}</div></div>'
            )
        groups_html.append(
            f"""
            <section class="tracker-group">
              <div class="group-label editable-text" data-group-id="{html.escape(group.id)}" contenteditable="true" spellcheck="false" style="--group-color:{html.escape(group.color)}">{html.escape(group.label)}</div>
              <div class="group-rows">{''.join(rows_html)}</div>
            </section>
            """
        )
    return render_template(
        "components/tracker_grid.html",
        build_tracker_grid_context(
            header_html=header,
            groups_html="".join(groups_html),
        ),
    )


def render_slice_header(slice_item: TimeSlice, selected_day: str) -> str:
    representative = slice_item.days[0]
    selected = " selected" if representative == selected_day else ""
    date_copy = representative if slice_item.kind == "day" else f"{slice_item.days[0]} → {slice_item.days[-1]}"
    return (
        f'<div class="day-column-head {html.escape(slice_item.mode)}{selected}" style="flex:{slice_item.width_units} 0 0;">'
        f"<div>{html.escape(slice_item.label)}</div>"
        f'<div class="day-date">{html.escape(date_copy)}</div>'
        "</div>"
    )


def render_cell(slice_item: TimeSlice, row: TrackerRow, notes: list[DashboardNote], state: dict[str, Any], selected_day: str, selected_row: str, todos: list[TodoItem]) -> str:
    day_key = slice_item.days[0]
    representative_notes = notes_for_row_and_day(notes, state, day_key, row.id)
    representative_todos = todos_for_cell(day_key, row.id, todos)
    if row.mode == "todo":
        representative_todos = todos_for_day(day_key, todos)
    cell_state = get_cell_state(state, day_key, row.id)
    status_value = (
        derived_cell_status(day_key, row.id, notes, state)
        if slice_item.kind == "day"
        else summarize_status_for_days(row.id, slice_item.days, notes, state, todos)
    )
    status_class = f" status-{status_value}" if status_value else ""
    selected_class = " selected" if day_key == selected_day and selected_row == row.id else ""
    chips: list[str] = []
    calendar_html = ""
    for note in representative_notes[:4]:
        assignment = get_assignment(note, state)
        kind = artifact_type(note)
        chip_class = "artifact-chip approved" if assignment.approved else "artifact-chip provisional"
        chips.append(f'<span class="{chip_class}" title="{html.escape(note.title)}">{artifact_icon(kind)}</span>')
        prompt = infer_calendar_prompt(note)
        if prompt.offer and not calendar_html:
            calendar_html = (
                f'<button type="button" class="cell-calendar-button" title="Add to calendar" '
                f'data-title="{html.escape(prompt.title, quote=True)}" '
                f'data-start="{html.escape(prompt.start, quote=True)}" '
                f'data-end="{html.escape(prompt.end, quote=True)}" '
                f'data-location="{html.escape(prompt.location, quote=True)}" '
                f'data-details="{html.escape(prompt.details, quote=True)}" '
                f'data-note="{html.escape(note.title, quote=True)}" '
                f'data-type="{html.escape(prompt.item_type, quote=True)}" '
                f'data-evidence="{html.escape(prompt.evidence, quote=True)}" '
                'onclick="openCalendarDialog(this)">+</button>'
            )
    for item in representative_todos[:4]:
        chip_class = "artifact-chip approved" if item.approved else "artifact-chip provisional"
        chips.append(f'<span class="{chip_class}" title="{html.escape(item.text)}">□</span>')
    total = len(representative_notes) + len(representative_todos)
    if slice_item.kind == "week":
        total += sum(
            len(notes_for_row_and_day(notes, state, candidate, row.id)) + len(todos_for_cell(candidate, row.id, todos))
            for candidate in slice_item.days[1:]
        )
        if row.mode == "todo":
            total = sum(len(todos_for_day(candidate, todos)) for candidate in slice_item.days)
    count = f'<span class="artifact-count">{total}</span>' if total else ""
    if representative_todos:
        count = f'<span class="artifact-count">{total}</span>'
    note_preview = ""
    cell_summary = derived_cell_summary(day_key, row.id, notes, state)
    if slice_item.mode in {"focus", "near"} and cell_summary:
        trimmed = cell_summary[:48] + ("..." if len(cell_summary) > 48 else "")
        note_preview = f'<span class="cell-note-preview">{html.escape(trimmed)}</span>'
    if slice_item.mode == "pixel":
        chips = []
        calendar_html = ""
        note_preview = ""
    return (
        f'<a class="tracker-cell {html.escape(slice_item.mode)} {html.escape(slice_item.kind)}{status_class}{selected_class}" '
        f'href="/?day={html.escape(day_key)}&row={html.escape(row.id)}" style="flex:{slice_item.width_units} 0 0;">'
        f'<span class="cell-inner">{count}<span class="artifact-strip">{"".join(chips)}</span>{calendar_html}{note_preview}</span>'
        "</a>"
    )


def artifact_icon(kind: str) -> str:
    mapping = {
        "photo": "◐",
        "video": "▶",
        "event": "◪",
        "link": "↗",
        "note": "◆",
    }
    return mapping.get(kind, "◆")


def render_right_drawer(
    notes: list[DashboardNote],
    tasks: list[str],
    config: DashboardConfig,
    state: dict[str, Any],
    selected_day: str,
    selected_row: str,
) -> str:
    row_map = row_lookup(config)
    row = row_map.get(selected_row, all_rows(config)[0])
    todos = load_todos(state)
    cell_notes = notes_for_row_and_day(notes, state, selected_day, row.id)
    cell_state = get_cell_state(state, selected_day, row.id)
    if row.mode == "todo":
        return render_todo_drawer(tasks, config, state, selected_day, row)
    grouped: dict[str, list[DashboardNote]] = defaultdict(list)
    for note in cell_notes:
        grouped[artifact_type(note)].append(note)
    groups_html: list[str] = []
    for kind in ("event", "photo", "video", "link", "note"):
        items = grouped.get(kind, [])
        if not items:
            continue
        rendered = "".join(render_drawer_note(note, state) for note in items)
        groups_html.append(f'<section class="drawer-group"><div class="drawer-group-label">{html.escape(kind.title())}</div>{rendered}</section>')
    if not groups_html:
        groups_html.append('<div class="drawer-empty">No approved or suggested artifacts in this cell yet. Tomorrow stays easy: add only what matters.</div>')
    streak_summary = render_row_summary(row, notes, state)
    task_preview = "".join(f"<li>{html.escape(task)}</li>" for task in tasks[:4]) or "<li>Nothing pending.</li>"
    return render_template(
        "components/right_drawer.html",
        build_standard_drawer_context(
            overline=html.escape(day_label(selected_day)),
            title=html.escape(row.label),
            subline=html.escape(selected_day),
            top_controls=render_status_controls(selected_day, row.id, state) + render_cell_note_editor(selected_day, row.id, cell_state),
            summary=html.escape(streak_summary),
            actions_html=(
                f"<section class=\"drawer-actions\">"
                f"<button type=\"button\" class=\"drawer-action\" onclick=\"openPlanner('{html.escape(selected_day)}')\">Plan tomorrow</button>"
                f"<button type=\"button\" class=\"drawer-action\" onclick=\"saveDashboardConfig()\">Save layout edits</button>"
                f"</section>"
            ),
            stream_html="".join(groups_html),
            tasks_html=task_preview,
        ),
    )


def render_todo_drawer(tasks: list[str], config: DashboardConfig, state: dict[str, Any], selected_day: str, row: TrackerRow) -> str:
    todos = todos_for_day(selected_day, load_todos(state))
    grouped: dict[str, list[TodoItem]] = defaultdict(list)
    for item in todos:
        grouped[item.type].append(item)
    groups_html: list[str] = []
    for todo_type in TODO_TYPES:
        items = grouped.get(todo_type, [])
        if not items:
            continue
        rendered = "".join(render_todo_item(item, config) for item in items)
        groups_html.append(f'<section class="drawer-group"><div class="drawer-group-label">{html.escape(todo_type.title())}</div>{rendered}</section>')
    if not groups_html:
        groups_html.append('<div class="drawer-empty">Capture first. Tasks will be typed, scheduled, and prompted into the near future as provisional work.</div>')
    task_preview = "".join(f"<li>{html.escape(task)}</li>" for task in tasks[:4]) or "<li>Nothing pending.</li>"
    return render_template(
        "components/right_drawer.html",
        build_todo_drawer_context(
            overline=html.escape(day_label(selected_day)),
            title=html.escape(row.label),
            subline=html.escape(selected_day),
            top_controls=render_todo_capture(selected_day, config),
            summary="Everything lands here first, then gets typed, given a time estimate, and prompted into the next realistic row/date by available capacity.",
            stream_html="".join(groups_html),
            tasks_html=task_preview,
        ),
    )


def render_todo_capture(selected_day: str, config: DashboardConfig) -> str:
    type_options = "".join(f'<option value="{html.escape(todo_type)}">{html.escape(todo_type.title())}</option>' for todo_type in TODO_TYPES)
    time_options = "".join(f'<option value="{html.escape(preset)}">{html.escape(preset)}</option>' for preset in TIME_PRESETS)
    return f"""
    <section class="todo-capture">
      <div class="drawer-group-label">Add Item</div>
      <textarea id="todo-text" class="cell-note-input" rows="3" placeholder="Capture the task, link, follow-up, or idea..."></textarea>
      <div class="todo-capture-grid">
        <label>Type<select id="todo-type" class="todo-select">{type_options}</select></label>
        <label>Estimate<select id="todo-estimate" class="todo-select">{time_options}</select></label>
      </div>
      <div class="cell-note-actions">
        <button type="button" class="drawer-action mini" onclick="createTodo('{html.escape(selected_day)}')">Add to-do</button>
      </div>
    </section>
    """


def render_todo_item(item: TodoItem, config: DashboardConfig) -> str:
    row_name = row_lookup(config).get(item.suggested_row_id).label if item.suggested_row_id in row_lookup(config) else item.suggested_row_id
    state_label = "approved" if item.approved else "provisional"
    return render_template(
        "components/todo_item.html",
        {
            "state_label": state_label,
            "text": html.escape(item.text),
            "estimate": html.escape(item.estimate),
            "summary": f"Suggested for {html.escape(item.suggested_day)} in {html.escape(row_name)}.",
            "actions_html": (
                drawer_button("Approve", f"updateTodo({json.dumps(item.id)}, 'approved', true)")
                + drawer_button("Done", f"updateTodo({json.dumps(item.id)}, 'done', true)")
            ),
        },
    )


def render_status_controls(selected_day: str, row_id: str, state: dict[str, Any]) -> str:
    current = get_cell_state(state, selected_day, row_id).status
    labels = [
        ("done", "Did it"),
        ("excused", "Excused"),
        ("oops", "Oops"),
        ("missed", "Did not happen"),
    ]
    buttons = []
    for value, label in labels:
        active = " active" if current == value else ""
        buttons.append(
            f'<button type="button" class="status-chip {value}{active}" onclick="updateCellStatus(\'{html.escape(selected_day)}\', \'{html.escape(row_id)}\', \'{value}\')">{html.escape(label)}</button>'
        )
    return f'<div class="status-controls">{"".join(buttons)}</div>'


def render_cell_note_editor(selected_day: str, row_id: str, cell_state: CellState) -> str:
    note_value = html.escape(cell_state.note)
    return f"""
    <section class="cell-note-editor">
      <div class="drawer-group-label">Cell Note</div>
      <textarea id="cell-note-input" class="cell-note-input" rows="4" placeholder="Write a short note for this day and row...">{note_value}</textarea>
      <div class="cell-note-actions">
        <button type="button" class="drawer-action mini" onclick="saveCellNote('{html.escape(selected_day)}', '{html.escape(row_id)}')">Save note</button>
      </div>
    </section>
    """


def render_drawer_note(note: DashboardNote, state: dict[str, Any]) -> str:
    assignment = get_assignment(note, state)
    prompt = infer_calendar_prompt(note)
    approval_class = "approved" if assignment.approved else "provisional"
    filename_js = json.dumps(note.filename)
    actions = [
        drawer_button("Approve", f"updateAssignment({filename_js}, 'approved', true)"),
        drawer_button("Reassign", f"openReassign({filename_js})"),
        drawer_button("Highlight", f"toggleAssignmentFlag({filename_js}, 'highlighted')"),
        drawer_button("Save For Later", f"toggleAssignmentFlag({filename_js}, 'save_for_later')"),
        drawer_button("Archive", f"toggleAssignmentFlag({filename_js}, 'archived')"),
    ]
    calendar = ""
    if prompt.offer:
        calendar = (
            f'<button type="button" class="mini-calendar" '
            f'data-title="{html.escape(prompt.title, quote=True)}" '
            f'data-start="{html.escape(prompt.start, quote=True)}" '
            f'data-end="{html.escape(prompt.end, quote=True)}" '
            f'data-location="{html.escape(prompt.location, quote=True)}" '
            f'data-details="{html.escape(prompt.details, quote=True)}" '
            f'data-note="{html.escape(note.title, quote=True)}" '
            f'data-type="{html.escape(prompt.item_type, quote=True)}" '
            f'data-evidence="{html.escape(prompt.evidence, quote=True)}" '
            'onclick="openCalendarDialog(this)">Add to calendar</button>'
        )
    preview_html = ""
    if note.image_path:
        preview_html = (
            f'<a class="drawer-note-preview" href="/note?file={html.escape(note.filename)}">'
            f'<img class="drawer-note-preview-image" src="/media?path={html.escape(note.image_path)}" alt="{html.escape(note.title)}">'
            f"</a>"
        )
    return render_template(
        "components/drawer_note.html",
        {
            "state_label": approval_class,
            "filename": html.escape(note.filename),
            "title": html.escape(note.title),
            "category": html.escape(note.category),
            "preview_html": preview_html,
            "summary": html.escape(note.visual_summary or note.personal_insight or "No summary available."),
            "actions_html": "".join(actions),
            "calendar_html": calendar,
        },
    )


def drawer_button(label: str, onclick: str) -> str:
    return f'<button type="button" class="drawer-action mini" onclick="{html.escape(onclick, quote=True)}">{html.escape(label)}</button>'


def render_row_summary(row: TrackerRow, notes: list[DashboardNote], state: dict[str, Any]) -> str:
    recent_days = [date.today().fromordinal(date.today().toordinal() - offset).isoformat() for offset in range(6, -1, -1)]
    if row.mode == "streak":
        completed = sum(1 for day in recent_days if get_cell_state(state, day, row.id).status == "done")
        return f"{completed}/7 days marked complete this week. Proof accumulates when you keep showing up."
    if row.mode == "analysis":
        linked = sum(len(notes_for_row_and_day(notes, state, day, row.id)) for day in recent_days)
        if row.id == "ai_experiment":
            return f"Weekly workshop read: {linked} attached artifacts in the last 7 days. Notice whether experimentation became protected time or only happened after other work was finished."
        return f"Weekly relationship read: {linked} attached artifacts in the last 7 days. Look for patterns of initiative versus reaction, and whether attention is clustered or sustained."
    if row.mode == "todo":
        return "This row expands to hold lightweight planning. Keep it tactical, not existential."
    return "One main color plus evidence-backed artifacts. Suggestions stay amber until you decide."


def render_weekly_analysis_cards(notes: list[DashboardNote], config: DashboardConfig, state: dict[str, Any]) -> str:
    cards: list[str] = []
    for row_id in ("ai_experiment", "relationship"):
        row = row_lookup(config).get(row_id)
        if row is None:
            continue
        cards.append(f'<article class="weekly-card"><div class="drawer-group-label">{html.escape(row.label)}</div><p>{html.escape(render_row_summary(row, notes, state))}</p></article>')
    return f'<section class="weekly-analysis">{"".join(cards)}</section>'


STATUS_COLORS = {
    "done": "#3ca86b",
    "excused": "#98d88a",
    "oops": "#9fc7f8",
    "missed": "#4969c9",
    "scheduled": "#d5b15b",
    "": "#f5efe4",
}


def mobile_media_url(path: str) -> str:
    """Return a server-relative media URL for a local file path."""
    if not path:
        return ""
    return f"/media?path={path}"


def build_mobile_cell_payload(
    slice_item: TimeSlice,
    row: TrackerRow,
    notes: list[DashboardNote],
    state: dict[str, Any],
    todos: list[TodoItem],
) -> dict[str, Any]:
    """Build one cell payload for the mobile client."""
    if slice_item.kind == "week":
        status = summarize_status_for_days(row.id, slice_item.days, notes, state, todos)
        matching_notes = [
            note
            for note in notes
            if any(normalize_day(item) in slice_item.days for item in (note.linked_dates or [note.date]))
            and row.id in (note.tracker_rows or [note.tracker_row] or [get_assignment(note, state).row_id])
            and not get_assignment(note, state).archived
        ]
        first_with_media = next((item for item in matching_notes if item.image_path), None)
        todo_count = len(
            [item for item in todos if item.suggested_row_id == row.id and item.suggested_day in slice_item.days and not item.done]
        )
        return {
            "key": slice_item.key,
            "status": status,
            "statusColor": STATUS_COLORS.get(status, STATUS_COLORS[""]),
            "note": "",
            "summary": "",
            "artifactCount": len(matching_notes),
            "todoCount": todo_count,
            "thumbnailUrl": mobile_media_url(first_with_media.image_path) if first_with_media else "",
            "days": slice_item.days,
            "editable": False,
        }

    day_key = slice_item.days[0]
    status = derived_cell_status(day_key, row.id, notes, state)
    summary = derived_cell_summary(day_key, row.id, notes, state)
    cell_notes = notes_for_row_and_day(notes, state, day_key, row.id)
    cell_todos = todos_for_cell(day_key, row.id, todos)
    first_with_media = next((item for item in cell_notes if item.image_path), None)
    return {
        "key": day_key,
        "status": status,
        "statusColor": STATUS_COLORS.get(status, STATUS_COLORS[""]),
        "note": get_cell_state(state, day_key, row.id).note,
        "summary": summary,
        "artifactCount": len(cell_notes),
        "todoCount": len(cell_todos),
        "thumbnailUrl": mobile_media_url(first_with_media.image_path) if first_with_media else "",
        "days": [day_key],
        "editable": True,
    }


def serialize_note_for_mobile(note: DashboardNote, state: dict[str, Any]) -> dict[str, Any]:
    """Serialize one artifact for the mobile client."""
    assignment = get_assignment(note, state)
    return {
        "filename": note.filename,
        "title": note.title,
        "category": note.category,
        "visualSummary": note.visual_summary,
        "personalInsight": note.personal_insight,
        "imageUrl": mobile_media_url(note.image_path),
        "trackerRow": note.tracker_row,
        "trackerRows": note.tracker_rows,
        "linkedDates": note.linked_dates,
        "futureDates": note.future_dates,
        "calendarOffer": note.calendar_offer,
        "calendarTitle": note.calendar_title,
        "calendarStart": note.calendar_start,
        "calendarEnd": note.calendar_end,
        "calendarLocation": note.calendar_location,
        "calendarDetails": note.calendar_details,
        "actionItems": note.action_items,
        "assignment": {
            "rowId": assignment.row_id,
            "approved": assignment.approved,
            "highlighted": assignment.highlighted,
            "archived": assignment.archived,
            "saveForLater": assignment.save_for_later,
            "label": assignment.label,
        },
    }


def build_mobile_snapshot(
    notes: list[DashboardNote],
    tasks: list[str],
    config: DashboardConfig,
    state: dict[str, Any],
    selected_day: str,
) -> dict[str, Any]:
    """Build a normalized command-desk payload for the iOS client."""
    slices = build_command_window(selected_day)
    todos = load_todos(state)
    groups_payload: list[dict[str, Any]] = []
    for group in config.groups:
        rows_payload: list[dict[str, Any]] = []
        for row in group.rows:
            cells = [build_mobile_cell_payload(slice_item, row, notes, state, todos) for slice_item in slices]
            row_artifacts = [
                serialize_note_for_mobile(note, state)
                for note in notes_for_row_and_day(notes, state, selected_day, row.id)
            ]
            row_todos = [
                todo_to_dict(item)
                for item in todos
                if (item.source_day == selected_day or item.suggested_day == selected_day)
                and item.suggested_row_id == row.id
                and not item.done
            ]
            rows_payload.append(
                {
                    "id": row.id,
                    "label": row.label,
                    "mode": row.mode,
                    "capacityHours": row.capacity_hours,
                    "cells": cells,
                    "artifacts": row_artifacts,
                    "todos": row_todos,
                }
            )
        groups_payload.append(
            {
                "id": group.id,
                "label": group.label,
                "color": group.color,
                "rows": rows_payload,
            }
        )
    day_artifacts = [
        serialize_note_for_mobile(note, state)
        for note in notes
        if selected_day in [normalize_day(item) for item in (note.linked_dates or [note.date])]
        and not get_assignment(note, state).archived
    ]
    return {
        "identity": {
            "inscription": config.identity.inscription,
            "affirmation": config.identity.affirmation,
            "rotatingPhrase": config.identity.rotating_phrase,
            "backgroundCaption": config.identity.background_caption,
            "backgroundImageUrl": mobile_media_url(config.identity.background_image_path),
        },
        "selectedDay": selected_day,
        "slices": [
            {
                "key": slice_item.key,
                "label": slice_item.label,
                "mode": slice_item.mode,
                "kind": slice_item.kind,
                "days": slice_item.days,
                "widthUnits": slice_item.width_units,
            }
            for slice_item in slices
        ],
        "groups": groups_payload,
        "tasks": tasks,
        "dayArtifacts": day_artifacts,
        "todoTypes": TODO_TYPES,
        "timePresets": TIME_PRESETS,
    }


def render_command_desk_script(config: DashboardConfig, selected_day: str, selected_row: str) -> str:
    row_options = "".join(
        f'<option value="{html.escape(row.id)}">{html.escape(row.label)}</option>'
        for row in all_rows(config)
    )
    return f"""
    <dialog id="reassign-dialog" class="calendar-dialog">
      <form method="dialog" class="calendar-dialog-card">
        <div class="eyebrow">Reassign Artifact</div>
        <label>Move to row<select id="reassign-row">{row_options}</select></label>
        <div class="calendar-dialog-actions">
          <button type="button" class="calendar-button" onclick="submitReassign()">Save</button>
          <button type="button" class="dialog-close" onclick="closeReassign()">Close</button>
        </div>
      </form>
    </dialog>
    <script>
      window.VISIONLIFE_UI_STATE = {{
        selectedDay: {json.dumps(selected_day)},
        selectedRow: {json.dumps(selected_row)},
      }};
    </script>
    """


def render_note_detail(note: DashboardNote, dashboard_dir: Path) -> str:
    media_html = (
        f'<img src="/media?path={html.escape(note.image_path)}" alt="{html.escape(note.title)}">'
        if note.image_path
        else ""
    )
    tags_html = "\n".join(f"<li>{html.escape(tag)}</li>" for tag in note.tags)
    calendar_action = render_calendar_button(note)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(note.title)} | VisionLife Ledger</title>
  <style>{BASE_STYLES}</style>
</head>
<body>
  {render_top_menu("dashboard")}
  <main class="shell detail">
    <a class="backlink" href="/">Back to ledger</a>
    <article class="card">
      <div class="media">{media_html}</div>
      <div class="body">
        <div class="meta">
          <span>{html.escape(note.category)}</span>
          <span>{html.escape(note.date)}</span>
        </div>
        <h1 style="font-size: clamp(28px, 4vw, 52px); margin-bottom: 18px;">{html.escape(note.title)}</h1>
        {calendar_action}
        <div class="detail-grid">
          <section>
            <div class="detail-block">
              <h4>Visual Summary</h4>
              <div>{html.escape(note.visual_summary or "No summary available.")}</div>
            </div>
            <div class="detail-block">
              <h4>Personal Insight</h4>
              <div>{html.escape(note.personal_insight or "No personal insight available.")}</div>
            </div>
            <div class="detail-block">
              <h4>Raw Text</h4>
              <pre style="white-space: pre-wrap; margin:0; font: inherit; color: var(--ink);">{html.escape(note.raw_text or "No extracted text.")}</pre>
            </div>
          </section>
          <aside>
            <div class="detail-block">
              <h4>Location Context</h4>
              <div>{html.escape(note.location_context or "No location context available.")}</div>
            </div>
            <div class="detail-block">
              <h4>Primary Objects</h4>
              <div>{html.escape(note.primary_objects or "No primary objects detected.")}</div>
            </div>
            <div class="detail-block">
              <h4>Tags</h4>
              <ul class="tags">{tags_html}</ul>
            </div>
            <div class="detail-block">
              <h4>GPS</h4>
              <div>{html.escape(note.gps_latitude or "null")}, {html.escape(note.gps_longitude or "null")}</div>
            </div>
            <div class="detail-block">
              <h4>Source Note</h4>
              <div>{html.escape(str(note.path.relative_to(dashboard_dir)))}</div>
            </div>
          </aside>
        </div>
      </div>
    </article>
  </main>
  {render_calendar_dialog()}
</body>
</html>"""


def build_artifact_action_items(note: DashboardNote) -> list[str]:
    items = list(note.action_items)
    prompt = infer_calendar_prompt(note)
    if prompt.offer:
        items.append(f"Create calendar event: {prompt.title or note.title}")
    if note.raw_text.strip():
        items.append("Review extracted text for names, dates, or follow-up details.")
    if not items:
        items.append("Reassign or label this artifact for the right tracker row.")
    deduped: list[str] = []
    for item in items:
        if item not in deduped:
            deduped.append(item)
    return deduped


def render_artifact_card(note: DashboardNote, state: dict[str, Any], *, archived_view: bool = False) -> str:
    assignment = get_assignment(note, state)
    calendar_action = render_calendar_button(note)
    action_items = "".join(f"<li>{html.escape(item)}</li>" for item in build_artifact_action_items(note))
    label_html = (
        f'<span class="artifact-label-chip">{html.escape(assignment.label)}</span>'
        if assignment.label
        else '<span class="artifact-label-chip empty">Unlabeled</span>'
    )
    tags_html = "".join(f"<span class=\"artifact-tag\">{html.escape(tag)}</span>" for tag in note.tags[:8])
    linked_dates = ", ".join(note.linked_dates or ([normalize_day(note.date)] if note.date else [])) or "Undated"
    future_dates = ", ".join(note.future_dates) or "None"
    media_html = (
        f'<img class="artifact-card-image" src="/media?path={html.escape(note.image_path)}" alt="{html.escape(note.title)}">'
        if note.image_path
        else '<div class="artifact-card-image empty">No preview</div>'
    )
    return f"""
    <article class="artifact-card">
      <a class="artifact-card-media" href="/note?file={html.escape(note.filename)}">{media_html}</a>
      <div class="artifact-card-body">
        <div class="artifact-card-meta">
          <span>{html.escape(note.category)}</span>
          <span>{html.escape(assignment.row_id)}</span>
          {label_html}
        </div>
        <h2><a href="/note?file={html.escape(note.filename)}">{html.escape(note.title)}</a></h2>
        <div class="artifact-card-dates">Attachs to: {html.escape(linked_dates)} | Future dates: {html.escape(future_dates)}</div>
        <p class="artifact-card-summary">{html.escape(note.visual_summary or note.personal_insight or "No summary available.")}</p>
        <div class="artifact-card-tags">{tags_html}</div>
        <section class="artifact-card-analysis">
          <div class="artifact-card-section-title">Action items</div>
          <ul class="artifact-action-list">{action_items}</ul>
        </section>
        <section class="artifact-card-analysis">
          <div class="artifact-card-section-title">Analysis</div>
          <div class="artifact-card-analysis-copy">{html.escape(note.personal_insight or note.location_context or note.primary_objects or "No analysis available.")}</div>
        </section>
        <div class="artifact-card-actions">
          <button type="button" class="drawer-action mini" onclick="openReassign('{html.escape(note.filename)}')">Reassign</button>
          <button type="button" class="drawer-action mini" onclick="setArtifactLabel('{html.escape(note.filename)}', {json.dumps(assignment.label)})">Label</button>
          <button type="button" class="drawer-action mini" onclick="toggleAssignmentFlag('{html.escape(note.filename)}', 'archived')">{'Unarchive' if archived_view else 'Archive'}</button>
          {calendar_action}
        </div>
      </div>
    </article>
    """


def render_artifact_gallery(
    notes: list[DashboardNote],
    dashboard_dir: Path,
    config: DashboardConfig,
    state: dict[str, Any],
    *,
    archived_view: bool = False,
) -> str:
    image_notes = []
    for note in notes:
        if not note.image_path:
            continue
        assignment = get_assignment(note, state)
        if archived_view and assignment.archived:
            image_notes.append(note)
        elif not archived_view and not assignment.archived:
            image_notes.append(note)
    cards_html = "".join(render_artifact_card(note, state, archived_view=archived_view) for note in image_notes) or '<div class="empty">No image artifacts yet.</div>'
    return render_template(
        "artifact_gallery.html",
        {
            "styles": load_dashboard_css(),
            "artifact_count": str(len(image_notes)),
            "page_copy": (
                "Archived images and frames remain on disk and can be restored into the active workflow."
                if archived_view
                else "Images and frames with their analysis results, queued for sorting and action."
            ),
            "cards_html": cards_html,
            "calendar_dialog": render_calendar_dialog(),
            "bootstrap_script": render_command_desk_script(config, "", ""),
            "script": load_dashboard_js(),
        },
    )


def build_category_options(notes: list[DashboardNote], selected: str = "") -> str:
    categories = sorted({note.category for note in notes if note.category})
    options: list[str] = []
    for category in categories:
        selected_attr = ' selected="selected"' if category == selected else ""
        options.append(f'<option value="{html.escape(category)}"{selected_attr}>{html.escape(category)}</option>')
    return "\n".join(options)


def filter_notes(notes: list[DashboardNote], query: str, category: str, tag: str) -> list[DashboardNote]:
    query_lower = query.strip().lower()
    category_lower = category.strip().lower()
    tag_lower = tag.strip().lower()
    filtered: list[DashboardNote] = []
    for note in notes:
        searchable = " ".join(
            [
                note.title,
                note.visual_summary,
                note.personal_insight,
                note.location_context,
                note.primary_objects,
                note.raw_text,
                " ".join(note.tags),
            ]
        ).lower()
        if query_lower and query_lower not in searchable:
            continue
        if category_lower and note.category.lower() != category_lower:
            continue
        if tag_lower and all(tag_lower not in existing.lower() for existing in note.tags):
            continue
        filtered.append(note)
    return filtered


def _truthy(value: str) -> bool:
    return (value or "").strip().lower() in {"true", "yes", "1"}


def render_calendar_dialog() -> str:
    return """
  <dialog id="calendar-dialog" class="calendar-dialog">
    <form method="dialog" class="calendar-dialog-card">
      <div class="eyebrow">Add To Calendar</div>
      <h3 id="calendar-dialog-heading">Calendar Draft</h3>
      <label>Title<input id="calendar-title" type="text"></label>
      <label>Start<input id="calendar-start" type="text" placeholder="YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS"></label>
      <label>End<input id="calendar-end" type="text" placeholder="Optional"></label>
      <label>Location<input id="calendar-location" type="text"></label>
      <label>Details<textarea id="calendar-details" rows="6"></textarea></label>
      <div class="calendar-evidence" id="calendar-evidence"></div>
      <div class="calendar-dialog-actions">
        <button type="button" class="calendar-button" onclick="openGoogleCalendarDraft()">Open Google Calendar Draft</button>
        <button type="button" class="dialog-close" onclick="closeCalendarDialog()">Close</button>
      </div>
    </form>
  </dialog>
"""


BASE_STYLES = """
    :root {
      --paper: #eee6d8;
      --paper-warm: #e4d8c5;
      --ink: #201b17;
      --ink-soft: #4a433c;
      --wood: #7a5a43;
      --wood-deep: #5a4030;
      --metal: #8e857a;
      --metal-cool: #6f7672;
      --line: #b9aa96;
      --panel: rgba(252, 248, 242, 0.78);
      --panel-strong: rgba(245, 237, 226, 0.92);
      --accent-olive: #66715c;
      --accent-blue: #5a6f7e;
      --shadow: 0 24px 56px rgba(32, 27, 23, 0.1);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Source Serif 4", Georgia, "Iowan Old Style", "Palatino Linotype", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 0% 0%, rgba(90,111,126,0.08), transparent 28%),
        radial-gradient(circle at 100% 0%, rgba(102,113,92,0.07), transparent 24%),
        linear-gradient(180deg, #f4ecdf 0%, var(--paper) 100%);
    }
    .shell {
      max-width: 1440px;
      margin: 0 auto;
      padding: 112px 28px 56px;
    }
    .frame {
      border: 1px solid rgba(90, 64, 48, 0.34);
      background:
        linear-gradient(180deg, rgba(255,255,255,0.15), rgba(255,255,255,0.06)),
        var(--paper);
      padding: 20px;
      box-shadow: inset 0 0 0 12px rgba(228,216,197,0.68), var(--shadow);
    }
    .top-header {
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      z-index: 1000;
      padding: 14px 28px 12px;
      background: rgba(238, 230, 216, 0.96);
      border-bottom: 1px solid rgba(90, 64, 48, 0.22);
      box-shadow: 0 10px 24px rgba(32, 27, 23, 0.08);
    }
    .top-header-label {
      max-width: 1440px;
      margin: 0 auto 10px;
      color: var(--ink);
      font-size: 13px;
      letter-spacing: 0.14em;
      text-transform: uppercase;
    }
    .top-menu {
      max-width: 1440px;
      margin: 0 auto;
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      padding: 14px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.72);
      box-shadow: var(--shadow);
    }
    .menu-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 44px;
      padding: 11px 16px;
      text-decoration: none;
      color: var(--ink);
      font-size: 14px;
      letter-spacing: 0.04em;
      background: rgba(244, 236, 224, 0.88);
      border: 1px solid rgba(90, 64, 48, 0.35);
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.32);
    }
    .menu-link:hover {
      border-color: var(--wood);
      background: rgba(255,255,255,0.92);
    }
    .menu-link.active {
      color: var(--ink);
      border-color: var(--wood-deep);
      background: rgba(230, 218, 198, 0.95);
    }
    .calendar-action {
      margin: 14px 0 16px;
      display: grid;
      gap: 8px;
      align-items: start;
    }
    .calendar-button,
    .dialog-close {
      appearance: none;
      border: 1px solid rgba(90, 64, 48, 0.4);
      background: rgba(244, 236, 224, 0.92);
      color: var(--ink);
      min-height: 42px;
      padding: 10px 14px;
      font: inherit;
      cursor: pointer;
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.32);
    }
    .calendar-button:hover,
    .dialog-close:hover {
      background: rgba(255,255,255,0.94);
      border-color: var(--wood);
    }
    .calendar-reason {
      color: var(--ink-soft);
      font-size: 14px;
      line-height: 1.45;
    }
    .calendar-dialog {
      border: none;
      padding: 0;
      background: transparent;
      max-width: 720px;
      width: calc(100% - 32px);
    }
    .calendar-dialog::backdrop {
      background: rgba(32, 27, 23, 0.32);
    }
    .calendar-dialog-card {
      display: grid;
      gap: 12px;
      padding: 24px;
      border: 1px solid var(--line);
      background: var(--panel-strong);
      box-shadow: var(--shadow);
    }
    .calendar-dialog-card h3 {
      margin: 0;
      font-size: clamp(28px, 3vw, 40px);
    }
    .calendar-dialog-card label {
      display: grid;
      gap: 6px;
      color: var(--ink-soft);
      font-size: 14px;
      letter-spacing: 0.03em;
    }
    .calendar-dialog-card input,
    .calendar-dialog-card textarea {
      width: 100%;
      padding: 12px 14px;
      border: 1px solid rgba(90, 64, 48, 0.28);
      background: rgba(255,255,255,0.78);
      color: var(--ink);
      font: inherit;
    }
    .calendar-dialog-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      justify-content: flex-start;
    }
    .calendar-evidence {
      color: var(--accent-blue);
      line-height: 1.5;
    }
    .masthead {
      display: grid;
      grid-template-columns: 1.65fr 0.88fr;
      gap: 24px;
      margin-bottom: 26px;
    }
    .title-panel, .tasks-panel, .card, .lead-note, .manifesto, .reference, .filters {
      background: var(--panel);
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
    }
    .title-panel { padding: 32px; }
    .hero-panel {
      position: relative;
      overflow: hidden;
      min-height: 390px;
      display: flex;
      flex-direction: column;
      justify-content: flex-end;
      background:
        linear-gradient(180deg, rgba(255,255,255,0.24), rgba(255,255,255,0.08)),
        linear-gradient(135deg, rgba(122,90,67,0.09), transparent 48%),
        var(--panel-strong);
    }
    .hero-metric {
      position: absolute;
      top: -22px;
      right: 18px;
      font-size: clamp(110px, 18vw, 240px);
      line-height: 0.9;
      color: rgba(126, 112, 96, 0.24);
      font-weight: 700;
      letter-spacing: -0.08em;
      text-shadow: 1px 1px 0 rgba(255,255,255,0.24);
    }
    .eyebrow {
      font-size: 12px;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      color: var(--ink-soft);
      margin-bottom: 14px;
    }
    h1 {
      font-size: clamp(34px, 5vw, 76px);
      line-height: 0.94;
      margin: 0 0 12px;
      font-weight: 500;
      max-width: 10ch;
    }
    .subtitle {
      max-width: 60ch;
      color: var(--ink-soft);
      font-size: 17px;
      line-height: 1.72;
    }
    .hero-rule {
      width: 148px;
      height: 1px;
      margin: 22px 0 16px;
      background: linear-gradient(90deg, var(--wood-deep), transparent);
    }
    .hero-microcopy {
      max-width: 56ch;
      color: var(--ink-soft);
      font-size: 13px;
      line-height: 1.62;
      text-transform: none;
    }
    .tasks-panel {
      padding: 24px;
      align-self: start;
      background:
        linear-gradient(180deg, rgba(255,255,255,0.2), rgba(255,255,255,0.08)),
        var(--panel);
    }
    .tasks-panel h2 { margin: 0 0 12px; font-size: 18px; font-weight: 600; }
    .tasks-panel ul { margin: 0; padding-left: 18px; color: var(--ink-soft); line-height: 1.72; }
    .manifesto {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 0;
      margin-bottom: 18px;
      background: linear-gradient(180deg, rgba(255,255,255,0.18), rgba(255,255,255,0.05)), var(--panel);
    }
    .manifesto-block {
      padding: 20px 18px 18px;
      min-height: 182px;
      border-right: 1px solid rgba(185,170,150,0.6);
    }
    .manifesto-block:last-child { border-right: 0; }
    .manifesto-block p {
      margin: 0;
      color: var(--ink-soft);
      line-height: 1.65;
      font-size: 14px;
    }
    .manifesto-source {
      color: var(--accent-olive);
      font-style: italic;
    }
    .guidance-panel {
      margin-top: 18px;
      padding-top: 16px;
      border-top: 1px solid var(--line);
    }
    .guidance-copy {
      color: var(--ink-soft);
      line-height: 1.62;
      font-size: 14px;
    }
    .guidance-list {
      margin: 12px 0 0;
      padding-left: 18px;
      color: var(--ink-soft);
      line-height: 1.55;
    }
    .palette-line {
      margin-top: 12px;
      color: var(--accent-olive);
      font-size: 12px;
      letter-spacing: 0.04em;
    }
    .reference-strip {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 14px;
      margin-bottom: 22px;
    }
    .timeline {
      margin-bottom: 22px;
      padding: 16px 18px 18px;
      background: linear-gradient(180deg, rgba(255,255,255,0.18), rgba(255,255,255,0.05)), var(--panel);
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
    }
    .timeline-header {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: baseline;
      margin-bottom: 12px;
    }
    .timeline-copy {
      color: var(--ink-soft);
      font-size: 13px;
      line-height: 1.5;
    }
    .timeline-track {
      display: flex;
      gap: 8px;
      align-items: stretch;
      overflow-x: auto;
      padding-bottom: 2px;
    }
    .timeline-segment {
      min-width: 88px;
      padding: 12px 10px 10px;
      text-decoration: none;
      color: inherit;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.34);
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      gap: 8px;
    }
    .timeline-label {
      font-size: 11px;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--ink-soft);
    }
    .timeline-title {
      font-size: 14px;
      line-height: 1.35;
      color: var(--ink);
    }
    .reference {
      margin: 0;
      background: rgba(255,255,255,0.24);
    }
    .reference-media {
      aspect-ratio: 1 / 0.7;
      background: #d9cfbf;
      overflow: hidden;
      border-bottom: 1px solid var(--line);
    }
    .reference-media img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }
    .reference figcaption {
      padding: 12px;
    }
    .reference-title {
      font-size: 13px;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      color: var(--ink);
      margin-bottom: 6px;
    }
    .reference-copy {
      color: var(--ink-soft);
      line-height: 1.5;
      font-size: 13px;
    }
    .ledger {
      display: grid;
      grid-template-columns: 1.06fr 0.94fr;
      gap: 24px;
      align-items: start;
    }
    .archive-column { min-width: 0; }
    .grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 22px;
    }
    .time-slice {
      position: relative;
      min-width: 0;
    }
    .time-label {
      margin: 0 0 8px;
      font-size: 11px;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      color: var(--ink-soft);
    }
    .time-slice.past .time-label,
    .timeline-segment.past .timeline-label { color: var(--metal-cool); }
    .time-slice.future .time-label,
    .timeline-segment.future .timeline-label { color: var(--accent-blue); }
    .time-slice.today .time-label,
    .timeline-segment.today .timeline-label { color: var(--accent-olive); }
    .time-slice.today .card,
    .time-slice.today .lead-note,
    .timeline-segment.today {
      background: rgba(244, 236, 224, 0.82);
      border-color: var(--wood);
    }
    .time-slice.past-distant,
    .timeline-segment.past-distant { opacity: 0.78; }
    .time-slice.past-recent,
    .timeline-segment.past-recent { opacity: 0.88; }
    .time-slice.past-week,
    .timeline-segment.past-week { opacity: 0.96; }
    .time-slice.active-moment .card,
    .time-slice.active-moment .lead-note,
    .timeline-segment.active-moment {
      box-shadow: 0 0 0 1px rgba(122,90,67,0.3), var(--shadow);
    }
    .artifact-frame {
      padding: 14px;
      border: 2px solid var(--wood);
      background: rgba(244, 236, 224, 0.4);
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.36);
    }
    .artifact-frame.touchpoint-frame {
      border-color: var(--metal);
      background: rgba(236, 238, 237, 0.5);
      box-shadow:
        inset 0 0 0 1px rgba(255,255,255,0.42),
        inset 0 0 0 8px rgba(142,133,122,0.08);
    }
    .artifact-frame.spiritual-frame {
      border-color: var(--wood);
      background: rgba(244, 236, 224, 0.44);
    }
    .filters {
      display: grid;
      grid-template-columns: 1.2fr 0.9fr 0.9fr auto;
      gap: 12px;
      margin-bottom: 22px;
      padding: 16px;
    }
    .filters input, .filters select {
      width: 100%;
      padding: 11px 12px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.55);
      color: var(--ink);
      font: inherit;
    }
    .filters button, .filters a {
      padding: 11px 14px;
      border: 1px solid var(--ink);
      background: transparent;
      color: var(--ink);
      text-decoration: none;
      font: inherit;
      cursor: pointer;
    }
    .lead-note, .card {
      overflow: hidden;
      position: relative;
      background:
        linear-gradient(180deg, rgba(255,255,255,0.28), rgba(255,255,255,0.12)),
        var(--panel);
    }
    .lead-note::before, .card::before {
      content: "";
      position: absolute;
      inset: 12px;
      border: 1px solid rgba(185,171,149,0.38);
      pointer-events: none;
    }
    .lead-note {
      display: grid;
      grid-template-columns: 1fr;
    }
    .lead-note-media {
      height: 420px;
      background: #ded2c1;
      border-bottom: 1px solid var(--line);
    }
    .lead-note-media img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }
    .lead-note-body {
      padding: 26px;
    }
    .lead-note h2 {
      margin: 0 0 14px;
      font-size: clamp(30px, 3.5vw, 52px);
      line-height: 0.98;
      font-weight: 500;
      max-width: 13ch;
    }
    .lead-summary {
      margin: 0 0 18px;
      font-size: 18px;
      line-height: 1.72;
      color: var(--ink);
    }
    .insight-panel {
      margin: 0 0 20px;
      padding: 18px;
      border: 1px solid rgba(185,170,150,0.7);
      background: rgba(244, 236, 224, 0.56);
    }
    .insight-panel p {
      margin: 8px 0 0;
      color: var(--ink-soft);
      line-height: 1.72;
    }
    .insight-label, .support-label {
      font-size: 12px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--ink-soft);
    }
    .lead-support {
      display: grid;
      grid-template-columns: 1fr;
      gap: 16px;
    }
    .support-block {
      padding-top: 14px;
      border-top: 1px solid rgba(185,170,150,0.7);
      color: var(--ink-soft);
      line-height: 1.62;
    }
    .card {
      min-height: 100%;
    }
    .media { height: 240px; background: #ded2c1; border-bottom: 1px solid var(--line); }
    .media img { width: 100%; height: 100%; object-fit: cover; display: block; }
    .body { padding: 22px; }
    .meta {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--ink-soft);
      margin-bottom: 12px;
    }
    .card h3 { margin: 0 0 10px; font-size: 26px; font-weight: 500; }
    .summary { color: var(--ink); line-height: 1.55; margin-bottom: 14px; }
    .insight {
      padding-top: 14px;
      border-top: 1px solid var(--line);
      color: var(--ink-soft);
      line-height: 1.62;
      font-size: 15px;
    }
    .card.marginal .media { height: 180px; }
    .card.marginal h3 { font-size: 22px; }
    .card.marginal .summary, .card.marginal .insight { font-size: 14px; }
    .tags {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 14px 0 0;
      padding: 0;
      list-style: none;
    }
    .tags li {
      border: 1px solid var(--line);
      padding: 6px 10px;
      font-size: 12px;
      color: var(--accent-olive);
      background: rgba(255,255,255,0.36);
    }
    .footer { margin-top: 22px; color: var(--ink-soft); font-size: 13px; }
    .detail { max-width: 980px; margin: 0 auto; }
    .detail .card { overflow: visible; }
    .detail .media { height: auto; max-height: 560px; }
    .detail .media img { object-fit: contain; background: #d9cfbf; }
    .detail-grid { display: grid; grid-template-columns: 1.2fr 0.8fr; gap: 22px; }
    .detail-block {
      padding: 18px;
      background: rgba(255,255,255,0.28);
      border: 1px solid var(--line);
      margin-top: 18px;
    }
    .detail-block h4 {
      margin: 0 0 10px;
      font-size: 14px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--ink-soft);
    }
    .backlink { display: inline-block; margin-bottom: 18px; color: var(--accent-blue); text-decoration: none; }
    .empty { padding: 42px; border: 1px dashed var(--line); color: var(--ink-soft); text-align: center; }
    @media (max-width: 900px) {
      .masthead { grid-template-columns: 1fr; }
      .manifesto { grid-template-columns: 1fr 1fr; }
      .ledger { grid-template-columns: 1fr; }
      .timeline-header { display: block; }
      .top-header { padding: 12px 16px 10px; }
      .top-menu { gap: 8px; padding: 10px; }
      .menu-link { font-size: 12px; min-height: 40px; padding: 10px 12px; }
      .shell { padding: 16px; }
      .shell { padding-top: 116px; }
      .frame { padding: 12px; }
      .reference-strip { grid-template-columns: 1fr 1fr; }
      .filters { grid-template-columns: 1fr; }
      .grid { grid-template-columns: 1fr; }
      .lead-note-media { height: 280px; }
      .detail-grid { grid-template-columns: 1fr; }
    }
"""


COMMAND_DESK_STYLES = """
    .command-desk-body {
      min-height: 100vh;
      background:
        radial-gradient(circle at 15% 20%, rgba(90,111,126,0.08), transparent 30%),
        linear-gradient(180deg, #efe6d7 0%, #e5dac8 100%);
      overflow-x: auto;
    }
    .desk-shell {
      max-width: 1800px;
      margin: 0 auto;
      padding: 28px;
      position: relative;
    }
    .desk-background {
      position: absolute;
      inset: 0;
      pointer-events: none;
      overflow: hidden;
    }
    .background-art {
      position: absolute;
      right: -4%;
      top: 2%;
      width: min(42vw, 760px);
      opacity: 0.12;
      filter: grayscale(1) contrast(1.08);
      mix-blend-mode: multiply;
    }
    .background-caption {
      position: absolute;
      right: 6%;
      top: 52%;
      font-size: clamp(52px, 8vw, 140px);
      letter-spacing: -0.04em;
      color: rgba(32,27,23,0.08);
      font-weight: 700;
    }
    .desk-frame {
      position: relative;
      border: 1px solid rgba(90,64,48,0.36);
      background: linear-gradient(180deg, rgba(255,255,255,0.18), rgba(255,255,255,0.06)), var(--paper);
      box-shadow: inset 0 0 0 12px rgba(255,255,255,0.16), var(--shadow);
      padding: 30px;
    }
    .desk-header {
      display: grid;
      gap: 8px;
      margin-bottom: 24px;
      position: relative;
      z-index: 2;
    }
    .command-inscription {
      color: var(--wood-deep);
      text-transform: uppercase;
      letter-spacing: 0.16em;
      font-size: 13px;
    }
    .command-affirmation {
      font-size: clamp(40px, 5vw, 72px);
      color: #0b9c4a;
      line-height: 0.95;
      width: fit-content;
    }
    .command-rotating-wrap {
      display: flex;
      align-items: center;
      gap: 12px;
      width: fit-content;
      position: relative;
    }
    .command-rotating {
      font-size: 24px;
      color: var(--ink-soft);
      border-bottom: 1px solid transparent;
      min-width: 220px;
    }
    .editable-text:focus {
      outline: 1px dashed rgba(90,64,48,0.45);
      background: rgba(255,255,255,0.44);
    }
    .edit-hover-button {
      opacity: 0;
      transition: opacity 120ms ease;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.88);
      padding: 8px 10px;
      font: inherit;
      cursor: pointer;
    }
    .command-rotating-wrap:hover .edit-hover-button,
    .tracker-group:hover .edit-hover-button {
      opacity: 1;
    }
    .command-timeline {
      margin-bottom: 26px;
      position: relative;
      z-index: 2;
    }
    .command-timeline-copy {
      margin-bottom: 10px;
      color: var(--ink-soft);
      letter-spacing: 0.08em;
      text-transform: uppercase;
      font-size: 12px;
    }
    .command-timeline-track {
      display: flex;
      gap: 10px;
      overflow-x: auto;
      padding-bottom: 8px;
    }
    .command-timeline-segment {
      min-width: 88px;
      padding: 12px 14px;
      text-decoration: none;
      color: inherit;
      border: 1px solid rgba(90,64,48,0.24);
      background: rgba(255,255,255,0.44);
      display: grid;
      gap: 4px;
    }
    .command-timeline-segment.selected {
      border-color: var(--wood-deep);
      background: rgba(255,255,255,0.76);
      box-shadow: 0 10px 20px rgba(32,27,23,0.08);
    }
    .timeline-day {
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--ink-soft);
    }
    .timeline-date {
      font-size: 16px;
    }
    .desk-main {
      display: grid;
      grid-template-columns: minmax(980px, 1fr) 390px;
      gap: 22px;
      align-items: start;
      position: relative;
      z-index: 2;
    }
    .tracker-panel {
      min-width: 980px;
    }
    .tracker-grid-shell {
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.48);
      box-shadow: var(--shadow);
      overflow: hidden;
    }
    .tracker-grid-header {
      display: grid;
      grid-template-columns: 220px 1fr;
      border-bottom: 1px solid var(--line);
      background: rgba(255,255,255,0.55);
    }
    .tracker-spacer {
      padding: 16px;
      text-transform: uppercase;
      letter-spacing: 0.14em;
      font-size: 12px;
      color: var(--ink-soft);
    }
    .day-columns,
    .row-cells {
      display: flex;
      min-width: 0;
    }
    .day-column-head {
      min-height: 72px;
      padding: 14px 10px;
      border-left: 1px solid rgba(90,64,48,0.15);
      display: grid;
      align-content: end;
      gap: 2px;
      font-size: 14px;
      min-width: 10px;
    }
    .day-column-head.selected {
      background: rgba(255,255,255,0.82);
    }
    .day-column-head.focus { min-width: 240px; }
    .day-column-head.near { min-width: 132px; }
    .day-column-head.compressed { min-width: 64px; padding-left: 6px; padding-right: 6px; }
    .day-column-head.week-band { min-width: 44px; padding-left: 4px; padding-right: 4px; }
    .day-date {
      color: var(--ink-soft);
      font-size: 12px;
    }
    .tracker-group {
      display: grid;
      grid-template-columns: 220px 1fr;
      border-top: 1px solid rgba(90,64,48,0.14);
    }
    .group-label {
      padding: 18px 14px;
      border-right: 1px solid rgba(90,64,48,0.16);
      background: color-mix(in srgb, var(--group-color) 72%, white);
      font-size: 18px;
      font-weight: 600;
    }
    .tracker-row {
      display: contents;
    }
    .row-label {
      padding: 14px;
      border-right: 1px solid rgba(90,64,48,0.14);
      border-top: 1px solid rgba(90,64,48,0.12);
      background: rgba(255,255,255,0.38);
      display: flex;
      align-items: center;
      font-size: 16px;
    }
    .tracker-cell {
      min-height: 76px;
      border-left: 1px solid rgba(90,64,48,0.12);
      border-top: 1px solid rgba(90,64,48,0.12);
      text-decoration: none;
      color: inherit;
      background: rgba(255,255,255,0.18);
      position: relative;
      padding: 8px;
      min-width: 10px;
    }
    .tracker-cell.focus { min-width: 240px; }
    .tracker-cell.near { min-width: 132px; }
    .tracker-cell.compressed { min-width: 64px; padding: 6px 5px; }
    .tracker-cell.week-band { min-width: 44px; padding: 3px 2px; }
    .tracker-cell.compressed .cell-note-preview,
    .tracker-cell.week-band .cell-note-preview { display: none; }
    .tracker-cell.week-band .artifact-strip,
    .tracker-cell.week-band .cell-calendar-button { display: none; }
    .tracker-cell.week-band .cell-inner { display: flex; justify-content: center; align-items: center; }
    .tracker-cell.selected {
      box-shadow: inset 0 0 0 2px var(--wood-deep);
      background: rgba(255,255,255,0.86);
    }
    .tracker-cell.status-done { background: rgba(52, 175, 90, 0.24); }
    .tracker-cell.status-excused { background: rgba(155, 214, 129, 0.24); }
    .tracker-cell.status-oops { background: rgba(133, 186, 224, 0.28); }
    .tracker-cell.status-missed { background: rgba(72, 114, 168, 0.26); }
    .tracker-cell.status-scheduled { background: rgba(233, 181, 79, 0.22); }
    .cell-inner {
      display: grid;
      grid-template-columns: auto 1fr auto;
      align-items: start;
      gap: 6px;
      min-height: 100%;
    }
    .artifact-count {
      font-size: 11px;
      color: var(--ink-soft);
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }
    .artifact-strip {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
      align-self: center;
    }
    .cell-note-preview {
      grid-column: 1 / -1;
      font-size: 11px;
      line-height: 1.3;
      color: var(--ink-soft);
      margin-top: 4px;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
    .artifact-chip {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 20px;
      height: 20px;
      border-radius: 999px;
      font-size: 12px;
      border: 1px solid rgba(90,64,48,0.22);
    }
    .artifact-chip.approved {
      background: rgba(255,255,255,0.84);
      color: var(--ink);
    }
    .artifact-chip.provisional {
      background: rgba(233, 181, 79, 0.2);
      color: #8e5e00;
      border-color: rgba(186, 138, 36, 0.5);
    }
    .cell-calendar-button {
      border: 1px solid rgba(90,64,48,0.24);
      background: rgba(255,255,255,0.88);
      color: var(--ink);
      width: 24px;
      height: 24px;
      cursor: pointer;
      font: inherit;
    }
    .right-drawer {
      position: sticky;
      top: 22px;
      padding: 20px;
      border: 1px solid var(--line);
      background: rgba(254,250,244,0.94);
      box-shadow: var(--shadow);
      max-height: calc(100vh - 44px);
      overflow-y: auto;
    }
    .drawer-overline,
    .drawer-group-label {
      color: var(--ink-soft);
      text-transform: uppercase;
      letter-spacing: 0.12em;
      font-size: 12px;
    }
    .drawer-head h2 {
      margin: 6px 0 4px;
      font-size: 38px;
      line-height: 0.95;
    }
    .drawer-subline,
    .drawer-summary {
      color: var(--ink-soft);
      line-height: 1.5;
    }
    .status-controls {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 16px 0;
    }
    .status-chip {
      border: 1px solid rgba(90,64,48,0.22);
      background: rgba(255,255,255,0.72);
      padding: 8px 10px;
      cursor: pointer;
      font: inherit;
    }
    .status-chip.active { box-shadow: inset 0 0 0 2px rgba(32,27,23,0.18); }
    .status-chip.done { background: rgba(52, 175, 90, 0.22); }
    .status-chip.excused { background: rgba(155, 214, 129, 0.22); }
    .status-chip.oops { background: rgba(133, 186, 224, 0.22); }
    .status-chip.missed { background: rgba(72, 114, 168, 0.22); }
    .drawer-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin: 18px 0;
    }
    .cell-note-editor {
      display: grid;
      gap: 8px;
      margin: 14px 0 16px;
      padding: 14px;
      border: 1px solid rgba(90,64,48,0.16);
      background: rgba(255,255,255,0.42);
    }
    .cell-note-input {
      width: 100%;
      padding: 12px 14px;
      border: 1px solid rgba(90,64,48,0.24);
      background: rgba(255,255,255,0.86);
      color: var(--ink);
      font: inherit;
      resize: vertical;
    }
    .cell-note-actions {
      display: flex;
      justify-content: flex-start;
    }
    .drawer-action {
      border: 1px solid rgba(90,64,48,0.22);
      background: rgba(255,255,255,0.86);
      padding: 10px 12px;
      cursor: pointer;
      font: inherit;
    }
    .drawer-action.mini,
    .mini-calendar {
      padding: 7px 10px;
      font-size: 13px;
    }
    .drawer-stream {
      display: grid;
      gap: 14px;
      margin-top: 16px;
    }
    .drawer-note {
      border: 1px solid rgba(90,64,48,0.16);
      background: rgba(255,255,255,0.46);
      padding: 14px;
      display: grid;
      gap: 8px;
    }
    .drawer-note.provisional { border-left: 4px solid #d2a13a; }
    .drawer-note.approved { border-left: 4px solid var(--metal-cool); }
    .drawer-note-head {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: baseline;
    }
    .drawer-note-head a {
      color: var(--ink);
      text-decoration: none;
      font-weight: 600;
    }
    .drawer-note-category {
      color: var(--ink-soft);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    .drawer-note-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .drawer-empty {
      color: var(--ink-soft);
      padding: 18px 0;
      line-height: 1.6;
    }
    .drawer-tasks {
      margin-top: 18px;
      border-top: 1px solid rgba(90,64,48,0.18);
      padding-top: 16px;
    }
    .weekly-analysis {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
      margin-top: 16px;
    }
    .weekly-card {
      border: 1px solid rgba(90,64,48,0.16);
      background: rgba(255,255,255,0.44);
      padding: 16px;
    }
    .desk-footer {
      margin-top: 16px;
      color: var(--ink-soft);
      font-size: 12px;
      letter-spacing: 0.06em;
    }
    @media (max-width: 1400px) {
      .desk-main { grid-template-columns: 1fr; }
      .right-drawer { position: relative; top: 0; max-height: none; }
      .tracker-panel { min-width: 0; overflow-x: auto; }
    }
    @media (max-width: 860px) {
      .desk-shell { padding: 12px; }
      .desk-frame { padding: 16px; }
      .background-art { width: 70vw; opacity: 0.08; }
      .weekly-analysis { grid-template-columns: 1fr; }
      .tracker-grid-header,
      .tracker-group { grid-template-columns: 150px 1fr; }
      .day-column-head.focus, .tracker-cell.focus { min-width: 180px; }
      .day-column-head.near, .tracker-cell.near { min-width: 110px; }
      .day-column-head.compressed, .tracker-cell.compressed { min-width: 52px; }
      .day-column-head.week-band, .tracker-cell.week-band { min-width: 34px; }
      .command-affirmation { font-size: 42px; }
    }
"""


def build_handler(
    dashboard_dir: Path,
    research_file: Path,
    config_file: Path,
    state_file: Path,
    inbox_dir: Path,
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/media":
                self.serve_media(parse_qs(parsed.query))
                return
            if parsed.path == "/api/mobile/dashboard":
                self.serve_mobile_dashboard(parse_qs(parsed.query))
                return
            if parsed.path == "/artifacts":
                self.serve_artifacts(archived_view=False)
                return
            if parsed.path == "/archived":
                self.serve_artifacts(archived_view=True)
                return
            if parsed.path == "/note":
                self.serve_note(parse_qs(parsed.query))
                return

            query = parse_qs(parsed.query)
            raw_notes = load_dashboard_notes(dashboard_dir)
            research_assets = load_research_assets(research_file)
            config = load_dashboard_config(config_file, research_assets)
            state = load_dashboard_state(state_file)
            filtered_notes = filter_notes(
                raw_notes,
                query.get("q", [""])[0],
                query.get("category", [""])[0],
                query.get("tag", [""])[0],
            )
            tasks = load_tasks(dashboard_dir / "TASKS.md")
            body = render_command_desk(
                filtered_notes,
                raw_notes,
                tasks,
                dashboard_dir,
                research_assets,
                config,
                state,
                query,
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/mobile/upload":
                self.handle_mobile_upload(parsed)
                return
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            if parsed.path == "/api/config":
                self.handle_config_update(payload)
                return
            if parsed.path == "/api/state":
                self.handle_state_update(payload)
                return
            self.send_error(404, "Unknown endpoint")

        def serve_media(self, query: dict[str, list[str]]) -> None:
            requested = query.get("path", [""])[0]
            path = Path(requested).expanduser()
            if not path.exists() or not path.is_file():
                self.send_error(404, "File not found")
                return

            content = path.read_bytes()
            mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", mime_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def serve_note(self, query: dict[str, list[str]]) -> None:
            filename = query.get("file", [""])[0]
            path = dashboard_dir / filename
            if not path.exists() or not path.is_file():
                self.send_error(404, "Note not found")
                return
            note = parse_dashboard_note(path)
            body = render_note_detail(note, dashboard_dir).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def serve_artifacts(self, *, archived_view: bool) -> None:
            raw_notes = load_dashboard_notes(dashboard_dir)
            research_assets = load_research_assets(research_file)
            config = load_dashboard_config(config_file, research_assets)
            state = load_dashboard_state(state_file)
            body = render_artifact_gallery(raw_notes, dashboard_dir, config, state, archived_view=archived_view).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def serve_mobile_dashboard(self, query: dict[str, list[str]]) -> None:
            raw_notes = load_dashboard_notes(dashboard_dir)
            research_assets = load_research_assets(research_file)
            config = load_dashboard_config(config_file, research_assets)
            state = load_dashboard_state(state_file)
            tasks = load_tasks(dashboard_dir / "TASKS.md")
            selected_day = query.get("day", [""])[0] or build_selected_day(raw_notes, {})
            payload = build_mobile_snapshot(raw_notes, tasks, config, state, selected_day)
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

        def handle_config_update(self, payload: dict[str, Any]) -> None:
            current = json.loads(json.dumps(DEFAULT_CONFIG))
            existing = load_dashboard_config(config_file, load_research_assets(research_file))
            current["identity"]["background_image_path"] = existing.identity.background_image_path
            current["identity"]["background_caption"] = existing.identity.background_caption
            identity = payload.get("identity", {})
            current["identity"]["inscription"] = str(identity.get("inscription") or existing.identity.inscription)
            current["identity"]["affirmation"] = str(identity.get("affirmation") or existing.identity.affirmation)
            current["identity"]["rotating_phrase"] = str(identity.get("rotating_phrase") or existing.identity.rotating_phrase)
            current["groups"] = payload.get("groups", DEFAULT_CONFIG["groups"])
            save_json(config_file, current)
            self.send_response(204)
            self.end_headers()

        def handle_state_update(self, payload: dict[str, Any]) -> None:
            state = load_dashboard_state(state_file)
            kind = payload.get("kind")
            if kind == "cell":
                key = f"{payload.get('day', '')}|{payload.get('row_id', '')}"
                previous = state.setdefault("cells", {}).get(key, {})
                status_value = str(payload.get("status") or "")
                if payload.get("preserve_status"):
                    status_value = str(previous.get("status") or "")
                state.setdefault("cells", {})[key] = {
                    "status": status_value,
                    "note": str(payload.get("note") or ""),
                }
            elif kind == "assignment":
                filename = str(payload.get("filename") or "")
                assignment = state.setdefault("note_assignments", {}).setdefault(filename, {})
                assignment[str(payload.get("field") or "")] = payload.get("value")
            elif kind == "assignment_toggle":
                filename = str(payload.get("filename") or "")
                field = str(payload.get("field") or "")
                assignment = state.setdefault("note_assignments", {}).setdefault(filename, {})
                assignment[field] = not bool(assignment.get(field, False))
            elif kind == "todo_create":
                config = load_dashboard_config(config_file, load_research_assets(research_file))
                todos = load_todos(state)
                todo_type = str(payload.get("type") or "admin")
                text = str(payload.get("text") or "").strip()
                estimate = str(payload.get("estimate") or "30m")
                source_day = str(payload.get("source_day") or date.today().isoformat())
                if text:
                    suggested_row_id = suggested_row_for_todo(text, todo_type, config)
                    row = row_lookup(config).get(suggested_row_id, all_rows(config)[0])
                    suggested_day = suggest_todo_day(source_day, row, estimate, todos)
                    todos.append(
                        TodoItem(
                            id=f"todo-{len(todos) + 1}-{slugify_text(text)[:18]}",
                            source_day=source_day,
                            text=text,
                            type=todo_type,
                            estimate=estimate,
                            suggested_row_id=suggested_row_id,
                            suggested_day=suggested_day,
                        )
                    )
                    state["todos"] = [todo_to_dict(item) for item in todos]
            elif kind == "todo_update":
                todo_id = str(payload.get("id") or "")
                field = str(payload.get("field") or "")
                value = payload.get("value")
                todos = load_todos(state)
                for item in todos:
                    if item.id != todo_id:
                        continue
                    if field == "approved":
                        item.approved = bool(value)
                    elif field == "done":
                        item.done = bool(value)
                    elif field == "suggested_row_id":
                        item.suggested_row_id = str(value or item.suggested_row_id)
                    elif field == "suggested_day":
                        item.suggested_day = str(value or item.suggested_day)
                state["todos"] = [todo_to_dict(item) for item in todos]
            save_json(state_file, state)
            self.send_response(204)
            self.end_headers()

        def handle_mobile_upload(self, parsed: Any) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            content = self.rfile.read(length)
            query = parse_qs(parsed.query)
            requested_name = (
                query.get("filename", [""])[0]
                or self.headers.get("X-Filename", "")
                or f"upload-{datetime.now().strftime('%Y%m%d-%H%M%S')}.bin"
            )
            safe_name = Path(requested_name).name or f"upload-{datetime.now().strftime('%Y%m%d-%H%M%S')}.bin"
            target = inbox_dir / safe_name
            if target.exists():
                stem = target.stem
                suffix = target.suffix
                target = inbox_dir / f"{stem}-{datetime.now().strftime('%Y%m%d-%H%M%S')}{suffix}"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            payload = {
                "filename": target.name,
                "path": str(target),
                "bytes": len(content),
            }
            body = json.dumps(payload).encode("utf-8")
            self.send_response(201)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def main() -> None:
    """Compatibility launcher that defers to the presentation package."""
    from presentation.web.app import main as web_main

    web_main()


if __name__ == "__main__":
    main()
