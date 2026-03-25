"""Convenience runner for processing a limited recent batch from the test inbox."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

from records import analysis_record_to_dict
from services.dashboard_service import sync_result_to_dashboard
from services.sensitivity_service import detect_sensitive_result, protect_sensitive_result
from utils import ensure_directory, prepare_media_for_analysis
from vision import VisionAnalyzer, describe_result


SUPPORTED = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".mov", ".mp4", ".pdf"}


async def handle(path: Path, workspace: Path, results_dir: Path, dashboard_dir: Path, analyzer: VisionAnalyzer) -> dict[str, object]:
    """Process one asset through the rich batch flow and return a summary row."""
    prepared = await asyncio.to_thread(prepare_media_for_analysis, path, workspace)
    result = await analyzer.analyze_asset(prepared)
    result_payload = analysis_record_to_dict(result)
    sensitivity = await asyncio.to_thread(detect_sensitive_result, result)
    result_path: Path | None = None
    dashboard_path: Path | None = None
    protected_bundle_path: Path | None = None
    if sensitivity.sensitive:
        protected_bundle_path = await asyncio.to_thread(
            protect_sensitive_result,
            result,
            dashboard_dir / "ID",
            sensitivity,
        )
    else:
        result_path = results_dir / f"{path.stem}.json"
        result_path.write_text(json.dumps(result_payload, indent=2), encoding="utf-8")
        dashboard_path = await asyncio.to_thread(sync_result_to_dashboard, result, dashboard_dir)
    print("DONE", path.name, flush=True)
    print(describe_result(result), flush=True)
    return {
        "source_path": str(path),
        "analysis_path": str(prepared.analysis_path),
        "result_path": str(result_path) if result_path else None,
        "dashboard_path": str(dashboard_path) if dashboard_path else None,
        "protected_bundle_path": str(protected_bundle_path) if protected_bundle_path else None,
        "sensitive": sensitivity.sensitive,
        "sensitivity_reasons": sensitivity.reasons,
        "sensitivity_types": sensitivity.matched_types,
        "category": result_payload.get("vision_result", {}).get("category"),
        "subcategory": result_payload.get("vision_result", {}).get("subcategory"),
        "image_type": result_payload.get("vision_result", {}).get("image_type"),
        "visual_style": result_payload.get("vision_result", {}).get("visual_style"),
        "tags": result_payload.get("vision_result", {}).get("tags"),
        "text_analysis": result_payload.get("vision_result", {}).get("text_analysis"),
        "research": result_payload.get("web_enrichment"),
    }


async def main() -> None:
    """Select recent inbox assets, process them concurrently, and write a run summary."""
    root = Path(__file__).resolve().parent
    inbox = root / "test_inbox"
    run_root = root / os.getenv("VISIONLIFE_RUN_DIR", "rich_run_20260322")
    workspace = run_root / "workspace"
    results_dir = workspace / "results"
    dashboard_dir = run_root / "dashboard"
    summary_path = run_root / "run_summary.json"

    ensure_directory(workspace)
    ensure_directory(results_dir)
    ensure_directory(dashboard_dir)
    ensure_directory(workspace / "prepared")

    files: list[tuple[float, Path]] = []
    for path in inbox.iterdir():
        if path.is_file() and path.suffix.lower() in SUPPORTED:
            st = path.stat()
            birth = getattr(st, "st_birthtime", st.st_ctime)
            files.append((birth, path))

    selected = [path for _, path in sorted(files, reverse=True)[:12]]
    print("SELECTED_BATCH", flush=True)
    for path in selected:
        print(path.name, flush=True)

    analyzer = VisionAnalyzer(model="gpt-5.4", web_model="gpt-5", enable_web_enrichment=True, max_concurrency=4)
    results = await asyncio.gather(*(handle(path, workspace, results_dir, dashboard_dir, analyzer) for path in selected), return_exceptions=True)

    payload: dict[str, object] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "selected_count": len(selected),
        "items": [],
    }

    for path, item in zip(selected, results):
        if isinstance(item, Exception):
            print("FAILED", path.name, repr(item), flush=True)
            payload["items"].append({"source_path": str(path), "error": repr(item)})
        else:
            payload["items"].append(item)

    summary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("SUMMARY", summary_path, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
