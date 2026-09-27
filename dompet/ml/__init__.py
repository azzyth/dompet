"""Categorizer training and inference. Third-party deps (sklearn, joblib, yaml) live here."""

from dompet.ml.features import text_from_row, transaction_text  # noqa: F401
from dompet.ml.labels import SEED_RULES, label_text  # noqa: F401
