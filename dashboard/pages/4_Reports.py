"""Reports page — full quality report with Plotly visualisations."""

import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000/api/v1").rstrip("/")

st.set_page_config(page_title="Reports — Meridian", page_icon="📋", layout="wide")

st.title("📋 Quality Reports")
st.caption("Full pipeline health reports with trend analysis and column quality matrices.")


# ---------------------------------------------------------------------------
# Source selection
# ---------------------------------------------------------------------------

def fetch_sources() -> list[dict]:
    try:
        r = requests.get(f"{API_URL}/sources", timeout=10)
        r.raise_for_status()
        return r.json().get("items", [])
    except Exception:
        return []


sources = fetch_sources()
if not sources:
    st.info("No sources found. Add a source and run a profile first.")
    st.stop()

source_map = {s["name"]: s["id"] for s in sources}
selected_name = st.selectbox("Select Source", list(source_map.keys()))
selected_id = source_map[selected_name]

# ---------------------------------------------------------------------------
# Fetch report
# ---------------------------------------------------------------------------

try:
    r = requests.get(f"{API_URL}/reports/{selected_id}", timeout=15)
    r.raise_for_status()
    report = r.json()
except Exception as exc:
    st.error(f"Failed to load report: {exc}")
    st.stop()

# ---------------------------------------------------------------------------
# Header metrics
# ---------------------------------------------------------------------------

st.divider()
health = report.get("overall_health_score", 100)
h1, h2, h3, h4 = st.columns(4)
h1.metric("Overall Health Score", f"{health:.1f} / 100")
h2.metric("Tables Profiled", report.get("tables_profiled", 0))
h3.metric("Profile Runs", report.get("total_profiles", 0))
h4.metric("Anomalies (7d)", report.get("recent_anomaly_count", 0))

# ---------------------------------------------------------------------------
# Health score gauge
# ---------------------------------------------------------------------------

st.divider()
col_gauge, col_donut = st.columns(2)

with col_gauge:
    st.subheader("Health Score Gauge")
    fig_gauge = go.Figure(
        go.Indicator(
            mode="gauge+number+delta",
            value=health,
            domain={"x": [0, 1], "y": [0, 1]},
            title={"text": "Pipeline Health", "font": {"size": 20, "color": "white"}},
            delta={"reference": 100, "increasing": {"color": "#00ff7f"}},
            gauge={
                "axis": {"range": [0, 100], "tickcolor": "white"},
                "bar": {"color": "#00d4ff"},
                "bgcolor": "#1e1e2e",
                "bordercolor": "gray",
                "steps": [
                    {"range": [0, 50], "color": "#3d1515"},
                    {"range": [50, 70], "color": "#3d2d15"},
                    {"range": [70, 90], "color": "#2d3d15"},
                    {"range": [90, 100], "color": "#153d15"},
                ],
                "threshold": {
                    "line": {"color": "red", "width": 4},
                    "thickness": 0.75,
                    "value": 70,
                },
            },
        )
    )
    fig_gauge.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0e1117",
        height=300,
        margin=dict(l=20, r=20, t=40, b=20),
    )
    st.plotly_chart(fig_gauge, use_container_width=True)

with col_donut:
    st.subheader("Anomaly Breakdown (7d)")
    by_sev = report.get("anomaly_breakdown", {})
    if by_sev:
        colours = {
            "critical": "#ff4444",
            "high": "#ff8c00",
            "medium": "#ffd700",
            "low": "#6495ed",
        }
        labels = list(by_sev.keys())
        values = list(by_sev.values())
        colour_list = [colours.get(l, "#aaa") for l in labels]

        fig_donut = go.Figure(
            go.Pie(
                labels=labels,
                values=values,
                hole=0.5,
                marker_colors=colour_list,
            )
        )
        fig_donut.update_layout(
            template="plotly_dark",
            paper_bgcolor="#0e1117",
            height=300,
            legend=dict(font=dict(color="white")),
            margin=dict(l=20, r=20, t=40, b=20),
        )
        st.plotly_chart(fig_donut, use_container_width=True)
    else:
        st.success("No anomalies detected in the last 7 days!")

# ---------------------------------------------------------------------------
# Row count + health score trends
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Trend Charts")

tr1, tr2 = st.columns(2)

with tr1:
    rc_trend = report.get("row_count_trend", [])
    if rc_trend:
        df_rc = pd.DataFrame(rc_trend)
        fig_rc = px.area(
            df_rc, x="profiled_at", y="row_count",
            title="Row Count Over Time",
            template="plotly_dark",
            labels={"profiled_at": "Time", "row_count": "Rows"},
        )
        fig_rc.update_traces(line_color="#00d4ff", fillcolor="rgba(0, 212, 255, 0.15)")
        st.plotly_chart(fig_rc, use_container_width=True)
    else:
        st.info("No row count trend data.")

with tr2:
    hs_trend = report.get("health_trend", [])
    if hs_trend:
        df_hs = pd.DataFrame(hs_trend)
        fig_hs = px.area(
            df_hs, x="profiled_at", y="health_score",
            title="Health Score Over Time",
            template="plotly_dark",
            labels={"profiled_at": "Time", "health_score": "Health Score"},
            range_y=[0, 105],
        )
        fig_hs.update_traces(line_color="#00ff7f", fillcolor="rgba(0, 255, 127, 0.15)")
        fig_hs.add_hline(y=70, line_dash="dash", line_color="orange")
        st.plotly_chart(fig_hs, use_container_width=True)
    else:
        st.info("No health trend data.")

# ---------------------------------------------------------------------------
# Anomaly timeline bar chart
# ---------------------------------------------------------------------------

timeline = report.get("anomaly_timeline", [])
if timeline:
    st.divider()
    st.subheader("Anomaly Timeline (Last 7 Days)")
    df_tl = pd.DataFrame(timeline)
    fig_tl = px.bar(
        df_tl, x="date", y="count",
        title="Anomalies Detected per Day",
        template="plotly_dark",
        labels={"date": "Date", "count": "Anomalies"},
        color="count",
        color_continuous_scale="Reds",
    )
    st.plotly_chart(fig_tl, use_container_width=True)

# ---------------------------------------------------------------------------
# Column quality heatmap
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Column Quality Heatmap")

matrix = report.get("column_quality_matrix", [])
if matrix:
    df_mat = pd.DataFrame(matrix)

    # Build null_rate pivot: rows=columns, values=null_rate
    pivot_data = df_mat[["column_name", "null_rate", "distinct_rate"]].copy()
    pivot_data["null_rate_pct"] = pivot_data["null_rate"] * 100
    pivot_data["distinct_rate_pct"] = pivot_data["distinct_rate"] * 100

    # Null rate heatmap
    fig_hm = go.Figure(
        go.Heatmap(
            z=pivot_data["null_rate_pct"].values.reshape(1, -1),
            x=pivot_data["column_name"].tolist(),
            y=["Null Rate %"],
            colorscale="RdYlGn_r",
            zmin=0,
            zmax=100,
            text=[[f"{v:.1f}%" for v in pivot_data["null_rate_pct"]]],
            texttemplate="%{text}",
            showscale=True,
        )
    )
    fig_hm.update_layout(
        title="Null Rate per Column (%)",
        template="plotly_dark",
        paper_bgcolor="#0e1117",
        height=200,
        margin=dict(l=80, r=20, t=40, b=80),
        xaxis=dict(tickangle=-45),
    )
    st.plotly_chart(fig_hm, use_container_width=True)
else:
    st.info("No column quality data available.")

# ---------------------------------------------------------------------------
# Recent anomalies table
# ---------------------------------------------------------------------------

st.divider()
st.subheader("Recent Anomalies")

recent = report.get("recent_anomalies", [])
if recent:
    SEVERITY_EMOJI = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}
    rows = []
    for a in recent:
        rows.append(
            {
                "Severity": f"{SEVERITY_EMOJI.get(a['severity'], '')} {a['severity'].upper()}",
                "Type": a["anomaly_type"].replace("_", " ").title(),
                "Column": a.get("column_name") or "(table-level)",
                "Metric": a["metric_name"],
                "Expected": f"{a['expected_value']:.4f}",
                "Actual": f"{a['actual_value']:.4f}",
                "Score": f"{a['deviation_score']:.2f}",
                "Detector": a["detector"],
                "Detected": a["detected_at"][:19].replace("T", " "),
                "ACK": "✅" if a["acknowledged"] else "",
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, height=400)
else:
    st.success("No recent anomalies in the last 7 days.")
