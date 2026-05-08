"""Schema drift detector — compares column lists and types between profiles."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any


def _make_anomaly(
    *,
    source_id: str,
    table_profile_id: str,
    column_name: str | None,
    severity: str,
    metric_name: str,
    expected_value: str,
    actual_value: str,
    description: str,
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "source_id": source_id,
        "table_profile_id": table_profile_id,
        "column_name": column_name,
        "anomaly_type": "schema_drift",
        "severity": severity,
        "metric_name": metric_name,
        # Store sentinel numeric values; real info is in description
        "expected_value": 0.0,
        "actual_value": 1.0,
        "deviation_score": 1.0,
        "description": description,
        "detected_at": datetime.utcnow().isoformat(),
        "acknowledged": False,
        "detector": "SchemaDriftDetector",
    }


class SchemaDriftDetector:
    """
    Compares the column schema of the current profile against the most recent
    previous profile and detects:
      - Added columns   → low severity
      - Removed columns → critical severity
      - Type changes    → high severity
    """

    def detect(
        self,
        current_profile: dict[str, Any],
        previous_profile: dict[str, Any] | None,
        source_id: str,
        table_profile_id: str,
    ) -> list[dict[str, Any]]:
        if previous_profile is None:
            return []

        current_cols: dict[str, str] = {
            c["column_name"]: c["data_type"]
            for c in current_profile.get("columns", [])
        }
        previous_cols: dict[str, str] = {
            c["column_name"]: c["data_type"]
            for c in previous_profile.get("columns", [])
        }

        anomalies: list[dict[str, Any]] = []

        # Added columns (new in current, missing in previous)
        added = set(current_cols) - set(previous_cols)
        for col in sorted(added):
            anomalies.append(
                _make_anomaly(
                    source_id=source_id,
                    table_profile_id=table_profile_id,
                    column_name=col,
                    severity="low",
                    metric_name="schema_column_added",
                    expected_value="absent",
                    actual_value=current_cols[col],
                    description=(
                        f"New column '{col}' ({current_cols[col]}) detected "
                        f"in table '{current_profile.get('table_name', '')}'. "
                        f"This column was not present in the previous profile."
                    ),
                )
            )

        # Removed columns (in previous, missing from current) → critical
        removed = set(previous_cols) - set(current_cols)
        for col in sorted(removed):
            anomalies.append(
                _make_anomaly(
                    source_id=source_id,
                    table_profile_id=table_profile_id,
                    column_name=col,
                    severity="critical",
                    metric_name="schema_column_removed",
                    expected_value=previous_cols[col],
                    actual_value="absent",
                    description=(
                        f"Column '{col}' ({previous_cols[col]}) was REMOVED "
                        f"from table '{current_profile.get('table_name', '')}'. "
                        f"Downstream pipelines may be broken."
                    ),
                )
            )

        # Type changes (in both, but type differs)
        common = set(current_cols) & set(previous_cols)
        for col in sorted(common):
            prev_type = previous_cols[col]
            curr_type = current_cols[col]
            if prev_type != curr_type:
                anomalies.append(
                    _make_anomaly(
                        source_id=source_id,
                        table_profile_id=table_profile_id,
                        column_name=col,
                        severity="high",
                        metric_name="schema_type_change",
                        expected_value=prev_type,
                        actual_value=curr_type,
                        description=(
                            f"Column '{col}' type changed from '{prev_type}' "
                            f"to '{curr_type}' in table "
                            f"'{current_profile.get('table_name', '')}'. "
                            f"This may cause query failures."
                        ),
                    )
                )

        # Column count change (beyond individual adds/removes)
        prev_count = len(previous_cols)
        curr_count = len(current_cols)
        if prev_count != curr_count and not added and not removed:
            # Shouldn't happen, but be defensive
            anomalies.append(
                _make_anomaly(
                    source_id=source_id,
                    table_profile_id=table_profile_id,
                    column_name=None,
                    severity="medium",
                    metric_name="schema_column_count_change",
                    expected_value=str(prev_count),
                    actual_value=str(curr_count),
                    description=(
                        f"Column count changed from {prev_count} to {curr_count} "
                        f"in table '{current_profile.get('table_name', '')}'."
                    ),
                )
            )

        return anomalies
