"""Services for detecting and protecting sensitive VisionLife outputs."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tarfile
from dataclasses import asdict, dataclass
from pathlib import Path

from services.dashboard_service import build_dashboard_note
from records import AnalysisRecord, analysis_record_to_dict
from utils import ensure_directory


SENSITIVE_CATEGORY_KEYWORDS = {
    "document",
    "health",
    "medical",
    "identity",
    "identification",
    "passport",
    "license",
}

PII_PATTERNS: dict[str, str] = {
    "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
    "drivers_license": r"\bDL\s?[A-Z]\d{7}\b|\b[A-Z]\d{7}\b",
    "date_of_birth": r"\bDOB\b|\bdate of birth\b",
    "address": r"\b\d{1,6}\s+[A-Z0-9][A-Za-z0-9.\- ]+\s(?:ST|STREET|AVE|AVENUE|RD|ROAD|BLVD|DR|DRIVE|LN|LANE|WAY|HWY|HIGHWAY|CT|COURT)\b",
    "credit_card": r"\b(?:\d[ -]*?){13,19}\b",
    "passport": r"\bpassport\b",
}


@dataclass(slots=True)
class SensitivityDecision:
    """Describes whether a result should be diverted into the protected ID vault."""

    sensitive: bool
    reasons: list[str]
    matched_types: list[str]


def detect_sensitive_result(result: AnalysisRecord | dict[str, object]) -> SensitivityDecision:
    """Apply lightweight OCR/category heuristics to decide whether a result is sensitive.

    This is intentionally conservative. The goal is not perfect privacy
    classification; the goal is to avoid leaking obviously identifying or
    regulated-style information into the public dashboard surface.
    """
    result = analysis_record_to_dict(result)
    vision_result = result.get("vision_result") if isinstance(result.get("vision_result"), dict) else {}
    category = str(vision_result.get("category") or "").strip().lower()
    subcategory = str(vision_result.get("subcategory") or "").strip().lower()
    tags = [str(item).strip().lower() for item in vision_result.get("tags") or []]
    raw_text = str(vision_result.get("raw_text") or "")
    text_significance = ""
    if isinstance(vision_result.get("text_analysis"), dict):
        text_significance = str(vision_result["text_analysis"].get("significance") or "")
    haystack = "\n".join(
        [
            str(result.get("source_path") or ""),
            str(vision_result.get("category") or ""),
            str(vision_result.get("subcategory") or ""),
            " ".join(str(item) for item in vision_result.get("tags") or []),
            raw_text,
            text_significance,
        ]
    )

    matched_types: list[str] = []
    reasons: list[str] = []
    category_terms = {category, subcategory, *tags}
    if any(
        keyword == term or keyword in term.split()
        for term in category_terms
        for keyword in SENSITIVE_CATEGORY_KEYWORDS
        if term
    ):
        matched_types.append("sensitive_category")
        reasons.append("Category/subcategory/tags indicate identity, document, or health-related content.")

    for label, pattern in PII_PATTERNS.items():
        if re.search(pattern, haystack, re.IGNORECASE):
            matched_types.append(label)

    if matched_types:
        if raw_text.strip():
            reasons.append("OCR extracted structured or identifying text from the image.")
        if "highly significant" in text_significance.lower() or "personally identifying" in text_significance.lower():
            reasons.append("Model flagged the text as sensitive or identifying.")

    matched_types = sorted(set(matched_types))
    reasons = list(dict.fromkeys(reasons))
    return SensitivityDecision(sensitive=bool(matched_types), reasons=reasons, matched_types=matched_types)


def protect_sensitive_result(
    result: AnalysisRecord | dict[str, object],
    id_root: Path,
    decision: SensitivityDecision,
    *,
    password_env_var: str = "VISIONLIFE_ID_PASSWORD",
) -> Path:
    """Package and encrypt a sensitive result into the protected ID vault.

    The protected bundle contains:
    - a rewritten dashboard note that points to local bundle media
    - the raw structured result JSON
    - sensitivity reasoning
    - a manifest of source/prepared asset provenance

    This keeps sensitive outputs explainable and recoverable while still
    preventing them from being published into the normal dashboard path.
    """
    result = analysis_record_to_dict(result)
    password = os.getenv(password_env_var)
    if not password:
        raise RuntimeError(
            f"Sensitive result detected, but {password_env_var} is not set. "
            "Refusing to write sensitive output to the public dashboard."
        )

    id_root = ensure_directory(id_root)
    os.chmod(id_root, 0o700)
    staging_root = ensure_directory(id_root / "_staging")
    os.chmod(staging_root, 0o700)

    note_name, _, _, _ = build_dashboard_note(result)
    slug = Path(note_name).stem
    bundle_dir = ensure_directory(staging_root / slug)
    media_dir = ensure_directory(bundle_dir / "media")

    source_path = Path(str(result["source_path"])).expanduser()
    analysis_path = Path(str(result["analysis_path"])).expanduser()
    source_copy_name = source_path.name
    if source_path.exists():
        shutil.copy2(source_path, media_dir / source_path.name)
    else:
        source_copy_name = ""

    if analysis_path == source_path and source_copy_name:
        analysis_copy_name = source_copy_name
    else:
        analysis_copy = media_dir / analysis_path.name
        shutil.copy2(analysis_path, analysis_copy)
        analysis_copy_name = analysis_copy.name

    protected_note_name, protected_note_text, _, _ = build_dashboard_note(
        result,
        media_path_override=f"media/{analysis_copy_name}",
    )
    (bundle_dir / protected_note_name).write_text(protected_note_text, encoding="utf-8")
    (bundle_dir / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (bundle_dir / "sensitivity.json").write_text(json.dumps(asdict(decision), indent=2), encoding="utf-8")
    (bundle_dir / "manifest.json").write_text(
        json.dumps(
            {
                "source_path": str(source_path),
                "source_present": source_path.exists(),
                "analysis_path": str(analysis_path),
                "analysis_present": analysis_path.exists(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    tar_path = id_root / f"{slug}.tar.gz"
    enc_path = id_root / f"{slug}.tar.gz.enc"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(bundle_dir, arcname=slug)

    openssl_path = shutil.which("openssl")
    if not openssl_path:
        raise RuntimeError("openssl is required to encrypt protected ID bundles.")

    env = os.environ.copy()
    env[password_env_var] = password
    subprocess.run(
        [
            openssl_path,
            "enc",
            "-aes-256-cbc",
            "-pbkdf2",
            "-salt",
            "-in",
            str(tar_path),
            "-out",
            str(enc_path),
            "-pass",
            f"env:{password_env_var}",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    os.chmod(enc_path, 0o600)

    tar_path.unlink(missing_ok=True)
    shutil.rmtree(bundle_dir, ignore_errors=True)
    return enc_path
