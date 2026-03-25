"""Media preparation, local transforms, and metadata utilities for VisionLife."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import mimetypes
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps
from PIL.ExifTags import GPSTAGS, TAGS


LOGGER = logging.getLogger(__name__)

SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif"}
SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov"}
SUPPORTED_DOCUMENT_EXTENSIONS = {".pdf"}
IMAGE_RESIZE_THRESHOLD_BYTES = 20 * 1024 * 1024
MAX_IMAGE_LONG_EDGE = 2048
HIGH_BITRATE_VIDEO_THRESHOLD_MEGABITS = 25.0


@dataclass(slots=True)
class PreparedAsset:
    """Represents a source asset plus its normalized analysis derivative."""

    source_path: Path
    analysis_path: Path
    media_type: str
    transformed: bool = False
    notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def ensure_directory(path: Path) -> Path:
    """Create a directory tree if needed and return the path for chaining."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_supported_media(path: Path) -> bool:
    """Return whether VisionLife currently knows how to prepare this file type."""
    return path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS | SUPPORTED_VIDEO_EXTENSIONS | SUPPORTED_DOCUMENT_EXTENSIONS


def wait_for_file_ready(path: Path, attempts: int = 10, delay_seconds: float = 1.0) -> bool:
    """Wait until a newly dropped file stops changing size before processing it."""
    previous_size: int | None = None

    for _ in range(attempts):
        try:
            current_size = path.stat().st_size
        except FileNotFoundError:
            return False

        if current_size > 0 and current_size == previous_size:
            return True

        previous_size = current_size
        time.sleep(delay_seconds)

    return False


def prepare_media_for_analysis(path: Path, working_dir: Path) -> PreparedAsset:
    """Normalize an incoming file into an image-like asset the model can analyze."""
    suffix = path.suffix.lower()

    if suffix in SUPPORTED_IMAGE_EXTENSIONS:
        return _prepare_image(path, working_dir)

    if suffix in SUPPORTED_VIDEO_EXTENSIONS:
        return _prepare_video(path, working_dir)

    if suffix in SUPPORTED_DOCUMENT_EXTENSIONS:
        return _prepare_pdf(path, working_dir)

    raise ValueError(f"Unsupported media type: {path.suffix}")


def extract_exif_data(path: Path) -> dict[str, Any]:
    """Extract image metadata in a JSON-safe shape used by prompts and notes."""
    try:
        with Image.open(path) as image:
            exif = image.getexif()
            exif_payload = {TAGS.get(tag, str(tag)): value for tag, value in exif.items()}
            gps_info = _normalize_gps_info(exif_payload.get("GPSInfo"))

            normalized = {
                "device": {
                    "make": _safe_scalar(exif_payload.get("Make")),
                    "model": _safe_scalar(exif_payload.get("Model")),
                    "software": _safe_scalar(exif_payload.get("Software")),
                },
                "timestamp": {
                    "captured_at": _safe_scalar(exif_payload.get("DateTimeOriginal")),
                    "digitized_at": _safe_scalar(exif_payload.get("DateTimeDigitized")),
                    "modified_at": _safe_scalar(exif_payload.get("DateTime")),
                },
                "gps": gps_info,
                "raw_exif": _json_safe(exif_payload),
            }

            if image.format == "PNG":
                png_text = {key: _safe_scalar(value) for key, value in image.info.items()}
                if png_text:
                    normalized["raw_png_metadata"] = png_text

            return normalized
    except Exception as exc:
        LOGGER.warning("Could not extract EXIF from %s: %s", path, exc)
        return {
            "device": {"make": None, "model": None, "software": None},
            "timestamp": {"captured_at": None, "digitized_at": None, "modified_at": None},
            "gps": None,
            "raw_exif": {},
            "error": str(exc),
        }


def image_file_to_data_url(path: Path) -> str:
    """Encode a prepared image as a data URL for the Responses API."""
    mime_type, _ = mimetypes.guess_type(path.name)
    if mime_type is None:
        mime_type = "application/octet-stream"

    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def compute_file_hash(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Compute a stable SHA-256 hash for dedupe and history tracking."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def safe_delete_file(path: Path) -> bool:
    """Best-effort local deletion used by the fast-sort pre-cloud gate."""
    try:
        path.unlink(missing_ok=True)
        return True
    except Exception as exc:
        LOGGER.warning("Could not delete %s: %s", path, exc)
        return False


def running_on_apple_silicon() -> bool:
    """Return whether the current machine is an Apple Silicon Mac."""
    return os.uname().machine == "arm64"


def _prepare_image(path: Path, working_dir: Path) -> PreparedAsset:
    if path.suffix.lower() in {".heic", ".heif"}:
        return _prepare_heic_image(path, working_dir)

    asset = PreparedAsset(
        source_path=path,
        analysis_path=path,
        media_type="image",
        metadata={"original_size_bytes": path.stat().st_size},
    )

    if path.stat().st_size <= IMAGE_RESIZE_THRESHOLD_BYTES:
        asset.notes.append("Image is within the local size limit; no resize needed.")
        return asset

    output_dir = ensure_directory(working_dir / "prepared")
    output_path = output_dir / f"{path.stem}_2048{path.suffix.lower()}"

    with Image.open(path) as image:
        transposed = ImageOps.exif_transpose(image)
        width, height = transposed.size
        long_edge = max(width, height)
        asset.metadata["original_dimensions"] = {"width": width, "height": height}

        if long_edge <= MAX_IMAGE_LONG_EDGE:
            asset.notes.append(
                "Image exceeded 20 MB, but its dimensions were already within the target long edge."
            )
            return asset

        scale = MAX_IMAGE_LONG_EDGE / long_edge
        resized_dimensions = (int(width * scale), int(height * scale))
        resized = transposed.resize(resized_dimensions, Image.Resampling.LANCZOS)

        save_kwargs: dict[str, Any] = {"optimize": True}
        if path.suffix.lower() in {".jpg", ".jpeg"}:
            save_kwargs["quality"] = 92

        resized.save(output_path, **save_kwargs)

    asset.analysis_path = output_path
    asset.transformed = True
    asset.notes.append(
        "Image exceeded 20 MB, so a 2048px-long-edge derivative was generated for analysis."
    )
    asset.metadata["prepared_dimensions"] = {
        "width": resized_dimensions[0],
        "height": resized_dimensions[1],
    }
    asset.metadata["prepared_size_bytes"] = output_path.stat().st_size
    return asset


def _prepare_heic_image(path: Path, working_dir: Path) -> PreparedAsset:
    asset = PreparedAsset(
        source_path=path,
        analysis_path=path,
        media_type="image",
        transformed=True,
        metadata={"original_size_bytes": path.stat().st_size, "source_format": path.suffix.lower()},
    )
    output_dir = ensure_directory(working_dir / "prepared")
    output_path = output_dir / f"{path.stem}_heic.jpg"

    sips_path = _tool_path("sips")
    if sips_path is None:
        raise RuntimeError("sips is required on macOS to prepare HEIC images for analysis.")

    command = [sips_path, "-s", "format", "jpeg", str(path), "--out", str(output_path)]
    subprocess.run(command, capture_output=True, text=True, check=True)

    asset.analysis_path = output_path
    asset.notes.append("HEIC/HEIF image converted to JPEG locally for analysis compatibility.")
    asset.metadata["prepared_size_bytes"] = output_path.stat().st_size
    return asset


def _prepare_video(path: Path, working_dir: Path) -> PreparedAsset:
    asset = PreparedAsset(
        source_path=path,
        analysis_path=path,
        media_type="video",
        metadata=probe_video_metadata(path),
    )

    bitrate_mbps = asset.metadata.get("bitrate_mbps")
    if bitrate_mbps is None:
        asset.notes.append(
            "Video bitrate could not be determined; extracting a representative frame because the vision model expects an image."
        )
    elif bitrate_mbps >= HIGH_BITRATE_VIDEO_THRESHOLD_MEGABITS:
        asset.notes.append(
            f"Video bitrate {bitrate_mbps:.2f} Mbps exceeded the threshold; extracting one frame instead of uploading the full video."
        )
    else:
        asset.notes.append(
            f"Video bitrate {bitrate_mbps:.2f} Mbps is below the high-bitrate threshold, but a representative frame is still extracted because the vision model expects an image."
        )

    output_dir = ensure_directory(working_dir / "prepared")
    output_path = output_dir / f"{path.stem}_keyframe.jpg"
    extract_high_quality_frame(path, output_path, asset.metadata)
    asset.analysis_path = output_path
    asset.media_type = "image"
    asset.transformed = True
    asset.metadata["prepared_size_bytes"] = output_path.stat().st_size
    return asset


def _prepare_pdf(path: Path, working_dir: Path) -> PreparedAsset:
    asset = PreparedAsset(
        source_path=path,
        analysis_path=path,
        media_type="image",
        transformed=True,
        metadata={"original_size_bytes": path.stat().st_size, "source_format": path.suffix.lower()},
    )
    output_dir = ensure_directory(working_dir / "prepared")
    qlmanage_path = _tool_path("qlmanage")
    if qlmanage_path is None:
        raise RuntimeError("qlmanage is required on macOS to prepare PDFs for analysis.")

    command = [qlmanage_path, "-t", "-s", str(MAX_IMAGE_LONG_EDGE), "-o", str(output_dir), str(path)]
    subprocess.run(command, capture_output=True, text=True, check=True)

    candidates = sorted(output_dir.glob(f"{path.name}*.png"))
    if not candidates:
        candidates = sorted(output_dir.glob(f"{path.stem}*.png"))
    if not candidates:
        raise RuntimeError(f"Could not render a PDF preview for {path}.")

    output_path = output_dir / f"{path.stem}_pdf.png"
    candidates[0].replace(output_path)

    asset.analysis_path = output_path
    asset.notes.append("PDF rendered locally to a preview image for OCR and event analysis.")
    asset.metadata["prepared_size_bytes"] = output_path.stat().st_size
    return asset


def probe_video_metadata(path: Path) -> dict[str, Any]:
    ffprobe_path = _tool_path("ffprobe")
    if ffprobe_path is None:
        raise RuntimeError(
            "ffprobe is required for video pre-flight checks but is not installed or not on PATH."
        )

    command = [
        ffprobe_path,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_entries",
        "format=bit_rate,duration:stream=index,codec_type,width,height,avg_frame_rate",
        str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    payload = json.loads(result.stdout)

    metadata: dict[str, Any] = {}
    format_section = payload.get("format", {})
    bit_rate = format_section.get("bit_rate")
    duration = format_section.get("duration")

    if bit_rate:
        metadata["bitrate_bps"] = int(bit_rate)
        metadata["bitrate_mbps"] = int(bit_rate) / 1_000_000

    if duration:
        metadata["duration_seconds"] = float(duration)

    for stream in payload.get("streams", []):
        if stream.get("codec_type") == "video":
            metadata["frame_width"] = stream.get("width")
            metadata["frame_height"] = stream.get("height")
            metadata["avg_frame_rate"] = stream.get("avg_frame_rate")
            break

    return metadata


def extract_high_quality_frame(source_path: Path, output_path: Path, metadata: dict[str, Any]) -> None:
    ffmpeg_path = _tool_path("ffmpeg")
    if ffmpeg_path is None:
        raise RuntimeError(
            "ffmpeg is required to extract analysis frames from high-bitrate videos."
        )

    duration_seconds = metadata.get("duration_seconds")
    if duration_seconds and duration_seconds > 4:
        capture_time = min(duration_seconds / 2, 30.0)
    else:
        capture_time = 1.0

    command = [
        ffmpeg_path,
        "-y",
        "-ss",
        f"{capture_time:.2f}",
        "-i",
        str(source_path),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(output_path),
    ]
    subprocess.run(command, capture_output=True, text=True, check=True)


def _tool_path(tool_name: str) -> str | None:
    result = subprocess.run(
        ["which", tool_name],
        capture_output=True,
        text=True,
        check=False,
    )
    candidate = result.stdout.strip()
    return candidate or None


def _normalize_gps_info(gps_info: Any) -> dict[str, Any] | None:
    if not gps_info:
        return None

    if isinstance(gps_info, dict):
        readable = {GPSTAGS.get(tag, str(tag)): value for tag, value in gps_info.items()}
    else:
        return None

    latitude = _gps_to_decimal(readable.get("GPSLatitude"), readable.get("GPSLatitudeRef"))
    longitude = _gps_to_decimal(readable.get("GPSLongitude"), readable.get("GPSLongitudeRef"))

    return {
        "latitude": latitude,
        "longitude": longitude,
        "altitude": _safe_scalar(readable.get("GPSAltitude")),
        "timestamp": _safe_scalar(readable.get("GPSTimeStamp")),
        "date": _safe_scalar(readable.get("GPSDateStamp")),
        "raw": _json_safe(readable),
    }


def _gps_to_decimal(value: Any, ref: Any) -> float | None:
    if not value or not ref:
        return None

    try:
        degrees, minutes, seconds = value
        decimal = _ratio_to_float(degrees) + _ratio_to_float(minutes) / 60 + _ratio_to_float(seconds) / 3600
        if str(ref).upper() in {"S", "W"}:
            decimal *= -1
        return round(decimal, 7)
    except Exception:
        return None


def _ratio_to_float(value: Any) -> float:
    if isinstance(value, tuple) and len(value) == 2:
        numerator, denominator = value
        return float(numerator) / float(denominator)

    numerator = getattr(value, "numerator", None)
    denominator = getattr(value, "denominator", None)
    if numerator is not None and denominator is not None:
        return float(numerator) / float(denominator)

    return float(value)


def _safe_scalar(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, tuple):
        return [_safe_scalar(item) for item in value]
    return value


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    numerator = getattr(value, "numerator", None)
    denominator = getattr(value, "denominator", None)
    if numerator is not None and denominator is not None:
        return float(numerator) / float(denominator)
    return value
