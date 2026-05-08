"""Z-score and IQR based anomaly detectors."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import numpy as np


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_column_metric(profiles: list[dict], col_name: str, metric: str) -> list[float]:
    """Extract a metric's values across historical profiles for a given column."""
    values = []
    for p in profiles:
        for col in p.get("columns", []):
            if col["column_name"] == col_name:
                v = col.get(metric)
                if v is not None:
                    values.append(float(v))
                break
    return values


def _make_anomaly(
    *,
    source_id: str,
    table_profile_id: str,
    column_name: str | None,
    anomaly_type: str,
    severity: str,
    metric_name: str,
    expected_value: float,
    actual_value: float,
    deviation_score: float,
    description: str,
    detector: str,
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "source_id": source_id,
        "table_profile_id": table_profile_id,
        "column_name": column_name,
        "anomaly_type": anomaly_type,
        "severity": severity,
        "metric_name": metric_name,
        "expected_value": expected_value,
        "actual_value": actual_value,
        "deviation_score": deviation_score,
        "description": description,
        "detected_at": datetime.utcnow().isoformat(),
        "acknowledged": False,
        "detector": detector,
    }


def _severity_from_score(score: float) -> str:
    if score >= 6:
        return "critical"
    if score >= 4:
        return "high"
    if score >= 2.5:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Z-Score Detector
# ---------------------------------------------------------------------------

class ZScoreDetector:
    """
    Flags metrics where |current - mean| / std > threshold.
    Uses the last N historical profiles to compute baseline.
    """

    def __init__(self, threshold: float = 3.0, lookback: int = 30) -> None:
        self.threshold = threshold
        self.lookback = lookback

    def detect(
        self,
        current_profile: dict[str, Any],
        historical_profiles: list[dict[str, Any]],
        source_id: str,
        table_profile_id: str,
    ) -> list[dict[str, Any]]:
        if not historical_profiles:
            return []

        recent = historical_profiles[-self.lookback:]
        anomalies: list[dict[str, Any]] = []

        # --- Table-level metric: row_count ---
        row_counts = [float(p["row_count"]) for p in recent if p.get("row_count") is not None]
        if len(row_counts) >= 3:
            mean = np.mean(row_counts)
            std = np.std(row_counts)
            current_rc = float(current_profile.get("row_count", 0))
            if std > 0:
                z = abs(current_rc - mean) / std
                if z > self.threshold:
                    change_pct = ((current_rc - mean) / mean * 100) if mean != 0 else 0
                    direction = "dropped" if current_rc < mean else "spiked"
                    anomalies.append(
                        _make_anomaly(
                            source_id=source_id,
                            table_profile_id=table_profile_id,
                            column_name=None,
                            anomaly_type="volume_drop" if current_rc < mean else "outlier",
                            severity=_severity_from_score(z),
                            metric_name="row_count",
                            expected_value=mean,
                            actual_value=current_rc,
                            deviation_score=z,
                            description=(
                                f"Row count {direction} by {abs(change_pct):.1f}% "
                                f"(expected ~{mean:.0f}, got {current_rc:.0f}, z={z:.2f})"
                            ),
                            detector="ZScoreDetector",
                        )
                    )

        # --- Column-level metrics ---
        column_metrics = [
            ("null_rate", "null_rate_spike", "Null rate"),
            ("distinct_rate", "distribution_shift", "Distinct rate"),
            ("mean_value", "distribution_shift", "Mean value"),
            ("std_value", "distribution_shift", "Std deviation"),
        ]

        for col in current_profile.get("columns", []):
            col_name = col["column_name"]
            for metric, anomaly_type, label in column_metrics:
                current_val = col.get(metric)
                if current_val is None:
                    continue

                hist_vals = _extract_column_metric(recent, col_name, metric)
                if len(hist_vals) < 3:
                    continue

                mean = np.mean(hist_vals)
                std = np.std(hist_vals)
                if std == 0:
                    continue

                z = abs(float(current_val) - mean) / std
                if z > self.threshold:
                    anomalies.append(
                        _make_anomaly(
                            source_id=source_id,
                            table_profile_id=table_profile_id,
                            column_name=col_name,
                            anomaly_type=anomaly_type,
                            severity=_severity_from_score(z),
                            metric_name=metric,
                            expected_value=mean,
                            actual_value=float(current_val),
                            deviation_score=z,
                            description=(
                                f"Column '{col_name}': {label} is {current_val:.4f} "
                                f"(expected ~{mean:.4f}, z={z:.2f})"
                            ),
                            detector="ZScoreDetector",
                        )
                    )

        return anomalies


# ---------------------------------------------------------------------------
# IQR Detector
# ---------------------------------------------------------------------------

class IQRDetector:
    """
    Flags metrics where current < Q1 - multiplier*IQR or current > Q3 + multiplier*IQR.
    """

    def __init__(self, multiplier: float = 1.5, lookback: int = 30) -> None:
        self.multiplier = multiplier
        self.lookback = lookback

    def detect(
        self,
        current_profile: dict[str, Any],
        historical_profiles: list[dict[str, Any]],
        source_id: str,
        table_profile_id: str,
    ) -> list[dict[str, Any]]:
        if not historical_profiles:
            return []

        recent = historical_profiles[-self.lookback:]
        anomalies: list[dict[str, Any]] = []

        # Table-level: row_count
        row_counts = [float(p["row_count"]) for p in recent if p.get("row_count") is not None]
        if len(row_counts) >= 4:
            q1, q3 = np.percentile(row_counts, [25, 75])
            iqr = q3 - q1
            lower = q1 - self.multiplier * iqr
            upper = q3 + self.multiplier * iqr
            current_rc = float(current_profile.get("row_count", 0))
            if current_rc < lower or current_rc > upper:
                score = (
                    (lower - current_rc) / iqr if current_rc < lower else (current_rc - upper) / iqr
                ) if iqr > 0 else 3.0
                direction = "dropped" if current_rc < lower else "spiked"
                anomalies.append(
                    _make_anomaly(
                        source_id=source_id,
                        table_profile_id=table_profile_id,
                        column_name=None,
                        anomaly_type="volume_drop" if current_rc < lower else "outlier",
                        severity=_severity_from_score(score),
                        metric_name="row_count",
                        expected_value=(q1 + q3) / 2,
                        actual_value=current_rc,
                        deviation_score=score,
                        description=(
                            f"Row count {direction} outside IQR fence "
                            f"[{lower:.0f}, {upper:.0f}] (got {current_rc:.0f})"
                        ),
                        detector="IQRDetector",
                    )
                )

        # Column-level: null_rate
        for col in current_profile.get("columns", []):
            col_name = col["column_name"]
            current_nr = col.get("null_rate")
            if current_nr is None:
                continue

            hist_vals = _extract_column_metric(recent, col_name, "null_rate")
            if len(hist_vals) < 4:
                continue

            q1, q3 = np.percentile(hist_vals, [25, 75])
            iqr = q3 - q1
            lower = q1 - self.multiplier * iqr
            upper = q3 + self.multiplier * iqr

            if float(current_nr) < lower or float(current_nr) > upper:
                score = (
                    (lower - float(current_nr)) / iqr if float(current_nr) < lower
                    else (float(current_nr) - upper) / iqr
                ) if iqr > 0 else 3.0
                anomalies.append(
                    _make_anomaly(
                        source_id=source_id,
                        table_profile_id=table_profile_id,
                        column_name=col_name,
                        anomaly_type="null_rate_spike",
                        severity=_severity_from_score(score),
                        metric_name="null_rate",
                        expected_value=(q1 + q3) / 2,
                        actual_value=float(current_nr),
                        deviation_score=score,
                        description=(
                            f"Column '{col_name}': null rate {float(current_nr):.3f} "
                            f"outside IQR fence [{lower:.3f}, {upper:.3f}]"
                        ),
                        detector="IQRDetector",
                    )
                )

        return anomalies
