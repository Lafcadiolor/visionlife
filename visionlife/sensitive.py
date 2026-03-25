"""Compatibility wrapper for sensitive-data handling services."""

from services.sensitivity_service import SensitivityDecision, detect_sensitive_result, protect_sensitive_result

__all__ = ["SensitivityDecision", "detect_sensitive_result", "protect_sensitive_result"]
