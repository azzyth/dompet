"""Train the transaction categorizer and select the winner on a frozen split.

Usage:
    python -m dompet.ml.train --config configs/train.yaml
    python -m dompet.ml.train --config configs/train.yaml --source db

Writes:
    reports/metrics_summary.csv   every candidate's accuracy + macro-F1
    models/category_model.joblib  the best non-rule model
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import yaml
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.svm import LinearSVC

from dompet.ml.dataset import load_dataset
from dompet.ml.labels import label_text
from dompet.ml.predict import CategoryModel

NOTES = {
    "rules": "keyword rules from dompet/ml/labels.py",
    "logreg": "word 1-2 gram TF-IDF + LogisticRegression",
    "linearsvc": "word+char TF-IDF + calibrated LinearSVC",
    "lightgbm": "word TF-IDF + LightGBM",
}


def _logreg(seed: int) -> Pipeline:
    return Pipeline(
        [
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)),
            ("clf", LogisticRegression(max_iter=1000, class_weight="balanced", random_state=seed)),
        ]
    )


def _linearsvc(seed: int) -> Pipeline:
    return Pipeline(
        [
            (
                "features",
                FeatureUnion(
                    [
                        ("word", TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)),
                        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2)),
                    ]
                ),
            ),
            ("clf", CalibratedClassifierCV(LinearSVC(random_state=seed), cv=3)),
        ]
    )


def _lightgbm(seed: int) -> Pipeline:
    """Shallow, heavily-regularized trees. Defaults (num_leaves=31, min_child_samples=20)
    underfit badly on a few hundred sparse rows; these settings fixed that (see decision_log.md)."""
    from lightgbm import LGBMClassifier

    return Pipeline(
        [
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True)),
            (
                "clf",
                LGBMClassifier(
                    n_estimators=600,
                    learning_rate=0.05,
                    num_leaves=7,
                    min_child_samples=2,
                    colsample_bytree=0.6,
                    subsample=0.9,
                    subsample_freq=1,
                    random_state=seed,
                    verbose=-1,
                ),
            ),
        ]
    )


def build_models(names: list[str], seed: int) -> dict[str, Pipeline]:
    builders = {"logreg": _logreg, "linearsvc": _linearsvc, "lightgbm": _lightgbm}
    models: dict[str, Pipeline] = {}
    for name in names:
        if name == "rules":
            continue
        builder = builders.get(name)
        if builder is None:
            print(f"  ! unknown model {name!r}, skipping")
            continue
        try:
            models[name] = builder(seed)
        except ImportError:
            print(f"  ! {name} not installed, skipping")
    return models


def _score(name: str, y_true: list[str], y_pred: list[str]) -> dict:
    return {
        "model": name,
        "accuracy": round(accuracy_score(y_true, y_pred), 4),
        "macro_f1": round(f1_score(y_true, y_pred, average="macro"), 4),
        "note": NOTES.get(name, ""),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/train.yaml")
    parser.add_argument("--source", default=None, help="override config source: synthetic|db|csv")
    parser.add_argument("--model-path", default=None)
    args = parser.parse_args(argv)

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    seed = int(cfg.get("seed", 42))
    test_size = float(cfg.get("test_size", 0.25))
    source = args.source or cfg.get("source", "synthetic")
    model_path = Path(args.model_path or cfg.get("model_path", "models/category_model.joblib"))
    reports_dir = Path(cfg.get("reports_dir", "reports"))

    conn = None
    if source == "db":
        from dompet.db.connection import connect

        conn = connect()
    try:
        syn = cfg.get("synthetic", {})
        rows = load_dataset(
            source,
            conn=conn,
            csv_path=cfg.get("csv_path"),
            n_per_category=int(syn.get("n_per_category", 40)),
            seed=int(syn.get("seed", seed)),
        )
    finally:
        if conn is not None:
            conn.close()

    texts = [t for t, _ in rows]
    labels = [c for _, c in rows]
    n_categories = len(set(labels))
    print(f"dataset: {len(rows)} rows | {n_categories} categories | source={source}")

    x_train, x_test, y_train, y_test = train_test_split(
        texts, labels, test_size=test_size, random_state=seed, stratify=labels
    )

    results = [_score("rules", y_test, [label_text(t) for t in x_test])]

    best_name, best_pipeline, best_f1 = None, None, float("-inf")
    for name, pipeline in build_models(cfg.get("models", ["logreg"]), seed).items():
        pipeline.fit(x_train, y_train)
        row = _score(name, y_test, pipeline.predict(x_test))
        results.append(row)
        print(f"  {name:<10} acc={row['accuracy']:.4f}  macro_f1={row['macro_f1']:.4f}")
        if row["macro_f1"] > best_f1:
            best_name, best_pipeline, best_f1 = name, pipeline, row["macro_f1"]

    reports_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = reports_dir / "metrics_summary.csv"
    with metrics_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["model", "accuracy", "macro_f1", "note"])
        writer.writeheader()
        writer.writerows(results)

    rule_f1 = results[0]["macro_f1"]
    print(f"\nrules baseline macro-F1: {rule_f1:.4f}   ->  wrote {metrics_path}")

    if best_pipeline is None:
        print("no ML model trained (only the rules baseline ran); nothing saved")
        return 0

    version = f"{best_name}-seed{seed}"
    saved = CategoryModel(best_pipeline, sorted(set(labels)), version=version).save(model_path)
    print(f"best: {best_name} (macro_f1={best_f1:.4f}) | delta vs rules {best_f1 - rule_f1:+.4f}")
    print(f"saved model -> {saved}  (version={version})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
