"""
SpacePulse — 5x5 occupancy heatmap.

Real Core2 device sits at the (0, 0) corner of the grid. The other 24 cells
are simulated in-process: each cell has a stable per-session "personality"
(baseline dB, noise spread, coupling factor, burst probability) and is
spatially coupled to the real cell so a spike at (0, 0) propagates outward
with exponential decay.

All 25 cells are scored locally with the LSTM (`score_from_samples`) so the
heatmap is internally consistent — the cloud Lambda's logistic score is not
used here.
"""
from dataclasses import dataclass

import numpy as np
import plotly.graph_objects as go


GRID_ROWS, GRID_COLS = 5, 5
REAL_CELL = (0, 0)
REAL_LOCATION_ID = "library-1f"
REAL_BASELINE_DB = 50.0
DECAY = 2.0
COUPLING_GAIN = 2.0
STATIC_SEED = 7


@dataclass
class Zone:
    row: int
    col: int
    is_real: bool
    baseline_db: float   # static "personality": intrinsic ambient level
    sigma: float         # static: how noisy this cell is per-sample


def _build_floor_plan() -> list[Zone]:
    """
    Static per-cell personality (baseline + sigma) is fine because ±2 dB and
    σ ∈ [0.6, 1.2] are small enough that they don't flip cells across the
    LSTM's ~65 dB cutoff.

    Coupling weight is intentionally NOT jittered here: any static jitter on
    coupling would make specific cells *permanently* more receptive to the
    spike than their same-distance peers, which reads as a bug. Asymmetry
    instead comes from baseline + per-frame Gaussian noise.
    """
    rng = np.random.default_rng(STATIC_SEED)
    zones = []
    for r in range(GRID_ROWS):
        for c in range(GRID_COLS):
            is_real = (r, c) == REAL_CELL
            zones.append(Zone(
                row=r,
                col=c,
                is_real=is_real,
                baseline_db=48.0 + rng.uniform(-2.0, 2.0),
                sigma=rng.uniform(0.6, 1.2),
            ))
    return zones


FLOOR_PLAN: list[Zone] = _build_floor_plan()


def _chebyshev(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def build_score_grid(real_samples: list[float] | None, rng: np.random.Generator,
                     score_fn) -> np.ndarray:
    """
    real_samples: 30 most-recent SPL values from the real Core2 (or None if
                  not yet available; in that case we treat the real cell as
                  silent at REAL_BASELINE_DB).
    score_fn:     callable taking a 30-element SPL list, returning 0–100.
    """
    if real_samples is None or len(real_samples) < 30:
        real_arr = np.full(30, REAL_BASELINE_DB)
    else:
        real_arr = np.asarray(real_samples[-30:], dtype=float)

    real_excess = np.maximum(0.0, real_arr - REAL_BASELINE_DB)

    scores = np.zeros((GRID_ROWS, GRID_COLS))
    for z in FLOOR_PLAN:
        if z.is_real:
            samples = real_arr.tolist()
        else:
            d = _chebyshev((z.row, z.col), REAL_CELL)
            weight = min(float(np.exp(-d / DECAY)) * COUPLING_GAIN, 1.0)
            own = z.baseline_db + rng.normal(0.0, z.sigma, 30)
            samples = (own + real_excess * weight).tolist()
        scores[z.row, z.col] = float(score_fn(samples))
    return scores


def _score_to_hex(score: float) -> str:
    """Map 0–100 to a RdYlGn hex color via four anchor points."""
    anchors = [
        (0,   (0xd7, 0x30, 0x27)),
        (25,  (0xf4, 0x6d, 0x43)),
        (50,  (0xfe, 0xe0, 0x8b)),
        (75,  (0xa6, 0xd9, 0x6a)),
        (100, (0x1a, 0x98, 0x50)),
    ]
    score = max(0.0, min(100.0, score))
    for i in range(len(anchors) - 1):
        lo_s, lo_c = anchors[i]
        hi_s, hi_c = anchors[i + 1]
        if lo_s <= score <= hi_s:
            t = (score - lo_s) / (hi_s - lo_s)
            r = int(lo_c[0] + t * (hi_c[0] - lo_c[0]))
            g = int(lo_c[1] + t * (hi_c[1] - lo_c[1]))
            b = int(lo_c[2] + t * (hi_c[2] - lo_c[2]))
            return f"#{r:02x}{g:02x}{b:02x}"
    return "#1a9850"


def render_heatmap_html(scores: np.ndarray) -> str:
    """5×5 CSS-grid of monitor icons, one cell per zone."""
    cells = []
    for r in range(GRID_ROWS):
        for c in range(GRID_COLS):
            score = float(scores[r, c])
            is_real = (r, c) == REAL_CELL
            bg = _score_to_hex(score)
            label = int(round(score))

            if is_real:
                extra = (
                    "border:3px solid #1d4ed8;"
                    "box-shadow:0 0 14px rgba(29,78,216,0.45);"
                )
                badge = (
                    '<div style="font-size:0.62em;font-weight:700;color:#1d4ed8;'
                    'margin-bottom:2px;letter-spacing:0.04em;">★ LIVE</div>'
                )
            else:
                extra = "border:2px solid rgba(0,0,0,0.08);"
                badge = ""

            cells.append(
                f'<div style="background:{bg};border-radius:12px;padding:10px 4px;'
                f'text-align:center;display:flex;flex-direction:column;'
                f'align-items:center;justify-content:center;min-height:88px;'
                f'box-shadow:0 2px 5px rgba(0,0,0,0.12);{extra}">'
                f'{badge}'
                f'<div style="font-size:1.75em;line-height:1;">🖥️</div>'
                f'<div style="font-size:1.05em;font-weight:700;color:#111827;margin-top:5px;">{label}</div>'
                f'<div style="font-size:0.62em;color:#374151;margin-top:2px;opacity:0.75;">r{r} c{c}</div>'
                f'</div>'
            )

    grid = "\n".join(cells)
    return (
        '<div style="display:grid;grid-template-columns:repeat(5,1fr);'
        'gap:8px;max-width:580px;margin:0 auto;padding:8px 0;">'
        f'\n{grid}\n</div>'
    )


def render_heatmap(scores: np.ndarray) -> go.Figure:
    text = [
        [f"★ {int(round(scores[r, c]))}" if (r, c) == REAL_CELL
         else f"{int(round(scores[r, c]))}"
         for c in range(GRID_COLS)]
        for r in range(GRID_ROWS)
    ]

    fig = go.Figure(data=go.Heatmap(
        z=scores,
        zmin=0, zmax=100,
        colorscale="RdYlGn",
        text=text,
        texttemplate="%{text}",
        textfont=dict(size=16, color="#111827"),
        hovertemplate="row %{y}, col %{x}<br>score %{z:.0f}<extra></extra>",
        colorbar=dict(title="Score", thickness=14, len=0.8),
        xgap=3, ygap=3,
    ))

    fig.update_layout(
        height=520,
        margin=dict(l=20, r=20, t=10, b=20),
        xaxis=dict(
            title="Column",
            tickmode="array", tickvals=list(range(GRID_COLS)),
            scaleanchor="y", scaleratio=1,
            showgrid=False, zeroline=False,
        ),
        yaxis=dict(
            title="Row",
            tickmode="array", tickvals=list(range(GRID_ROWS)),
            autorange="reversed",
            showgrid=False, zeroline=False,
        ),
        paper_bgcolor="white", plot_bgcolor="white",
    )
    return fig


def quietest_cell(scores: np.ndarray) -> tuple[int, int, float]:
    idx = int(np.argmax(scores))
    r, c = divmod(idx, GRID_COLS)
    return r, c, float(scores[r, c])
