"""Sources page — manage data sources and trigger profile runs."""

import os
import time

import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000/api/v1").rstrip("/")

st.set_page_config(page_title="Sources — Meridian", page_icon="🗄️", layout="wide")

st.title("🗄️ Data Sources")
st.caption("Connect to databases and files, then trigger profile runs.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def health_badge(score) -> str:
    if score is None:
        return "⚪ N/A"
    if score >= 90:
        return f"🟢 {score:.1f}"
    if score >= 70:
        return f"🟡 {score:.1f}"
    return f"🔴 {score:.1f}"


def fetch_sources() -> list[dict]:
    try:
        r = requests.get(f"{API_URL}/sources", timeout=10)
        r.raise_for_status()
        return r.json().get("items", [])
    except Exception as exc:
        st.error(f"Failed to fetch sources: {exc}")
        return []


# ---------------------------------------------------------------------------
# Source table
# ---------------------------------------------------------------------------

sources = fetch_sources()

if sources:
    st.subheader(f"Active Sources ({len(sources)})")

    for src in sources:
        health = src.get("latest_health_score")
        badge = health_badge(health)
        last_run = src.get("latest_profiled_at", "Never")
        if last_run and last_run != "Never":
            last_run = last_run.replace("T", " ")[:19]

        with st.expander(f"{badge}  **{src['name']}**  —  `{src['source_type']}`", expanded=False):
            col1, col2, col3 = st.columns([2, 2, 1])
            col1.markdown(f"**ID:** `{src['id']}`")
            col1.markdown(f"**Type:** {src['source_type']}")
            if src.get("connection_string"):
                # Mask password
                cs = src["connection_string"]
                if "@" in cs:
                    parts = cs.split("@")
                    masked = "***@" + parts[-1]
                else:
                    masked = cs[:20] + "..."
                col1.markdown(f"**Connection:** `{masked}`")
            if src.get("file_path"):
                col1.markdown(f"**File:** `{src['file_path']}`")

            col2.markdown(f"**Last profiled:** {last_run}")
            col2.markdown(f"**Health score:** {badge}")
            col2.markdown(f"**Created:** {src['created_at'][:10]}")

            with col3:
                if st.button("▶ Run Profile", key=f"profile_{src['id']}"):
                    with st.spinner("Running profiler ..."):
                        try:
                            r = requests.post(
                                f"{API_URL}/sources/{src['id']}/profile",
                                timeout=120,
                            )
                            r.raise_for_status()
                            data = r.json()
                            profiles = data.get("profiles", [])
                            if profiles:
                                p = profiles[0]
                                st.success(
                                    f"Profile complete! "
                                    f"Rows: {p['row_count']:,} | "
                                    f"Health: {p['health_score']:.1f} | "
                                    f"Anomalies: {p['anomaly_count']}"
                                )
                            else:
                                st.success("Profile run complete.")
                            time.sleep(1)
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Profile failed: {exc}")

                if st.button("🗑 Delete", key=f"del_{src['id']}"):
                    try:
                        requests.delete(f"{API_URL}/sources/{src['id']}", timeout=10)
                        st.warning("Source deactivated.")
                        time.sleep(0.5)
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Delete failed: {exc}")
else:
    st.info("No sources configured yet. Add one below.")

# ---------------------------------------------------------------------------
# Add Source form
# ---------------------------------------------------------------------------

st.divider()
st.subheader("➕ Add a New Source")

with st.form("add_source_form"):
    name = st.text_input("Source name", placeholder="My Production DB")
    source_type = st.selectbox("Source type", ["postgres", "csv", "parquet"])

    connection_string = st.text_input(
        "Connection string (for postgres)",
        placeholder="postgresql://user:pass@host:5432/dbname",
        type="password",
    )
    file_path = st.text_input(
        "File path (for csv / parquet)",
        placeholder="/data/my_file.csv",
    )

    submitted = st.form_submit_button("Add Source")

if submitted:
    if not name:
        st.error("Source name is required.")
    else:
        payload = {
            "name": name,
            "source_type": source_type,
            "connection_string": connection_string or None,
            "file_path": file_path or None,
        }
        try:
            r = requests.post(f"{API_URL}/sources", json=payload, timeout=10)
            if r.ok:
                st.success(f"Source '{name}' added!")
                time.sleep(0.5)
                st.rerun()
            else:
                st.error(f"Error {r.status_code}: {r.text}")
        except Exception as exc:
            st.error(f"Request failed: {exc}")
