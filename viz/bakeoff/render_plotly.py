"""Render the Plotly entry for the LMArena ELO race bake-off."""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import plotly.graph_objects as go

REPO = Path(__file__).resolve().parents[2]
DB = REPO / "db" / "modeldb.sqlite"
OUT = REPO / "viz" / "bakeoff"
PNG = OUT / "plotly.png"

BENCHMARK_ID = "lmarena_text_overall"
MIN_POINTS = 8
TOP_N = 12

DEV_COLOR = {
    "anthropic": "#d97757",
    "openai": "#10a37f",
    "google": "#4285f4",
    "xai": "#111111",
    "deepseek": "#4d6bfe",
    "zhipuai": "#c026d3",
    "moonshotai": "#16a34a",
    "alibaba": "#6b3fa0",
    "meta": "#0668e1",
}
FALLBACK_COLOR = "#888888"


def load_series() -> list[dict[str, object]]:
    rows = sqlite3.connect(DB).execute(
        """
        SELECT br.model_id, m.canonical_slug, m.developer_id, br.measured_at,
               MAX(br.score) AS score
        FROM benchmark_result br
        JOIN model m ON m.id = br.model_id
        WHERE br.benchmark_id = ? AND br.model_id IS NOT NULL
        GROUP BY br.model_id, br.measured_at
        ORDER BY br.measured_at
        """,
        (BENCHMARK_ID,),
    ).fetchall()

    grouped: dict[int, dict[str, object]] = defaultdict(lambda: {"points": []})
    for model_id, slug, developer, measured_at, score in rows:
        series = grouped[int(model_id)]
        series["slug"] = slug
        series["developer"] = developer or ""
        series["points"].append((date.fromisoformat(measured_at), float(score)))

    models = [series for series in grouped.values() if len(series["points"]) >= MIN_POINTS]
    models.sort(key=lambda series: series["points"][-1][1], reverse=True)
    return models[:TOP_N]


def short_name(slug: str) -> str:
    return slug.split("/", 1)[-1]


def label_offsets(models: list[dict[str, object]]) -> dict[str, int]:
    """Small pixel nudges keep dense end labels readable without moving anchors."""
    ordered = sorted(models, key=lambda series: series["points"][-1][1])
    offsets: dict[str, int] = {}
    last_y: float | None = None
    run = 0
    for series in ordered:
        y = series["points"][-1][1]
        slug = str(series["slug"])
        if last_y is not None and abs(y - last_y) < 12:
            run += 1
        else:
            run = 0
        offsets[slug] = ((run + 1) // 2) * (1 if run % 2 else -1) * 9
        last_y = y
    return offsets


def build_figure(models: list[dict[str, object]]) -> go.Figure:
    if not models:
        raise RuntimeError("No LMArena ELO series matched the bake-off filters.")

    fig = go.Figure()
    annotations = []
    offsets = label_offsets(models)

    all_dates: list[date] = []
    all_scores: list[float] = []
    for series in models:
        points = series["points"]
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        slug = str(series["slug"])
        developer = str(series["developer"])
        color = DEV_COLOR.get(developer, FALLBACK_COLOR)
        all_dates.extend(xs)
        all_scores.extend(ys)

        fig.add_trace(
            go.Scatter(
                x=xs,
                y=ys,
                mode="lines",
                name=short_name(slug),
                line={"color": color, "width": 2.5},
                opacity=0.9,
                hovertemplate=(
                    f"<b>{short_name(slug)}</b><br>"
                    f"Developer: {developer or 'unknown'}<br>"
                    "%{x|%Y-%m-%d}<br>Rating: %{y:.1f}<extra></extra>"
                ),
            )
        )
        annotations.append(
            {
                "x": xs[-1],
                "y": ys[-1],
                "text": short_name(slug),
                "showarrow": False,
                "xanchor": "left",
                "yanchor": "middle",
                "xshift": 10,
                "yshift": offsets[slug],
                "font": {"size": 16, "color": color, "family": "Inter, Helvetica, Arial, sans-serif"},
                "bgcolor": "rgba(250, 250, 247, 0.78)",
                "borderpad": 2,
            }
        )

    y_min = min(all_scores) - 18
    y_max = max(all_scores) + 24
    x_min = min(all_dates) - timedelta(days=8)
    x_max = max(all_dates) + timedelta(days=115)

    fig.update_layout(
        template="simple_white",
        width=1600,
        height=900,
        showlegend=False,
        paper_bgcolor="#fbfaf7",
        plot_bgcolor="#fbfaf7",
        font={"family": "Inter, Helvetica, Arial, sans-serif", "color": "#2b2f33", "size": 15},
        margin={"l": 96, "r": 230, "t": 118, "b": 82},
        title={
            "text": (
                "<b>The LMArena ELO race</b>"
                "<br><sub>Text Overall · best variant per model per day · Source: LMArena</sub>"
            ),
            "x": 0.055,
            "xanchor": "left",
            "y": 0.965,
            "yanchor": "top",
            "font": {"size": 34, "color": "#171717", "family": "Inter, Helvetica, Arial, sans-serif"},
        },
        annotations=annotations,
    )
    fig.update_xaxes(
        range=[x_min, x_max],
        tickformat="%Y-%m",
        showgrid=False,
        showline=False,
        zeroline=False,
        ticks="outside",
        tickcolor="rgba(31, 41, 55, 0.24)",
        tickfont={"size": 14, "color": "#60656f"},
        title=None,
    )
    fig.update_yaxes(
        range=[y_min, y_max],
        title={"text": "LMArena rating (Bradley-Terry)", "font": {"size": 17, "color": "#414852"}},
        showgrid=True,
        gridcolor="rgba(107, 114, 128, 0.16)",
        gridwidth=1,
        showline=False,
        zeroline=False,
        ticks="outside",
        tickcolor="rgba(31, 41, 55, 0.24)",
        tickfont={"size": 14, "color": "#60656f"},
    )
    return fig


def render() -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    fig = build_figure(load_series())
    fig.write_image(PNG, width=1600, height=900, scale=2)
    return PNG


if __name__ == "__main__":
    path = render()
    print(f"{path.relative_to(REPO)} {path.stat().st_size} bytes")
