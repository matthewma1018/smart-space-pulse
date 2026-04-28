"""
Smart Space Pulse — Customer Dashboard
"""
import os
import sys
import time
from datetime import datetime, timezone

import numpy as np
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cloud.dynamodb_storage import DynamoDBStorage
from processing.model.inference import score_from_samples
from processing.storage import Storage as LocalSqliteStorage
from visualization.heatmap import (
    REAL_LOCATION_ID,
    build_score_grid,
    quietest_cell,
    render_heatmap_html,
)

REFRESH_INTERVAL = 3

LOCATION_NAMES = {
    "library-1f":     "Internet Cafe · Lobby",
    "library-2f":     "Library · 2nd Floor",
    "study-room-3":   "Study Room 3",
    "working-2b":     "Workspace 2B",
    "lounge-quiet-1": "Quiet Lounge",
    "gaming-lounge-1":"Gaming Lounge",
    "cafe-2a":        "Café 2A",
    "lecture-hall-b": "Lecture Hall B",
    "event-space-1":  "Event Space",
}


def friendly(lid):
    return LOCATION_NAMES.get(lid, lid.replace("-", " ").title())


def time_ago(ts_utc_str):
    if not ts_utc_str:
        return "just now"
    try:
        ts = datetime.fromisoformat(ts_utc_str.replace("Z", "+00:00"))
        secs = int((datetime.now(timezone.utc) - ts).total_seconds())
        if secs < 5:
            return "just now"
        if secs < 60:
            return f"{secs}s ago"
        if secs < 3600:
            return f"{secs // 60}m ago"
        return f"{secs // 3600}h ago"
    except Exception:
        return ts_utc_str[11:19] if len(ts_utc_str) > 18 else ts_utc_str


st.set_page_config(
    page_title="SpacePulse",
    page_icon="🔊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
    .block-container { padding-top: 1.1rem; padding-bottom: 0.5rem; }
    #MainMenu, footer, header { visibility: hidden; }

    .app-title {
        font-size: 1.75rem; font-weight: 800;
        color: #111827; letter-spacing: -0.02em; margin: 0;
    }
    .app-tagline { font-size: 0.88rem; color: #6b7280; margin: 2px 0 0 0; }

    .live-pill {
        display: inline-flex; align-items: center; gap: 6px;
        background: #ecfdf5; color: #065f46;
        border: 1px solid #6ee7b7; border-radius: 999px;
        padding: 4px 12px; font-size: 0.78rem; font-weight: 600;
    }
    .live-dot {
        width: 7px; height: 7px; border-radius: 50%;
        background: #10b981;
        animation: blink 2s ease-in-out infinite;
    }
    @keyframes blink {
        0%, 100% { opacity: 1; } 50% { opacity: 0.25; }
    }

    .rec-banner {
        background: linear-gradient(120deg, #ecfdf5 0%, #d1fae5 100%);
        border: 1.5px solid #a7f3d0; border-radius: 14px;
        padding: 1rem 1.5rem; margin-bottom: 1.1rem;
        display: flex; align-items: center; gap: 16px;
    }
    .rec-icon { font-size: 2rem; line-height: 1; }
    .rec-eyebrow {
        font-size: 0.72rem; font-weight: 700; color: #065f46;
        text-transform: uppercase; letter-spacing: 0.07em; margin: 0;
    }
    .rec-name { font-size: 1.25rem; font-weight: 800; color: #064e3b; margin: 3px 0 0; }

    .busy-banner {
        background: #fef2f2; border: 1.5px solid #fecaca;
        border-radius: 14px; padding: 1rem 1.5rem; margin-bottom: 1.1rem;
        color: #7f1d1d;
    }

    .space-card {
        border: 1.5px solid #e5e7eb; border-radius: 14px;
        padding: 1.1rem 1.3rem; background: #fff;
        box-shadow: 0 1px 4px rgba(0,0,0,0.05);
        margin-bottom: 0.85rem;
    }
    .card-quiet    { border-top: 4px solid #10b981; }
    .card-busy     { border-top: 4px solid #ef4444; }
    .card-changing { border-top: 4px solid #f59e0b; }

    .card-location { font-size: 1rem; font-weight: 700; color: #111827; margin: 0 0 4px 0; }
    .card-status   { font-size: 0.9rem; font-weight: 600; margin: 0; }
    .s-quiet    { color: #065f46; }
    .s-busy     { color: #991b1b; }
    .s-changing { color: #92400e; }

    .bar-track { background:#f3f4f6; border-radius:999px; height:9px; margin:10px 0 6px; overflow:hidden; }
    .bar-fill  { height:9px; border-radius:999px; transition: width 0.5s ease; }

    .card-meta { font-size: 0.76rem; color: #9ca3af; margin: 0; }

    .section-label {
        font-size: 0.72rem; font-weight: 700; color: #9ca3af;
        text-transform: uppercase; letter-spacing: 0.09em;
        margin: 1rem 0 0.4rem 0;
    }

    /* ── Model comparison strip ── */
    .model-compare {
        display: flex; gap: 10px;
        margin-top: 10px; padding-top: 8px;
        border-top: 1px solid #f3f4f6;
    }
    .model-col { flex: 1; }
    .model-name {
        font-size: 0.68rem; font-weight: 700; color: #9ca3af;
        text-transform: uppercase; letter-spacing: 0.06em; margin: 0 0 3px 0;
    }
    .model-mini-track {
        background: #f3f4f6; border-radius: 999px; height: 5px;
        overflow: hidden; margin-bottom: 3px;
    }
    .model-mini-fill { height: 5px; border-radius: 999px; }
    .model-verdict { font-size: 0.75rem; font-weight: 600; }
    .agree-badge {
        font-size: 0.68rem; font-weight: 600; color: #6366f1;
        background: #eef2ff; border-radius: 999px;
        padding: 1px 8px; margin-left: 6px;
    }
    .disagree-badge {
        font-size: 0.68rem; font-weight: 600; color: #d97706;
        background: #fffbeb; border-radius: 999px;
        padding: 1px 8px; margin-left: 6px;
    }
</style>
""", unsafe_allow_html=True)


# ── Storage helpers ───────────────────────────────────────────────────────────
# Try the cloud (DynamoDB → carries logistic scores from the Lambda).
# If AWS is unreachable, fall back to local SQLite written by
# processing/ingestor.py — the LSTM half of the pipeline keeps working.

@st.cache_resource
def get_storage():
    try:
        cloud = DynamoDBStorage()
        cloud.list_states()  # one round-trip to verify creds + reachability
        return cloud, True
    except Exception as e:
        print(f"[dashboard] DynamoDB unavailable ({e}) — using local SQLite fallback")
        return LocalSqliteStorage(), False


def load_current_states(storage):
    return [
        {
            "location_id": it["location_id"],
            "state":       it["state"],
            "score":       float(it["score"]),
            "updated_at":  it["updated_at"],
        }
        for it in storage.list_states()
    ]


def load_recent_telemetry(storage, location_id, limit=90):
    return storage.query_recent(location_id, n=limit)


def load_last_30_spl(storage, location_id):
    items = storage.query_recent(location_id, n=30)
    samples = [it["spl_db"] for it in items]
    return samples if len(samples) == 30 else None


def load_latest_spl(storage, location_id):
    items = storage.query_recent(location_id, n=1)
    if not items:
        return None, None
    return items[-1]["spl_db"], items[-1]["ts_utc"]


# ── Widget helpers ────────────────────────────────────────────────────────────

def noise_bar(spl_db):
    pct = max(4, min(100, int((max(spl_db, 30) - 30) / 70 * 100)))
    color = "#10b981" if spl_db < 55 else ("#f59e0b" if spl_db < 70 else "#ef4444")
    return (
        f'<div class="bar-track">'
        f'<div class="bar-fill" style="width:{pct}%;background:{color};"></div>'
        f'</div>'
    )


def card_attrs(state):
    return {
        "suitable":      ("card-quiet",   "🟢 Quiet",   "s-quiet"),
        "not_suitable":  ("card-busy",    "🔴 Busy",    "s-busy"),
        "transitioning": ("card-changing","🟡 Changing","s-changing"),
    }.get(state, ("card-changing", "⚪ Unknown", "s-changing"))


def model_compare_html(lstm_score, logistic_score):
    """Two-column mini widget showing both model scores."""
    def _col(name, score):
        if score is None:
            return (
                f'<div class="model-col">'
                f'<p class="model-name">{name}</p>'
                f'<p class="model-verdict" style="color:#9ca3af;">N/A</p>'
                f'</div>'
            )
        pct   = round(score)
        color = "#10b981" if score >= 65 else ("#f59e0b" if score >= 55 else "#ef4444")
        label = "Quiet" if score >= 65 else ("Uncertain" if score >= 55 else "Busy")
        vcls  = "s-quiet" if score >= 65 else ("s-changing" if score >= 55 else "s-busy")
        return (
            f'<div class="model-col">'
            f'<p class="model-name">{name}</p>'
            f'<div class="model-mini-track">'
            f'<div class="model-mini-fill" style="width:{pct}%;background:{color};"></div>'
            f'</div>'
            f'<span class="model-verdict {vcls}">{label}</span>'
            f'<span style="font-size:0.7rem;color:#9ca3af;"> {pct}</span>'
            f'</div>'
        )

    agree = (
        lstm_score is not None and logistic_score is not None and
        (lstm_score >= 65) == (logistic_score >= 65) and
        (lstm_score < 55) == (logistic_score < 55)
    )
    badge = (
        '<span class="agree-badge">Models agree</span>' if agree
        else '<span class="disagree-badge">Models differ</span>'
    ) if logistic_score is not None else ""

    return (
        f'<div class="model-compare">'
        f'{_col("LSTM", lstm_score)}'
        f'{_col("Logistic", logistic_score)}'
        f'</div>'
        f'<div style="margin-top:4px;">{badge}</div>'
    )


def make_noise_chart(data):
    fig = go.Figure()
    if not data:
        fig.update_layout(
            height=270, paper_bgcolor="white", plot_bgcolor="white",
            annotations=[dict(text="Waiting for data…", showarrow=False,
                              font=dict(size=13, color="#9ca3af"),
                              xref="paper", yref="paper", x=0.5, y=0.5)],
        )
        return fig

    ts  = [d["ts_utc"][11:19] for d in data]
    spl = [d["spl_db"] for d in data]

    for y0, y1, fc in [
        (0,  55, "rgba(16,185,129,0.07)"),
        (55, 70, "rgba(245,158,11,0.08)"),
        (70, 110,"rgba(239,68,68,0.07)"),
    ]:
        fig.add_hrect(y0=y0, y1=y1, fillcolor=fc, line_width=0)

    for y, lc, txt in [(55, "#10b981", "Quiet"), (70, "#ef4444", "Loud")]:
        fig.add_hline(y=y, line_dash="dot", line_color=lc, line_width=1.2, opacity=0.6,
                      annotation_text=txt, annotation_position="right",
                      annotation_font=dict(size=10, color=lc))

    fig.add_trace(go.Scatter(
        x=ts, y=spl, name="Noise level",
        line=dict(color="#6366f1", width=2),
        fill="tozeroy", fillcolor="rgba(99,102,241,0.07)",
        hovertemplate="%{x}  %{y:.1f} dB<extra></extra>",
    ))

    if len(spl) >= 5:
        rolled = [sum(spl[max(0, i - 4):i + 1]) / len(spl[max(0, i - 4):i + 1])
                  for i in range(len(spl))]
        fig.add_trace(go.Scatter(
            x=ts, y=rolled, name="Trend",
            line=dict(color="#f59e0b", width=1.5, dash="dash"),
            hovertemplate="%{x}  trend %{y:.1f} dB<extra></extra>",
        ))

    fig.update_layout(
        height=270,
        margin=dict(l=40, r=80, t=15, b=35),
        yaxis=dict(title="Noise (dB)", range=[30, 100], gridcolor="#f3f4f6"),
        xaxis=dict(title="", gridcolor="#f3f4f6"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(size=11)),
        paper_bgcolor="white", plot_bgcolor="white",
        hovermode="x unified",
    )
    return fig


# ── App ───────────────────────────────────────────────────────────────────────

storage, cloud_up = get_storage()

hdr_l, hdr_r = st.columns([3, 1])
with hdr_l:
    st.markdown(
        '<p class="app-title">🔊 SpacePulse</p>'
        '<p class="app-tagline">Find a quiet spot · real-time noise monitoring</p>',
        unsafe_allow_html=True,
    )
with hdr_r:
    st.markdown(
        '<div style="text-align:right;padding-top:0.55rem;">'
        '<span class="live-pill"><span class="live-dot"></span>Live</span>'
        '</div>',
        unsafe_allow_html=True,
    )

st.markdown("<div style='height:0.6rem'></div>", unsafe_allow_html=True)

if not cloud_up:
    st.markdown(
        '<div style="background:#fffbeb;border:1.5px solid #fcd34d;border-radius:10px;'
        'padding:8px 14px;margin-bottom:0.8rem;font-size:0.82rem;color:#92400e;">'
        '☁️ Cloud unreachable — running on local SQLite. '
        'LSTM is live; logistic scores will show N/A until AWS is back.'
        '</div>',
        unsafe_allow_html=True,
    )

states = load_current_states(storage)

tab_spaces, tab_heatmap = st.tabs(["Spaces", "Heatmap"])

with tab_spaces:
    if not states:
        st.markdown(
            '<div class="busy-banner">Sensors are warming up — data will appear shortly.</div>',
            unsafe_allow_html=True,
        )
    else:
        # Recommendation banner
        quiet_spots = [s for s in states if s["state"] == "suitable"]
        if quiet_spots:
            best = max(quiet_spots, key=lambda s: s["score"])
            st.markdown(
                f'<div class="rec-banner">'
                f'  <div class="rec-icon">✨</div>'
                f'  <div>'
                f'    <p class="rec-eyebrow">Best spot right now</p>'
                f'    <p class="rec-name">{friendly(best["location_id"])}</p>'
                f'  </div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="busy-banner">'
                '<strong>All spaces are currently busy.</strong> '
                'Conditions change quickly — check back in a few minutes.'
                '</div>',
                unsafe_allow_html=True,
            )

        st.markdown('<p class="section-label">All spaces</p>', unsafe_allow_html=True)

        cols = st.columns(2)
        for i, s in enumerate(states):
            spl_val, _ = load_latest_spl(storage, s["location_id"])
            card_cls, status_txt, status_cls = card_attrs(s["state"])
            upd      = time_ago(s["updated_at"])
            spl_text = f"{spl_val:.1f} dB" if spl_val is not None else "—"
            bar      = noise_bar(spl_val) if spl_val is not None else ""
            noise_label = (
                "Low noise"      if spl_val is not None and spl_val < 55 else
                "Moderate noise" if spl_val is not None and spl_val < 70 else
                "High noise"     if spl_val is not None else ""
            )

            # Logistic score comes from the cloud Lambda (already in ssp-state).
            # When AWS is down we're reading from local SQLite, where the
            # `score` column was written by the LSTM windower — not a logistic
            # value, so we suppress it rather than mislabel it.
            spl_30         = load_last_30_spl(storage, s["location_id"])
            lstm_score     = score_from_samples(spl_30) if spl_30 else None
            logistic_score = s["score"] if cloud_up else None
            compare        = model_compare_html(lstm_score, logistic_score)

            with cols[i % 2]:
                st.markdown(
                    f'<div class="space-card {card_cls}">'
                    f'  <p class="card-location">{friendly(s["location_id"])}</p>'
                    f'  <p class="card-status {status_cls}">{status_txt}</p>'
                    f'  {bar}'
                    f'  <p class="card-meta">{noise_label} · {spl_text} · {upd}</p>'
                    f'  {compare}'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        st.markdown("<div style='height:0.3rem'></div>", unsafe_allow_html=True)
        st.markdown('<p class="section-label">Noise over time</p>', unsafe_allow_html=True)

        location_ids   = [s["location_id"] for s in states]
        friendly_names = [friendly(lid) for lid in location_ids]
        sel_idx = st.selectbox(
            "Space",
            range(len(location_ids)),
            format_func=lambda i: friendly_names[i],
            key="live_sel",
            label_visibility="collapsed",
        )
        recent = load_recent_telemetry(storage, location_ids[sel_idx], limit=30)
        st.plotly_chart(make_noise_chart(recent), use_container_width=True)

with tab_heatmap:
    st.markdown(
        '<p class="section-label">Internet Cafe · live noise heatmap</p>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Real Core2 device sits at the ★ corner (row 0, col 0). "
        "The other 24 cells are simulated and spatially coupled to the real "
        "device — a spike at ★ propagates outward with distance-based decay. "
        "All 25 cells are scored with the **LSTM** (local PyTorch inference); "
        "the cloud Lambda's logistic score is shown only on the Spaces tab."
    )

    real_30 = load_last_30_spl(storage, REAL_LOCATION_ID)
    rng = np.random.default_rng()
    scores = build_score_grid(real_30, rng, score_from_samples)
    r_q, c_q, s_q = quietest_cell(scores)

    st.markdown(
        f'<div class="rec-banner">'
        f'  <div class="rec-icon">📍</div>'
        f'  <div>'
        f'    <p class="rec-eyebrow">Quietest spot right now</p>'
        f'    <p class="rec-name">Row {r_q}, Col {c_q} · score {int(round(s_q))}</p>'
        f'  </div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.markdown(render_heatmap_html(scores), unsafe_allow_html=True)

time.sleep(REFRESH_INTERVAL)
st.rerun()
