"""Profiles page — profile history, trends, and column quality grids."""

import os
from typing import Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000/api/v1").rstrip("/")


def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        if abs(v) >= 1_000_000:
            return f"{v:,.0f}"
        return f"{v:,.4f}"
    return str(v)

st.set_page_config(page_title="Profiles — Meridian", page_icon="📊", layout="wide")

st.title("📊 Data Profiles")
st.caption("Explore schema statistics, row counts, null rates, and distributions over time.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fetch_sources() -> list[dict]:
    try:
        r = requests.get(f"{API_URL}/sources", timeout=10)
        r.raise_for_status()
        return r.json().get("items", [])
    except Exception:
        return []


def fetch_profiles(source_id: str, table_name: Optional[str] = None) -> list[dict]:
    params = {"source_id": source_id, "limit": 100}
    if table_name:
        params["table_name"] = table_name
    try:
        r = requests.get(f"{API_URL}/profiles", params=params, timeout=15)
        r.raise_for_status()
        return r.json().get("items", [])
    except Exception as exc:
        st.error(f"Failed to fetch profiles: {exc}")
        return []


# ---------------------------------------------------------------------------
# Source + table selection
# ---------------------------------------------------------------------------

sources = fetch_sources()
if not sources:
    st.info("No sources found. Add a source and run a profile first.")
    st.stop()

source_names = {s["name"]: s["id"] for s in sources}
selected_source_name = st.selectbox("Select Source", list(source_names.keys()))
selected_source_id = source_names[selected_source_name]

# Fetch all profiles for this source to know table names
all_profiles = fetch_profiles(selected_source_id)
if not all_profiles:
    st.info("No profiles found for this source. Run a profile from the Sources page.")
    st.stop()

table_names = sorted(set(p["table_name"] for p in all_profiles))
selected_table = st.selectbox("Select Table", table_names)

profiles = [p for p in all_profiles if p["table_name"] == selected_table]
profiles_sorted = sorted(profiles, key=lambda x: x["profiled_at"])

st.markdown(f"**{len(profiles)}** profile runs found for `{selected_table}`")

# ---------------------------------------------------------------------------
# Row count over time
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Row Count Over Time")

if len(profiles_sorted) >= 2:
    df_rc = pd.DataFrame(
        [
            {"profiled_at": p["profiled_at"], "row_count": p["row_count"]}
            for p in profiles_sorted
        ]
    )
    fig_rc = px.line(
        df_rc,
        x="profiled_at",
        y="row_count",
        markers=True,
        title="Row Count Trend",
        template="plotly_dark",
        labels={"profiled_at": "Profile Time", "row_count": "Row Count"},
    )
    fig_rc.update_traces(line_color="#00d4ff", marker_color="#ff6b6b")
    st.plotly_chart(fig_rc, use_container_width=True)
else:
    st.info("Need at least 2 profile runs to show a trend.")

# ---------------------------------------------------------------------------
# Health score over time
# ---------------------------------------------------------------------------

if len(profiles_sorted) >= 2:
    df_hs = pd.DataFrame(
        [
            {"profiled_at": p["profiled_at"], "health_score": p["health_score"]}
            for p in profiles_sorted
        ]
    )
    fig_hs = px.line(
        df_hs,
        x="profiled_at",
        y="health_score",
        markers=True,
        title="Health Score Trend",
        template="plotly_dark",
        labels={"profiled_at": "Profile Time", "health_score": "Health Score"},
        range_y=[0, 105],
    )
    fig_hs.update_traces(line_color="#00ff7f", marker_color="#ffd700")
    fig_hs.add_hline(y=90, line_dash="dot", line_color="green", annotation_text="Good (90)")
    fig_hs.add_hline(y=70, line_dash="dot", line_color="orange", annotation_text="Warn (70)")
    st.plotly_chart(fig_hs, use_container_width=True)

# ---------------------------------------------------------------------------
# Null rate per column over time
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Null Rate per Column Over Time")

# Build a long-form DataFrame from column profiles across all runs
null_rate_rows = []
for p in profiles_sorted:
    for cp in p.get("column_profiles", []):
        null_rate_rows.append(
            {
                "profiled_at": p["profiled_at"],
                "column_name": cp["column_name"],
                "null_rate": cp["null_rate"],
            }
        )

if null_rate_rows:
    df_nr = pd.DataFrame(null_rate_rows)
    columns_available = sorted(df_nr["column_name"].unique())
    selected_cols = st.multiselect(
        "Columns to display",
        columns_available,
        default=columns_available[:6],
    )
    if selected_cols:
        df_nr_filtered = df_nr[df_nr["column_name"].isin(selected_cols)]
        fig_nr = px.line(
            df_nr_filtered,
            x="profiled_at",
            y="null_rate",
            color="column_name",
            markers=True,
            title="Null Rate Trend by Column",
            template="plotly_dark",
            labels={"profiled_at": "Profile Time", "null_rate": "Null Rate", "column_name": "Column"},
        )
        st.plotly_chart(fig_nr, use_container_width=True)
else:
    st.info("No column profile data available.")

# ---------------------------------------------------------------------------
# Column quality grid (latest profile)
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Column Quality Grid (Latest Profile)")

latest = profiles_sorted[-1] if profiles_sorted else None
if latest and latest.get("column_profiles"):
    rows = []
    for cp in latest["column_profiles"]:
        null_pct = f"{cp['null_rate']*100:.1f}%"
        distinct_pct = f"{cp['distinct_rate']*100:.1f}%"

        # Colour code null rate
        nr = cp["null_rate"]
        if nr > 0.3:
            null_cell = f"🔴 {null_pct}"
        elif nr > 0.05:
            null_cell = f"🟡 {null_pct}"
        else:
            null_cell = f"🟢 {null_pct}"

        rows.append(
            {
                "Column": cp["column_name"],
                "Type": cp["data_type"],
                "Null Rate": null_cell,
                "Distinct Rate": distinct_pct,
                "Null Count": f"{cp['null_count']:,}",
                "Distinct Count": f"{cp['distinct_count']:,}",
                "Min": _fmt(cp.get("min_value")),
                "Max": _fmt(cp.get("max_value")),
                "Mean": _fmt(cp.get("mean_value")),
                "Std": _fmt(cp.get("std_value")),
                "P25": _fmt(cp.get("p25")),
                "Median": _fmt(cp.get("median_value")),
                "P75": _fmt(cp.get("p75")),
                "P95": _fmt(cp.get("p95")),
            }
        )

    df_grid = pd.DataFrame(rows)
    st.dataframe(df_grid, use_container_width=True, height=400)
else:
    st.info("No column profiles available for the latest run.")
