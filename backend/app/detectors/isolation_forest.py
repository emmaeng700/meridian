"""Isolation Forest based anomaly detection."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import numpy as np

try:
    from sklearn.ensemble import IsolationForest as SKIsolationForest
    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False

MIN_HISTORY = 5  # Minimum historical profiles needed to train


def _extract_feature_vector(profile: dict[str, Any]) -> list[float | None]:
    """
    Build a feature vector from a table profile:
    [row_count, avg_null_rate, avg_distinct_rate, avg_mean, avg_std]
    """
    row_count = float(profile.get("row_count", 0) or 0)
    columns = profile.get("columns", [])

    null_rates = [c["null_rate"] for c in columns if c.get("null_rate") is not None]
    distinct_rates = [c["distinct_rate"] for c in columns if c.get("distinct_rate") is not None]
    means = [c["mean_value"] for c in columns if c.get("mean_value") is not None]
    stds = [c["std_value"] for c in columns if c.get("std_value") is not None]

    return [
        row_count,
        float(np.mean(null_rates)) if null_rates else 0.0,
        float(np.mean(distinct_rates)) if distinct_rates else 0.0,
        float(np.mean(means)) if means else 0.0,
        float(np.mean(stds)) if stds else 0.0,
    ]


def _make_anomaly(
    source_id: str,
    table_profile_id: str,
    score: float,
    description: str,
) -> dict[str, Any]:
    severity = "critical" if score > 0.7 else "high" if score > 0.5 else "medium"
    return {
        "id": str(uuid.uuid4()),
        "source_id": source_id,
        "table_profile_id": table_profile_id,
        "column_name": None,
        "anomaly_type": "distribution_shift",
        "severity": severity,
        "metric_name": "isolation_forest_score",
        "expected_value": 0.0,
        "actual_value": score,
        "deviation_score": score,
        "description": description,
        "detected_at": datetime.utcnow().isoformat(),
        "acknowledged": False,
        "detector": "IsolationForestDetector",
    }


class IsolationForestDetector:
    """
    Trains an IsolationForest on historical profile feature vectors
    and scores the current profile. Flags if anomaly score exceeds threshold.
    """

    def __init__(self, contamination: float = 0.1, score_threshold: float = -0.1) -> None:
        """
        score_threshold: IsolationForest returns negative scores for anomalies.
        Scores below this threshold are considered anomalous.
        """
        self.contamination = contamination
        self.score_threshold = score_threshold

    def detect(
        self,
        current_profile: dict[str, Any],
        historical_profiles: list[dict[str, Any]],
        source_id: str,
        table_profile_id: str,
    ) -> list[dict[str, Any]]:
        if not _SKLEARN_AVAILABLE:
            return []

        if len(historical_profiles) < MIN_HISTORY:
            return []

        # Build feature matrix from history
        X_hist = []
        for p in historical_profiles:
            vec = _extract_feature_vector(p)
            if all(v is not None for v in vec):
                X_hist.append(vec)

        if len(X_hist) < MIN_HISTORY:
            return []

        X_hist_arr = np.array(X_hist, dtype=float)

        # Handle any remaining NaNs
        if np.any(np.isnan(X_hist_arr)):
            X_hist_arr = np.nan_to_num(X_hist_arr, nan=0.0)

        # Train
        clf = SKIsolationForest(
            contamination=self.contamination,
            random_state=42,
            n_estimators=100,
        )
        clf.fit(X_hist_arr)

        # Score current
        current_vec = _extract_feature_vector(current_profile)
        if any(v is None for v in current_vec):
            return []

        current_arr = np.array([current_vec], dtype=float)
        if np.any(np.isnan(current_arr)):
            current_arr = np.nan_to_num(current_arr, nan=0.0)

        raw_score = clf.score_samples(current_arr)[0]

        # IsolationForest: more negative = more anomalous
        # Normalise to a 0-1 deviation score for display
        deviation_score = max(0.0, -raw_score)

        if raw_score < self.score_threshold:
            return [
                _make_anomaly(
                    source_id=source_id,
                    table_profile_id=table_profile_id,
                    score=deviation_score,
                    description=(
                        f"IsolationForest flagged anomalous profile behaviour "
                        f"(score={raw_score:.4f}). The combined distribution of row_count, "
                        f"null_rate, distinct_rate, and numeric statistics deviates "
                        f"significantly from historical baselines."
                    ),
                )
            ]

        return []
