#!/usr/bin/env python3
"""
seed_demo.py — Seeds the Meridian database with NYC Yellow Taxi demo data.

What this script does:
  1. Downloads a small sample of the NYC Yellow Taxi Jan-2023 parquet file
  2. Loads it into the `taxi_trips` PostgreSQL table in 5 batches
  3. Intentionally injects anomalies (null-rate spike, volume drop, column type drift)
     so that Meridian's detectors have something to find
  4. Calls POST /sources and POST /sources/{id}/profile 5 times to build history

Usage:
    python seed_demo.py [--api-url http://localhost:8000/api/v1]
"""

import argparse
import io
import os
import sys
import time
import random
from datetime import datetime

import requests
import pandas as pd
import numpy as np
import psycopg2
import psycopg2.extras

# ---------------------------------------------------------------------------
TAXI_URL = (
    "https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_2023-01.parquet"
)
SAMPLE_SIZE = 20_000          # rows per batch (manageable for demo)
N_BATCHES = 5                  # number of profile runs to build history
DB_DSN = os.environ.get("SYNC_DATABASE_URL", "postgresql://meridian:meridian@localhost:5432/meridian")
TABLE_NAME = "taxi_trips"
SOURCE_NAME = "NYC Yellow Taxi (Demo)"
# ---------------------------------------------------------------------------


def download_sample(url: str, sample_size: int) -> pd.DataFrame:
    print(f"[seed] Downloading taxi parquet from {url} ...")
    resp = requests.get(url, stream=True, timeout=120)
    resp.raise_for_status()
    buf = io.BytesIO(resp.content)
    df = pd.read_parquet(buf)
    print(f"[seed] Full dataset: {len(df):,} rows × {len(df.columns)} cols")
    sample = df.sample(n=min(sample_size, len(df)), random_state=42).reset_index(drop=True)
    print(f"[seed] Using sample of {len(sample):,} rows")
    return sample


def create_table(conn, df: pd.DataFrame) -> None:
    """Create the taxi_trips table (drop if exists)."""
    col_defs = []
    for col in df.columns:
        dtype = df[col].dtype
        if pd.api.types.is_integer_dtype(dtype):
            pg_type = "BIGINT"
        elif pd.api.types.is_float_dtype(dtype):
            pg_type = "DOUBLE PRECISION"
        elif pd.api.types.is_bool_dtype(dtype):
            pg_type = "BOOLEAN"
        elif pd.api.types.is_datetime64_any_dtype(dtype):
            pg_type = "TIMESTAMP"
        else:
            pg_type = "TEXT"
        col_defs.append(f'"{col}" {pg_type}')

    ddl = f"""
    DROP TABLE IF EXISTS {TABLE_NAME};
    CREATE TABLE {TABLE_NAME} (
        id SERIAL PRIMARY KEY,
        batch_id INTEGER,
        {', '.join(col_defs)}
    );
    """
    with conn.cursor() as cur:
        cur.execute(ddl)
    conn.commit()
    print(f"[seed] Created table '{TABLE_NAME}'")


def insert_batch(conn, df: pd.DataFrame, batch_id: int) -> None:
    """Bulk-insert a DataFrame batch."""
    cols = ["batch_id"] + list(df.columns)
    records = []
    for row in df.itertuples(index=False):
        values = [batch_id]
        for v in row:
            if pd.isna(v) if not isinstance(v, (list, dict)) else False:
                values.append(None)
            elif isinstance(v, (np.integer,)):
                values.append(int(v))
            elif isinstance(v, (np.floating,)):
                values.append(float(v))
            elif isinstance(v, pd.Timestamp):
                values.append(v.to_pydatetime())
            else:
                values.append(v)
        records.append(tuple(values))

    placeholders = ",".join(["%s"] * len(cols))
    col_str = ",".join([f'"{c}"' for c in cols])
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(
            cur,
            f"INSERT INTO {TABLE_NAME} ({col_str}) VALUES ({placeholders})",
            records,
            page_size=500,
        )
    conn.commit()
    print(f"[seed] Inserted batch {batch_id}: {len(df):,} rows")


def inject_null_spike(df: pd.DataFrame, col: str, rate: float = 0.6) -> pd.DataFrame:
    """Randomly null out `rate` fraction of `col` values."""
    df = df.copy()
    mask = np.random.random(len(df)) < rate
    df.loc[mask, col] = None
    return df


def inject_volume_drop(df: pd.DataFrame, keep_fraction: float = 0.3) -> pd.DataFrame:
    """Return only a fraction of rows to simulate a volume drop."""
    n = max(1, int(len(df) * keep_fraction))
    return df.sample(n=n, random_state=99).reset_index(drop=True)


def create_source(api_url: str) -> str:
    """POST /sources — create the demo source, return source_id."""
    # Check if already exists
    r = requests.get(f"{api_url}/sources")
    r.raise_for_status()
    for src in r.json().get("items", []):
        if src["name"] == SOURCE_NAME:
            print(f"[seed] Source already exists: {src['id']}")
            return src["id"]

    payload = {
        "name": SOURCE_NAME,
        "source_type": "postgres",
        "connection_string": DB_DSN,
    }
    r = requests.post(f"{api_url}/sources", json=payload)
    r.raise_for_status()
    src_id = r.json()["id"]
    print(f"[seed] Created source: {src_id}")
    return src_id


def run_profile(api_url: str, source_id: str) -> dict:
    """POST /sources/{id}/profile."""
    r = requests.post(
        f"{api_url}/sources/{source_id}/profile",
        params={"table_name": TABLE_NAME},
        timeout=120,
    )
    r.raise_for_status()
    result = r.json()
    profiles = result.get("profiles", [])
    if profiles:
        p = profiles[0]
        print(
            f"[seed]   Profile: rows={p['row_count']:,} "
            f"health={p['health_score']:.1f} "
            f"anomalies={p['anomaly_count']}"
        )
    return result


def main():
    parser = argparse.ArgumentParser(description="Seed Meridian demo data")
    parser.add_argument("--api-url", default="http://localhost:8000/api/v1")
    parser.add_argument("--db-dsn", default=DB_DSN)
    args = parser.parse_args()

    api_url = args.api_url.rstrip("/")

    # --- Wait for API to be ready ---
    print("[seed] Waiting for Meridian API ...")
    for attempt in range(30):
        try:
            r = requests.get(f"{api_url.rsplit('/api', 1)[0]}/health", timeout=5)
            if r.status_code == 200:
                print("[seed] API is ready.")
                break
        except Exception:
            pass
        time.sleep(2)
    else:
        print("[seed] ERROR: API did not become ready in time.", file=sys.stderr)
        sys.exit(1)

    # --- Download data ---
    base_df = download_sample(TAXI_URL, SAMPLE_SIZE)

    # --- Connect to DB ---
    conn = psycopg2.connect(args.db_dsn)
    create_table(conn, base_df)

    # --- Create source in Meridian ---
    source_id = create_source(api_url)

    # --- 5 batches with intentional anomalies in later batches ---
    print(f"\n[seed] Running {N_BATCHES} profile iterations ...\n")

    for batch in range(1, N_BATCHES + 1):
        print(f"[seed] === Batch {batch} ===")

        if batch <= 3:
            # Clean batches — build baseline history
            batch_df = base_df.copy()
        elif batch == 4:
            # Batch 4: spike null rate in 'passenger_count'
            print("[seed]   Injecting null-rate spike in 'passenger_count'")
            batch_df = inject_null_spike(base_df, "passenger_count", rate=0.75)
        else:
            # Batch 5: volume drop + additional null spike
            print("[seed]   Injecting volume drop (30% of rows) + null spike")
            batch_df = inject_null_spike(base_df, "tip_amount", rate=0.5)
            batch_df = inject_volume_drop(batch_df, keep_fraction=0.3)

        insert_batch(conn, batch_df, batch_id=batch)
        run_profile(api_url, source_id)

        if batch < N_BATCHES:
            time.sleep(1)

    conn.close()
    print("\n[seed] Demo seeding complete!")
    print(f"[seed] Open the dashboard at http://localhost:8501")
    print(f"[seed] API docs at http://localhost:8000/docs")


if __name__ == "__main__":
    main()
