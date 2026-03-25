"""CoreML-backed local classifier used to cheaply discard obvious junk images."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


POCKET_SHOT_THRESHOLD = float(os.getenv("VISIONLIFE_FAST_SORT_THRESHOLD", "0.90"))
DEFAULT_MODEL_PATH = Path(
    os.getenv(
        "VISIONLIFE_FAST_SORT_MODEL_PATH",
        str(Path(__file__).resolve().parent / "models" / "pocket_shot_classifier.mlpackage"),
    )
)
DEFAULT_LABEL_KEY = os.getenv("VISIONLIFE_FAST_SORT_LABEL_KEY", "label")
DEFAULT_CONFIDENCE_KEY = os.getenv("VISIONLIFE_FAST_SORT_CONFIDENCE_KEY", "labelProbability")
DEFAULT_POSITIVE_LABEL = os.getenv(
    "VISIONLIFE_FAST_SORT_POSITIVE_LABEL",
    "blurred_accidental_pocket_shot",
)
DEFAULT_IMAGE_SIZE = int(os.getenv("VISIONLIFE_FAST_SORT_IMAGE_SIZE", "224"))


@dataclass(slots=True)
class FastSortResult:
    """Outcome of the local pre-cloud image classifier."""
    label: str
    confidence: float
    should_delete: bool
    backend: str
    metrics: dict[str, float]
    rationale: str


class FastSortService:
    """
    Runs a trained CoreML image classifier in a subprocess so model/runtime
    failures never take down the watcher.
    """

    def __init__(
        self,
        model_path: Path = DEFAULT_MODEL_PATH,
        positive_label: str = DEFAULT_POSITIVE_LABEL,
        threshold: float = POCKET_SHOT_THRESHOLD,
    ) -> None:
        self.model_path = model_path
        self.positive_label = positive_label
        self.threshold = threshold

    def classify(self, image_path: Path) -> FastSortResult:
        """Run the CoreML classifier in a subprocess and normalize the outcome."""
        if not self.model_path.exists():
            return FastSortResult(
                label="fast_sort_model_missing",
                confidence=0.0,
                should_delete=False,
                backend="coreml_subprocess",
                metrics={},
                rationale=f"CoreML model not found at {self.model_path}.",
            )

        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--predict",
            str(self.model_path),
            str(image_path),
            self.positive_label,
            str(self.threshold),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)

        if result.returncode != 0:
            return FastSortResult(
                label="fast_sort_unavailable",
                confidence=0.0,
                should_delete=False,
                backend="coreml_subprocess",
                metrics={},
                rationale=result.stderr.strip() or "CoreML subprocess failed.",
            )

        payload = json.loads(result.stdout)
        return FastSortResult(
            label=payload["label"],
            confidence=float(payload["confidence"]),
            should_delete=bool(payload["should_delete"]),
            backend=payload["backend"],
            metrics={key: float(value) for key, value in payload["metrics"].items()},
            rationale=payload["rationale"],
        )


def _predict_with_coreml(
    model_path: Path,
    image_path: Path,
    positive_label: str,
    threshold: float,
) -> FastSortResult:
    import coremltools as ct
    import numpy as np
    from PIL import Image, ImageOps

    model = ct.models.MLModel(str(model_path))
    image = _prepare_image(image_path, size=DEFAULT_IMAGE_SIZE)
    prediction = model.predict({"image": image})

    label = str(prediction.get(DEFAULT_LABEL_KEY) or prediction.get("classLabel") or "unknown")
    confidence_map = (
        prediction.get(DEFAULT_CONFIDENCE_KEY)
        or prediction.get("classLabel_probs")
        or prediction.get("targetProbability")
        or {}
    )
    confidence = float(confidence_map.get(positive_label, 0.0))
    should_delete = label == positive_label and confidence >= threshold

    image_array = np.asarray(image, dtype=np.float32) / 255.0
    brightness = float(image_array.mean())
    contrast = float(image_array.std())

    return FastSortResult(
        label=label,
        confidence=round(confidence, 4),
        should_delete=should_delete,
        backend="coreml",
        metrics={
            "brightness": round(brightness, 4),
            "contrast": round(contrast, 4),
        },
        rationale=(
            f"CoreML classifier predicted {label} at {confidence:.2%} confidence."
            if label != "unknown"
            else "CoreML classifier did not return a recognized label."
        ),
    )


def _prepare_image(image_path: Path, size: int) -> Any:
    from PIL import Image, ImageOps

    with Image.open(image_path) as image:
        normalized = ImageOps.exif_transpose(image).convert("RGB")
        normalized.thumbnail((size, size))
        canvas = Image.new("RGB", (size, size), color=(0, 0, 0))
        offset = ((size - normalized.width) // 2, (size - normalized.height) // 2)
        canvas.paste(normalized, offset)
        return canvas


if __name__ == "__main__":
    if len(sys.argv) >= 6 and sys.argv[1] == "--predict":
        model_path = Path(sys.argv[2]).expanduser().resolve()
        image_path = Path(sys.argv[3]).expanduser().resolve()
        positive_label = sys.argv[4]
        threshold = float(sys.argv[5])
        print(
            json.dumps(
                asdict(
                    _predict_with_coreml(
                    model_path=model_path,
                    image_path=image_path,
                    positive_label=positive_label,
                    threshold=threshold,
                    )
                )
            )
        )
