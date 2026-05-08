from typing import Any, Optional
import psycopg2
import psycopg2.extras

from app.profiler.base import BaseProfiler

# Types we treat as numeric for percentile / stats queries
NUMERIC_TYPES = {
    "smallint", "integer", "bigint", "decimal", "numeric",
    "real", "double precision", "float4", "float8",
    "int2", "int4", "int8",
}

# Types we treat as string for length stats
STRING_TYPES = {
    "character varying", "varchar", "character", "char", "text",
    "bpchar",
}


class PostgresProfiler(BaseProfiler):
    """Profiles tables inside a PostgreSQL database via psycopg2."""

    def __init__(self, connection_string: str) -> None:
        self.connection_string = connection_string
        self._conn: Optional[psycopg2.extensions.connection] = None

    def _get_conn(self) -> psycopg2.extensions.connection:
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self.connection_string)
            self._conn.set_session(readonly=True, autocommit=True)
        return self._conn

    def close(self) -> None:
        if self._conn and not self._conn.closed:
            self._conn.close()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def list_tables(self) -> list[str]:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """
            )
            return [row[0] for row in cur.fetchall()]

    def profile_table(self, table_name: str) -> dict[str, Any]:
        conn = self._get_conn()

        # ---- row count ----
        with conn.cursor() as cur:
            cur.execute(f'SELECT COUNT(*) FROM "{table_name}"')  # noqa: S608
            row_count: int = cur.fetchone()[0]

        # ---- column metadata ----
        columns_meta = self._get_column_meta(table_name)

        column_profiles = []
        for col in columns_meta:
            col_name = col["column_name"]
            data_type = col["data_type"]
            col_profile = self._profile_column(table_name, col_name, data_type, row_count)
            column_profiles.append(col_profile)

        return {
            "table_name": table_name,
            "row_count": row_count,
            "column_count": len(column_profiles),
            "columns": column_profiles,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_column_meta(self, table_name: str) -> list[dict[str, str]]:
        conn = self._get_conn()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT column_name, data_type, udt_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = %s
                ORDER BY ordinal_position
                """,
                (table_name,),
            )
            return [dict(row) for row in cur.fetchall()]

    def _profile_column(
        self,
        table_name: str,
        col_name: str,
        data_type: str,
        row_count: int,
    ) -> dict[str, Any]:
        conn = self._get_conn()
        safe_col = f'"{col_name}"'
        safe_table = f'"{table_name}"'

        profile: dict[str, Any] = {
            "column_name": col_name,
            "data_type": data_type,
            "null_count": 0,
            "null_rate": 0.0,
            "distinct_count": 0,
            "distinct_rate": 0.0,
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

        with conn.cursor() as cur:
            # Null + distinct counts
            cur.execute(
                f"""
                SELECT
                    COUNT(*) - COUNT({safe_col}) AS null_count,
                    COUNT(DISTINCT {safe_col}) AS distinct_count
                FROM {safe_table}
                """  # noqa: S608
            )
            row = cur.fetchone()
            null_count = int(row[0])
            distinct_count = int(row[1])

        profile["null_count"] = null_count
        profile["null_rate"] = null_count / row_count if row_count > 0 else 0.0
        profile["distinct_count"] = distinct_count
        profile["distinct_rate"] = distinct_count / row_count if row_count > 0 else 0.0

        dtype_lower = data_type.lower()

        if dtype_lower in NUMERIC_TYPES:
            profile.update(self._numeric_stats(table_name, col_name))
        elif dtype_lower in STRING_TYPES:
            profile.update(self._string_stats(table_name, col_name))

        # Sample values
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {safe_col}
                FROM {safe_table}
                WHERE {safe_col} IS NOT NULL
                LIMIT 5
                """  # noqa: S608
            )
            profile["sample_values"] = [str(r[0]) for r in cur.fetchall()]

        return profile

    def _numeric_stats(self, table_name: str, col_name: str) -> dict[str, Any]:
        conn = self._get_conn()
        safe_col = f'"{col_name}"'
        safe_table = f'"{table_name}"'

        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    MIN({safe_col})::float,
                    MAX({safe_col})::float,
                    AVG({safe_col})::float,
                    STDDEV({safe_col})::float,
                    PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY {safe_col}),
                    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY {safe_col}),
                    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY {safe_col}),
                    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY {safe_col})
                FROM {safe_table}
                WHERE {safe_col} IS NOT NULL
                """  # noqa: S608
            )
            row = cur.fetchone()

        if row is None or row[0] is None:
            return {}

        return {
            "min_value": _safe_float(row[0]),
            "max_value": _safe_float(row[1]),
            "mean_value": _safe_float(row[2]),
            "std_value": _safe_float(row[3]),
            "p25": _safe_float(row[4]),
            "median_value": _safe_float(row[5]),
            "p75": _safe_float(row[6]),
            "p95": _safe_float(row[7]),
        }

    def _string_stats(self, table_name: str, col_name: str) -> dict[str, Any]:
        conn = self._get_conn()
        safe_col = f'"{col_name}"'
        safe_table = f'"{table_name}"'

        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    MIN(LENGTH({safe_col}))::float,
                    MAX(LENGTH({safe_col}))::float,
                    AVG(LENGTH({safe_col}))::float
                FROM {safe_table}
                WHERE {safe_col} IS NOT NULL
                """  # noqa: S608
            )
            row = cur.fetchone()

        if row is None or row[0] is None:
            return {}

        return {
            "min_length": _safe_float(row[0]),
            "max_length": _safe_float(row[1]),
            "avg_length": _safe_float(row[2]),
        }


def _safe_float(value: Any) -> Optional[float]:
    import math
    try:
        if value is None:
            return None
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None
