"""Anomalies page — feed, filters, and acknowledgement."""

import os
import time

import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000/api/v1").rstrip("/")

st.set_page_config(page_title="Anomalies — Meridian", page_icon="🚨", layout="wide")

st.title("🚨 Anomaly Feed")
st.caption("Detected data quality issues, sorted by most recent.")

# ---------------------------------------------------------------------------
# Severity config
# ---------------------------------------------------------------------------

SEVERITY_CONFIG = {
    "critical": {"emoji": "🔴", "colour": "#ff4444"},
    "high": {"emoji": "🟠", "colour": "#ff8c00"},
    "medium": {"emoji": "🟡", "colour": "#ffd700"},
    "low": {"emoji": "🔵", "colour": "#6495ed"},
}

ANOMALY_TYPE_LABELS = {
    "null_rate_spike": "Null Rate Spike",
    "volume_drop": "Volume Drop",
    "schema_drift": "Schema Drift",
    "distribution_shift": "Distribution Shift",
    "outlier": "Outlier",
}


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


def fetch_anomalies(
    source_id=None, severity=None, anomaly_type=None, acknowledged=None
) -> list[dict]:
    params = {"limit": 200}
    if source_id:
        params["source_id"] = source_id
    if severity:
        params["severity"] = severity
    if anomaly_type:
        params["anomaly_type"] = anomaly_type
    if acknowledged is not None:
        params["acknowledged"] = str(acknowledged).lower()
    try:
        r = requests.get(f"{API_URL}/anomalies", params=params, timeout=10)
        r.raise_for_status()
        return r.json().get("items", [])
    except Exception as exc:
        st.error(f"Failed to fetch anomalies: {exc}")
        return []


# ---------------------------------------------------------------------------
# Filters sidebar panel
# ---------------------------------------------------------------------------

sources = fetch_sources()
source_map = {"All sources": None}
source_map.update({s["name"]: s["id"] for s in sources})

with st.expander("🔎 Filters", expanded=True):
    col1, col2, col3, col4 = st.columns(4)

    selected_source_name = col1.selectbox("Source", list(source_map.keys()))
    selected_source_id = source_map[selected_source_name]

    severity_opts = ["All", "critical", "high", "medium", "low"]
    selected_severity = col2.selectbox("Severity", severity_opts)
    selected_severity = None if selected_severity == "All" else selected_severity

    type_opts = ["All"] + list(ANOMALY_TYPE_LABELS.keys())
    selected_type_raw = col3.selectbox("Anomaly Type", type_opts)
    selected_type = None if selected_type_raw == "All" else selected_type_raw

    ack_opts = {"All": None, "Unacknowledged only": False, "Acknowledged only": True}
    selected_ack_label = col4.selectbox("Status", list(ack_opts.keys()))
    selected_ack = ack_opts[selected_ack_label]

# ---------------------------------------------------------------------------
# Fetch and display
# ---------------------------------------------------------------------------

anomalies = fetch_anomalies(
    source_id=selected_source_id,
    severity=selected_severity,
    anomaly_type=selected_type,
    acknowledged=selected_ack,
)

# Summary metrics
total = len(anomalies)
unack = sum(1 for a in anomalies if not a["acknowledged"])
by_sev = {}
for a in anomalies:
    sev = a["severity"]
    by_sev[sev] = by_sev.get(sev, 0) + 1

st.divider()
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Total Shown", total)
m2.metric("Unacknowledged", unack)
m3.metric("🔴 Critical", by_sev.get("critical", 0))
m4.metric("🟠 High", by_sev.get("high", 0))
m5.metric("🟡 Medium", by_sev.get("medium", 0))
st.divider()

if not anomalies:
    st.success("No anomalies match the current filters. Your data looks clean! 🎉")
    st.stop()

# ---------------------------------------------------------------------------
# Anomaly cards
# ---------------------------------------------------------------------------

for a in anomalies:
    sev = a["severity"]
    cfg = SEVERITY_CONFIG.get(sev, {"emoji": "⚪", "colour": "#aaa"})
    atype_label = ANOMALY_TYPE_LABELS.get(a["anomaly_type"], a["anomaly_type"])
    col_tag = f" · `{a['column_name']}`" if a.get("column_name") else ""
    ack_tag = " ✅" if a["acknowledged"] else ""

    header = f"{cfg['emoji']} **{sev.upper()}** — {atype_label}{col_tag}{ack_tag}"
    detected = a["detected_at"].replace("T", " ")[:19]

    with st.container(border=True):
        c1, c2 = st.columns([5, 1])

        with c1:
            st.markdown(header)
            st.markdown(f"_{a['description']}_")

            mc1, mc2, mc3, mc4 = st.columns(4)
            mc1.metric("Expected", f"{a['expected_value']:.4f}")
            mc2.metric("Actual", f"{a['actual_value']:.4f}")
            mc3.metric("Deviation Score", f"{a['deviation_score']:.2f}")
            mc4.caption(f"Detector: `{a['detector']}`")

            st.caption(f"Detected: {detected}  |  Metric: `{a['metric_name']}`")

        with c2:
            if not a["acknowledged"]:
                if st.button("Acknowledge", key=f"ack_{a['id']}"):
                    try:
                        r = requests.patch(
                            f"{API_URL}/anomalies/{a['id']}/acknowledge",
                            json={"acknowledged": True},
                            timeout=10,
                        )
                        r.raise_for_status()
                        st.success("Acknowledged")
                        time.sleep(0.4)
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Failed: {exc}")
            else:
                if st.button("Un-acknowledge", key=f"unack_{a['id']}"):
                    try:
                        r = requests.patch(
                            f"{API_URL}/anomalies/{a['id']}/acknowledge",
                            json={"acknowledged": False},
                            timeout=10,
                        )
                        r.raise_for_status()
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Failed: {exc}")
