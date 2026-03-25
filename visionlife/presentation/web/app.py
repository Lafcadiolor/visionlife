"""HTTP entrypoint for the local VisionLife command-desk dashboard."""

from __future__ import annotations

from http.server import ThreadingHTTPServer
from pathlib import Path

import results_app


def ensure_dashboard_exists(dashboard_dir: Path) -> None:
    """Create the dashboard directory if it is missing."""
    dashboard_dir.mkdir(parents=True, exist_ok=True)


def main() -> None:
    """Launch the local dashboard server using the refactored presentation package.

    Runtime responsibilities here are intentionally narrow:
    1. parse CLI args
    2. resolve local paths
    3. load dashboard inputs
    4. either dump HTML or start the HTTP server

    This file should stay thin. Rendering and state shaping belong elsewhere.
    """
    args = results_app.parse_args()
    dashboard_dir = Path(args.dashboard_dir).expanduser().resolve()
    research_file = Path(args.research_file).expanduser().resolve()
    config_file = Path(args.config_file).expanduser().resolve()
    state_file = Path(args.state_file).expanduser().resolve()
    inbox_dir = Path(args.inbox_dir).expanduser().resolve()
    ensure_dashboard_exists(dashboard_dir)

    notes = results_app.load_dashboard_notes(dashboard_dir)
    tasks = results_app.load_tasks(dashboard_dir / "TASKS.md")
    research_assets = results_app.load_research_assets(research_file)
    config = results_app.load_dashboard_config(config_file, research_assets)
    state = results_app.load_dashboard_state(state_file)

    if args.dump_html:
        print(results_app.render_command_desk(notes, notes, tasks, dashboard_dir, research_assets, config, state, {}))
        return

    server = ThreadingHTTPServer(
        (args.host, args.port),
        results_app.build_handler(dashboard_dir, research_file, config_file, state_file, inbox_dir),
    )
    print(f"VisionLife results app: http://{args.host}:{args.port}")
    print(f"Dashboard source: {dashboard_dir}")
    server.serve_forever()
