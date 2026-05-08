from abc import ABC, abstractmethod
from typing import Any


class BaseProfiler(ABC):
    """Abstract base class for all data source profilers."""

    @abstractmethod
    def list_tables(self) -> list[str]:
        """Return a list of available table/dataset names."""
        ...

    @abstractmethod
    def profile_table(self, table_name: str) -> dict[str, Any]:
        """
        Profile a single table/dataset.

        Returns a dict with shape:
        {
            "table_name": str,
            "row_count": int,
            "column_count": int,
            "columns": [
                {
                    "column_name": str,
                    "data_type": str,
                    "null_count": int,
                    "null_rate": float,
                    "distinct_count": int,
                    "distinct_rate": float,
                    # optional numeric stats:
                    "min_value": float | None,
                    "max_value": float | None,
                    "mean_value": float | None,
                    "std_value": float | None,
                    "median_value": float | None,
                    "p25": float | None,
                    "p75": float | None,
                    "p95": float | None,
                    # optional string stats:
                    "min_length": float | None,
                    "max_length": float | None,
                    "avg_length": float | None,
                    # samples:
                    "sample_values": list,
                },
                ...
            ]
        }
        """
        ...

    def profile_all(self) -> list[dict[str, Any]]:
        """Profile all available tables."""
        results = []
        for table_name in self.list_tables():
            try:
                results.append(self.profile_table(table_name))
            except Exception as exc:  # noqa: BLE001
                # Skip tables we can't profile but don't crash
                print(f"[profiler] Skipping {table_name}: {exc}")
        return results
