"""
Smart Space Pulse — Streamlit Dashboard

Tab 1: Live view — gauges and time-series per location.
Tab 2: Historical — date picker, SPL histogram, occupancy heatmap.

Usage:
    streamlit run visualization/dashboard.py
"""
import os
import sqlite3
import sys
import time

import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_PATH = os.getenv("SQLITE_PATH", "data/ssp.db")
REFRESH_INTERVAL = 3


@st.cache_resource
def get_connection():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def load_current_states(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT location_id, state, score, updated_at FROM location_state"
    ).fetchall()
    return [
        {"location_id": r[0], "state": r[1], "score": r[2], "updated_at": r[3]}
        for r in rows
    ]


def load_recent_telemetry(conn, location_id: str, limit: int = 60) -> list[dict]:
    rows = conn.execute(
        "SELECT ts_utc, spl_db FROM raw_telemetry "
        "WHERE location_id = ? "
        "ORDER BY id DESC LIMIT ?",
        (location_id, limit),
    ).fetchall()
    return [
        {"ts_utc": r[0], "spl_db": r[1]}
        for r in reversed(rows)
    ]


def load_historical_telemetry(conn, location_id: str, date_str: str) -> list[dict]:
    rows = conn.execute(
        "SELECT ts_utc, spl_db FROM raw_telemetry "
        "WHERE location_id = ? AND ts_utc LIKE ? "
        "ORDER BY ts_utc",
        (location_id, date_str + "%"),
    ).fetchall()
    return [
        {"ts_utc": r[0], "spl_db": r[1]}
        for r in rows
    ]


def load_state_history(conn, location_id: str, date_str: str) -> list[dict]:
    rows = conn.execute(
        "SELECT location_id, state, score, updated_at FROM location_state "
        "WHERE location_id = ? AND updated_at LIKE ? "
        "ORDER BY updated_at",
        (location_id, date_str + "%"),
    ).fetchall()
    return [
        {"location_id": r[0], "state": r[1], "score": r[2], "updated_at": r[3]}
        for r in rows
    ]


def state_color(state: str) -> str:
    if state == "suitable":
        return "#2ecc71"
    elif state == "not_suitable":
        return "#e74c3c"
    return "#f39c12"


def make_gauge(score: float, location_id: str, state: str) -> go.Figure:
    color = state_color(state)
    label = state.replace("_", " ").title()
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        title={"text": f"{location_id}<br><span style='color:{color};'>{label}</span>"},
        gauge={
            "axis": {"range": [0, 100]},
            "bar": {"color": color},
            "steps": [
                {"range": [0, 55], "color": "#fde8e8"},
                {"range": [55, 65], "color": "#fef3cd"},
                {"range": [65, 100], "color": "#d4edda"},
            ],
            "threshold": {
                "line": {"color": "black", "width": 2},
                "thickness": 0.75,
                "value": score,
            },
        },
    ))
    fig.update_layout(height=280, margin=dict(l=20, r=20, t=60, b=10))
    return fig


def make_timeseries(data: list[dict], title: str) -> go.Figure:
    if not data:
        return go.Figure().update_layout(title=f"{title} (no data)")
    ts = [d["ts_utc"][11:19] for d in data]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=ts, y=[d["spl_db"] for d in data],
                             name="SPL (dB)", line=dict(color="#e74c3c")))
    fig.update_layout(
        title=title,
        height=350,
        margin=dict(l=50, r=20, t=40, b=30),
        yaxis=dict(title="SPL (dB)"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


def make_spl_histogram(data: list[dict], title: str) -> go.Figure:
    if not data:
        return go.Figure().update_layout(title=f"{title} (no data)")
    spl_values = [d["spl_db"] for d in data]
    fig = go.Figure(go.Histogram(x=spl_values, nbinsx=30, marker_color="#3498db"))
    fig.update_layout(
        title=title,
        xaxis_title="SPL (dB)",
        yaxis_title="Count",
        height=350,
        margin=dict(l=50, r=20, t=40, b=30),
    )
    return fig


def make_occupancy_heatmap(conn, date_str: str) -> go.Figure:
    rows = conn.execute(
        "SELECT location_id, substr(ts_utc, 12, 2) as hour, "
        "  CASE WHEN spl_db < 55 THEN 1 ELSE 0 END as quiet_flag "
        "FROM raw_telemetry WHERE ts_utc LIKE ? "
        "GROUP BY location_id, hour "
        "ORDER BY location_id, hour",
        (date_str + "%",),
    ).fetchall()

    if not rows:
        return go.Figure().update_layout(title="Occupancy Heatmap (no data)")

    locations = sorted(set(r[0] for r in rows))
    hours = [f"{h:02d}" for h in range(24)]
    z = [[0] * 24 for _ in locations]

    for r in rows:
        li = locations.index(r[0])
        hi = int(r[1])
        z[li][hi] = r[2]

    fig = go.Figure(go.Heatmap(
        z=z,
        x=hours,
        y=locations,
        colorscale=[[0, "#e74c3c"], [1, "#2ecc71"]],
        colorbar={"title": "Quiet %"},
    ))
    fig.update_layout(
        title="Occupancy Suitability by Hour",
        xaxis_title="Hour (UTC)",
        yaxis_title="Location",
        height=max(250, len(locations) * 60 + 100),
        margin=dict(l=100, r=20, t=40, b=30),
    )
    return fig


# ── App ──

st.set_page_config(page_title="Smart Space Pulse", layout="wide")
st.title("Smart Space Pulse")

conn = get_connection()

tab_live, tab_hist = st.tabs(["Live View", "Historical"])

with tab_live:
    states = load_current_states(conn)

    if not states:
        st.info("No location data yet. Run the pipeline to populate the database.")
        time.sleep(REFRESH_INTERVAL)
        st.rerun()

    # Gauges row
    cols = st.columns(min(len(states), 4))
    for i, s in enumerate(states):
        with cols[i % len(cols)]:
            st.plotly_chart(
                make_gauge(s["score"], s["location_id"], s["state"]),
                width="stretch",
            )

    # Time-series for selected location
    location_options = [s["location_id"] for s in states]
    selected = st.selectbox("Select location", location_options, key="live_loc")
    recent = load_recent_telemetry(conn, selected, limit=60)
    st.plotly_chart(
        make_timeseries(recent, f"Last 60 readings — {selected}"),
        width="stretch",
    )

    st.caption(f"Auto-refresh every {REFRESH_INTERVAL}s. Data from {DB_PATH}")
    time.sleep(REFRESH_INTERVAL)
    st.rerun()

with tab_hist:
    locations = [r[0] for r in conn.execute(
        "SELECT DISTINCT location_id FROM raw_telemetry"
    ).fetchall()]

    if not locations:
        st.info("No telemetry data available for historical analysis.")
        st.stop()

    col_loc, col_date = st.columns(2)
    with col_loc:
        hist_loc = st.selectbox("Location", locations, key="hist_loc")
    with col_date:
        hist_date = st.date_input("Date").isoformat()

    hist_data = load_historical_telemetry(conn, hist_loc, hist_date)

    ts_fig, hist_fig = st.columns(2)
    with ts_fig:
        st.plotly_chart(
            make_timeseries(hist_data, f"Time-Series — {hist_loc} ({hist_date})"),
            width="stretch",
        )
    with hist_fig:
        st.plotly_chart(
            make_spl_histogram(hist_data, f"SPL Distribution — {hist_loc} ({hist_date})"),
            width="stretch",
        )

    st.plotly_chart(
        make_occupancy_heatmap(conn, hist_date),
        width="stretch",
    )
