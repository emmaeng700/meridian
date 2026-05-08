import os
from typing import Any, Optional

import numpy as np
import pandas as pd

from app.profiler.base import BaseProfiler


class CSVProfiler(BaseProfiler):
    """Profiles CSV or Parquet files using pandas."""

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self._df: Optional[pd.DataFrame] = None

    def _load(self) -> pd.DataFrame:
        if self._df is None:
            ext = os.path.splitext(self.file_path)[1].lower()
            if ext == ".parquet":
                self._df = pd.read_parquet(self.file_path)
            else:
                # Try to sniff delimiter
                self._df = pd.read_csv(self.file_path, low_memory=False)
        return self._df

    def list_tables(self) -> list[str]:
        """Return a single table name derived from the filename."""
        basename = os.path.basename(self.file_path)
        name, _ = os.path.splitext(basename)
        return [name]

    def profile_table(self, table_name: str) -> dict[str, Any]:
        df = self._load()
        row_count, column_count = df.shape

        column_profiles = []
        for col in df.columns:
            col_profile = self._profile_column(df, col, row_count)
            column_profiles.append(col_profile)

        return {
            "table_name": table_name,
            "row_count": int(row_count),
            "column_count": int(column_count),
            "columns": column_profiles,
        }

    def _profile_column(self, df: pd.DataFrame, col_name: str, row_count: int) -> dict[str, Any]:
        series = df[col_name]
        null_count = int(series.isnull().sum())
        null_rate = null_count / row_count if row_count > 0 else 0.0
        distinct_count = int(series.nunique(dropna=True))
        distinct_rate = distinct_count / row_count if row_count > 0 else 0.0

        dtype_str = str(series.dtype)

        profile: dict[str, Any] = {
            "column_name": col_name,
            "data_type": dtype_str,
            "null_count": null_count,
            "null_rate": null_rate,
            "distinct_count": distinct_count,
            "distinct_rate": distinct_rate,
            "min_value": None,
            "max_value": None,
            "mean_value": None,
            "std_value": None,
            "median_value": None,
            "min_length": None,
            "max_length": None,
            "avg_length": None,
            "p25": None,
            "p75": None,
            "p95": None,
            "sample_values": [],
        }

        non_null = series.dropna()

        # Numeric stats
        if pd.api.types.is_numeric_dtype(series):
            if len(non_null) > 0:
                profile["min_value"] = _safe_float(non_null.min())
                profile["max_value"] = _safe_float(non_null.max())
                profile["mean_value"] = _safe_float(non_null.mean())
                profile["std_value"] = _safe_float(non_null.std())
                profile["median_value"] = _safe_float(non_null.median())
                profile["p25"] = _safe_float(non_null.quantile(0.25))
                profile["p75"] = _safe_float(non_null.quantile(0.75))
                profile["p95"] = _safe_float(non_null.quantile(0.95))

        # String stats
        elif pd.api.types.is_string_dtype(series) or pd.api.types.is_object_dtype(series):
            str_series = non_null.astype(str)
            if len(str_series) > 0:
                lengths = str_series.str.len()
                profile["min_length"] = _safe_float(lengths.min())
                profile["max_length"] = _safe_float(lengths.max())
                profile["avg_length"] = _safe_float(lengths.mean())

        # Sample values (up to 5)
        if len(non_null) > 0:
            sample = non_null.head(5).tolist()
            profile["sample_values"] = [_json_safe(v) for v in sample]

        return profile


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        f = float(value)
        if np.isnan(f) or np.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _json_safe(value: Any) -> Any:
    """Convert numpy types to Python native for JSON serialisation."""
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        v = float(value)
        return None if (np.isnan(v) or np.isinf(v)) else v
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if pd.isna(value):
        return None
    return str(value)
