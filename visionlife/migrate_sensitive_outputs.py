"""Move previously published sensitive outputs into the encrypted ID vault."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from services.sensitivity_service import detect_sensitive_result, protect_sensitive_result


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the sensitive-output migration utility."""
    parser = argparse.ArgumentParser(description="Move sensitive VisionLife outputs into the encrypted ID vault.")
    parser.add_argument("--run-dir", required=True, help="Run directory containing workspace/results and dashboard.")
    parser.add_argument("--delete-public", action="store_true", help="Delete public result/dashboard files after vaulting.")
    return parser.parse_args()


def main() -> None:
    """Scan a prior run directory and migrate sensitive results into protected storage."""
    args = parse_args()
    run_dir = Path(args.run_dir).expanduser().resolve()
    results_dir = run_dir / "workspace" / "results"
    dashboard_dir = run_dir / "dashboard"
    protected = []

    for result_path in sorted(results_dir.glob("*.json")):
        result = json.loads(result_path.read_text(encoding="utf-8"))
        decision = detect_sensitive_result(result)
        if not decision.sensitive:
            continue

        bundle_path = protect_sensitive_result(result, dashboard_dir / "ID", decision)
        protected.append((result_path, bundle_path))

        if args.delete_public:
            result_path.unlink(missing_ok=True)
            note_name = Path(str(result.get("source_path", ""))).stem
            for candidate in dashboard_dir.glob(f"*{note_name.lower()}*.md"):
                candidate.unlink(missing_ok=True)

    for result_path, bundle_path in protected:
        print(f"PROTECTED {result_path.name} -> {bundle_path}")


if __name__ == "__main__":
    main()
