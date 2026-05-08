"""
Meridian Dashboard — Streamlit multi-page app entrypoint.

Configures global page settings, sidebar branding, and a global health summary.
"""

import os

import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000/api/v1").rstrip("/")

st.set_page_config(
    page_title="Meridian — Data Observability",
    page_icon="🔭",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---- Sidebar ----
with st.sidebar:
    st.markdown("## 🔭 Meridian")
    st.caption("Data Observability Platform")
    st.divider()
    st.markdown("**Navigate**")
    st.page_link("pages/1_Sources.py", label="Sources", icon="🗄️")
    st.page_link("pages/2_Profiles.py", label="Profiles", icon="📊")
    st.page_link("pages/3_Anomalies.py", label="Anomalies", icon="🚨")
    st.page_link("pages/4_Reports.py", label="Reports", icon="📋")
    st.divider()
    st.caption(f"API: `{API_URL}`")

# ---- Main ----
st.title("🔭 Meridian Data Observability")
st.markdown(
    "Monitor your data pipelines for **anomalies**, **schema drift**, "
    "**null-rate spikes**, and **volume drops** — all in one place."
)

# Global health summary
try:
    r = requests.get(f"{API_URL}/anomalies/summary", timeout=5)
    if r.ok:
        summary = r.json()
        total = summary.get("total", 0)
        unack = summary.get("unacknowledged", 0)
        by_sev = summary.get("by_severity", {})

        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Total Anomalies", total)
        col2.metric("Unacknowledged", unack, delta=None)
        col3.metric("🔴 Critical", by_sev.get("critical", 0))
        col4.metric("🟠 High", by_sev.get("high", 0))
        col5.metric("🟡 Medium", by_sev.get("medium", 0))

        # Source health overview
        sr = requests.get(f"{API_URL}/sources", timeout=5)
        if sr.ok:
            sources = sr.json().get("items", [])
            if sources:
                st.divider()
                st.subheader("Source Health Overview")
                cols = st.columns(min(len(sources), 4))
                for idx, src in enumerate(sources):
                    health = src.get("latest_health_score")
                    col = cols[idx % len(cols)]
                    if health is None:
                        badge = "⚪"
                        colour = "grey"
                    elif health >= 90:
                        badge = "🟢"
                        colour = "green"
                    elif health >= 70:
                        badge = "🟡"
                        colour = "orange"
                    else:
                        badge = "🔴"
                        colour = "red"
                    col.metric(
                        label=f"{badge} {src['name']}",
                        value=f"{health:.1f}" if health is not None else "N/A",
                        delta=None,
                        help=f"Source type: {src['source_type']}",
                    )
    else:
        st.info("No data yet. Add a source and run a profile to get started.")
except requests.exceptions.ConnectionError:
    st.error(f"Cannot connect to Meridian API at `{API_URL}`. Is the backend running?")
except Exception as exc:
    st.warning(f"Dashboard error: {exc}")

st.divider()
st.markdown(
    "<small>Meridian is open-source. "
    "[GitHub](https://github.com/your-org/meridian)</small>",
    unsafe_allow_html=True,
)
