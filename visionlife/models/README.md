# Fast Sort Model

Place your trained CoreML pocket-shot classifier at:

`visionlife/models/pocket_shot_classifier.mlpackage`

Expected behavior:

- Input name: `image`
- Output label key: `label` or `classLabel`
- Output probability key: `labelProbability` or `classLabel_probs`
- Positive delete label: `blurred_accidental_pocket_shot`

You can override these with environment variables:

- `VISIONLIFE_FAST_SORT_MODEL_PATH`
- `VISIONLIFE_FAST_SORT_LABEL_KEY`
- `VISIONLIFE_FAST_SORT_CONFIDENCE_KEY`
- `VISIONLIFE_FAST_SORT_POSITIVE_LABEL`
- `VISIONLIFE_FAST_SORT_THRESHOLD`

Safety rule:

- VisionLife only deletes automatically when the classifier returns the configured positive label and confidence is at least `0.90`.
