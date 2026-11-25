"""Participant SDK for contest.harness.workspace.v2.

The platform calls `python3 /app/harness.py describe|train|predict`.
Training code uses Round. Prediction code uses serve_predictions.
"""

from .errors import HarnessError
from .predict import Sample, prediction_context, serve_predictions
from .protocol import MODEL_ACCESS, PROTOCOL, SDK_NAME, SDK_VERSION
from .round import ModelReceipt, Round

__all__ = [
    "HarnessError",
    "MODEL_ACCESS",
    "ModelReceipt",
    "PROTOCOL",
    "Round",
    "SDK_NAME",
    "SDK_VERSION",
    "Sample",
    "prediction_context",
    "serve_predictions",
]
