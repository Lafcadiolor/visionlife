"""Pipeline coordinator that runs VisionLife assets through explicit processing stages."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from db import HistoryStore
from fast_sort import FastSortService
from records import AnalysisRecord, analysis_record_to_dict
from services.dashboard_service import sync_result_to_dashboard
from services.sensitivity_service import detect_sensitive_result, protect_sensitive_result
from utils import (
    PreparedAsset,
    compute_file_hash,
    ensure_directory,
    prepare_media_for_analysis,
    safe_delete_file,
    wait_for_file_ready,
)
from vision import VisionAnalyzer, describe_result


LOGGER = logging.getLogger("visionlife.pipeline")


@dataclass(slots=True)
class PipelineConfig:
    """Filesystem targets used by the orchestrator when publishing outputs."""
    workspace_dir: Path
    results_dir: Path
    dashboard_dir: Path
    id_dir: Path


@dataclass(slots=True)
class PipelineOutcome:
    """Structured outcome from processing one candidate through the pipeline."""
    status: str
    file_hash: str | None
    candidate: Path
    prepared_asset: PreparedAsset | None = None
    result: AnalysisRecord | None = None
    output_path: Path | None = None
    dashboard_note_path: Path | None = None
    protected_bundle_path: Path | None = None
    failure_reason: str | None = None


class VisionProcessingPipeline:
    """Explicit processing coordinator for file stabilization through publication."""

    def __init__(
        self,
        *,
        config: PipelineConfig,
        analyzer: VisionAnalyzer,
        history_store: HistoryStore,
        fast_sorter: FastSortService | None,
    ) -> None:
        self.config = config
        self.analyzer = analyzer
        self.history_store = history_store
        self.fast_sorter = fast_sorter

    async def process_candidate(self, candidate: Path) -> PipelineOutcome:
        """Run the full pipeline for one candidate path.

        This is the main ingestion spine. The intent is that a reader can follow
        this function top-to-bottom and understand the lifecycle of one file:
        stabilize -> dedupe -> prepare -> fast sort -> analyze -> publish.
        """
        if not await self.stabilize_candidate(candidate):
            LOGGER.warning("File never stabilized, skipping: %s", candidate)
            return PipelineOutcome(status="skipped_unstable", file_hash=None, candidate=candidate)

        file_hash, duplicate_status = await self.dedupe_candidate(candidate)
        if duplicate_status is not None:
            LOGGER.info(
                "Skipping duplicate file %s; hash already seen with status=%s",
                candidate,
                duplicate_status,
            )
            return PipelineOutcome(status="duplicate", file_hash=file_hash, candidate=candidate)

        prepared_asset = await self.prepare_candidate(candidate)
        deleted = await self.apply_fast_sort(candidate, file_hash, prepared_asset)
        if deleted is not None:
            return deleted

        result = await self.analyze_candidate(prepared_asset)
        return await self.publish_result(candidate, file_hash, prepared_asset, result)

    async def stabilize_candidate(self, candidate: Path) -> bool:
        """Wait for a dropped file to stop changing before reading it."""
        return await _to_thread(wait_for_file_ready, candidate)

    async def dedupe_candidate(self, candidate: Path) -> tuple[str, str | None]:
        """Hash the file and short-circuit processing if it was already seen."""
        file_hash = await _to_thread(compute_file_hash, candidate)
        existing = await _to_thread(self.history_store.get, file_hash)
        if existing is None:
            return file_hash, None
        await _to_thread(
            self.history_store.mark_duplicate,
            file_hash,
            candidate,
            f"Duplicate seen again at {candidate}",
        )
        return file_hash, existing.status

    async def prepare_candidate(self, candidate: Path) -> PreparedAsset:
        """Build the normalized analysis asset used by the vision model."""
        return await _to_thread(prepare_media_for_analysis, candidate, self.config.workspace_dir)

    async def apply_fast_sort(
        self,
        candidate: Path,
        file_hash: str,
        prepared_asset: PreparedAsset,
    ) -> PipelineOutcome | None:
        # Fast sort is an early cost-control / junk-filtering gate.
        # If disabled, the candidate simply continues through the pipeline.
        if self.fast_sorter is None:
            return None

        fast_sort_result = await _to_thread(self.fast_sorter.classify, prepared_asset.analysis_path)
        prepared_asset.metadata["fast_sort"] = {
            "label": fast_sort_result.label,
            "confidence": fast_sort_result.confidence,
            "backend": fast_sort_result.backend,
            "metrics": fast_sort_result.metrics,
            "rationale": fast_sort_result.rationale,
        }

        if not fast_sort_result.should_delete:
            return None

        deleted_source = await _to_thread(safe_delete_file, candidate)
        deleted_prepared = True
        if prepared_asset.analysis_path != candidate:
            deleted_prepared = await _to_thread(safe_delete_file, prepared_asset.analysis_path)

        notes = list(prepared_asset.notes)
        notes.append(
            f"Deleted locally after MLX fast-sort labeled it {fast_sort_result.label} at {fast_sort_result.confidence:.2%} confidence."
        )
        await _to_thread(
            self.history_store.upsert,
            file_hash=file_hash,
            source_path=candidate,
            status="deleted_fast_sort",
            analysis_path=prepared_asset.analysis_path,
            fast_sort_label=fast_sort_result.label,
            fast_sort_confidence=fast_sort_result.confidence,
            notes=notes,
            metadata={
                **prepared_asset.metadata,
                "deleted_source": deleted_source,
                "deleted_prepared": deleted_prepared,
            },
        )
        LOGGER.info(
            "Deleted %s after fast-sort classified it as %s at %.2f confidence.",
            candidate,
            fast_sort_result.label,
            fast_sort_result.confidence,
        )
        return PipelineOutcome(
            status="deleted_fast_sort",
            file_hash=file_hash,
            candidate=candidate,
            prepared_asset=prepared_asset,
        )

    async def analyze_candidate(self, prepared_asset: PreparedAsset) -> AnalysisRecord:
        """Call the AI analysis layer for a prepared asset."""
        return await self.analyzer.analyze_asset(prepared_asset)

    async def publish_result(
        self,
        candidate: Path,
        file_hash: str,
        prepared_asset: PreparedAsset,
        result: AnalysisRecord,
    ) -> PipelineOutcome:
        """Persist, protect, and publish a completed analysis result.

        This stage is where the pipeline forks into:
        1. public dashboard/results publication
        2. protected sensitive-vault publication
        """
        sensitivity = await _to_thread(detect_sensitive_result, result)
        output_path: Path | None = None
        dashboard_note_path: Path | None = None
        protected_bundle_path: Path | None = None
        status = "processed"

        if sensitivity.sensitive:
            protected_bundle_path = await _to_thread(
                protect_sensitive_result,
                result,
                self.config.id_dir,
                sensitivity,
            )
            status = "protected_sensitive"
        else:
            output_path = await _to_thread(_save_result, result, self.config.results_dir)
            dashboard_note_path = await _to_thread(
                sync_result_to_dashboard,
                result,
                self.config.dashboard_dir,
            )

        await _to_thread(
            self.history_store.upsert,
            file_hash=file_hash,
            source_path=candidate,
            status=status,
            analysis_path=prepared_asset.analysis_path,
            result_path=output_path,
            fast_sort_label=(result.metadata.get("fast_sort") or {}).get("label"),
            fast_sort_confidence=(result.metadata.get("fast_sort") or {}).get("confidence"),
            notes=list(result.notes),
            metadata={
                **dict(result.metadata),
                "sensitive": sensitivity.sensitive,
                "sensitivity_reasons": sensitivity.reasons,
                "sensitivity_types": sensitivity.matched_types,
                "protected_bundle_path": str(protected_bundle_path) if protected_bundle_path else None,
            },
        )

        if sensitivity.sensitive:
            LOGGER.info(
                "%s Protected sensitive output in %s",
                describe_result(result),
                protected_bundle_path,
            )
        else:
            LOGGER.info(
                "%s Saved result to %s and dashboard note to %s",
                describe_result(result),
                output_path,
                dashboard_note_path,
            )

        return PipelineOutcome(
            status=status,
            file_hash=file_hash,
            candidate=candidate,
            prepared_asset=prepared_asset,
            result=result,
            output_path=output_path,
            dashboard_note_path=dashboard_note_path,
            protected_bundle_path=protected_bundle_path,
        )

    async def mark_failure(self, candidate: Path, exc: Exception) -> PipelineOutcome:
        """Record a failed processing attempt in history and return a typed outcome."""
        file_hash: str | None = None
        try:
            if candidate.exists():
                file_hash = await _to_thread(compute_file_hash, candidate)
        except Exception:
            file_hash = None

        if file_hash is not None:
            await _to_thread(
                self.history_store.upsert,
                file_hash=file_hash,
                source_path=candidate,
                status="failed",
                notes=[f"Processing failed for {candidate.name}."],
                metadata={},
                last_error=str(exc),
            )

        LOGGER.exception("Failed to process %s", candidate)
        return PipelineOutcome(
            status="failed",
            file_hash=file_hash,
            candidate=candidate,
            failure_reason=str(exc),
        )


async def _to_thread(func, /, *args, **kwargs):
    import asyncio

    return await asyncio.to_thread(func, *args, **kwargs)


def _save_result(result: AnalysisRecord, results_dir: Path) -> Path:
    ensure_directory(results_dir)
    payload = analysis_record_to_dict(result)
    source_name = Path(result.source_path).stem
    output_path = results_dir / f"{source_name}.json"
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path
