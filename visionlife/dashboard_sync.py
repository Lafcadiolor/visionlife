"""Compatibility wrapper for dashboard publication services."""

from services.dashboard_service import append_tasks, build_dashboard_note, sync_result_to_dashboard

__all__ = ["append_tasks", "build_dashboard_note", "sync_result_to_dashboard"]
