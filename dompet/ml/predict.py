"""Serve and persist the trained categorizer."""

from __future__ import annotations

import os
from pathlib import Path

import joblib

DEFAULT_MODEL_PATH = Path("models/category_model.joblib")


class CategoryModel:
    """Wraps a fitted sklearn pipeline and exposes a uniform ``predict`` contract.

    ``predict(text) -> (label, confidence)`` — confidence comes from
    ``predict_proba`` when the pipeline supports it, otherwise it is 1.0.
    """

    def __init__(self, pipeline, labels: list[str], version: str = "v1"):
        self.pipeline = pipeline
        self.labels = list(labels)
        self.version = version

    def predict(self, text: str) -> tuple[str, float]:
        if hasattr(self.pipeline, "predict_proba"):
            proba = self.pipeline.predict_proba([text])[0]
            best = int(proba.argmax())
            return str(self.pipeline.classes_[best]), float(proba[best])
        label = self.pipeline.predict([text])[0]
        return str(label), 1.0

    def save(self, path: str | Path = DEFAULT_MODEL_PATH) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)
        return path

    @classmethod
    def load(cls, path: str | Path | None = None) -> CategoryModel:
        path = Path(path or os.environ.get("DOMPET_MODEL_PATH") or DEFAULT_MODEL_PATH)
        if not path.exists():
            raise FileNotFoundError(
                f"no model at {path} — train one with: python -m dompet.ml.train"
            )
        return joblib.load(path)


def load_if_available() -> CategoryModel | None:
    """Best-effort load for the API/dashboard so a missing model is not fatal."""
    try:
        return CategoryModel.load()
    except (FileNotFoundError, ImportError):
        return None
