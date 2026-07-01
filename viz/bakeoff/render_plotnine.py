"""Render the plotnine entry for the LMArena ELO race bake-off."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
from plotnine import (
    aes,
    element_blank,
    element_line,
    element_rect,
    element_text,
    geom_line,
    geom_segment,
    geom_text,
    ggplot,
    labs,
    scale_color_manual,
    scale_x_datetime,
    theme,
    theme_minimal,
)

REPO = Path(__file__).resolve().parents[2]
DB = REPO / "db" / "modeldb.sqlite"
OUT = REPO / "viz" / "bakeoff" / "plotnine.png"

QUERY = """
SELECT br.model_id, m.canonical_slug, m.developer_id, br.measured_at, MAX(br.score) AS score
FROM benchmark_result br JOIN model m ON m.id=br.model_id
WHERE br.benchmark_id='lmarena_text_overall' AND br.model_id IS NOT NULL
GROUP BY br.model_id, br.measured_at ORDER BY br.measured_at
"""

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
MIN_POINTS = 8
TOP_N = 12


def short_name(slug: str) -> str:
    return slug.split("/", 1)[-1]


def load_data() -> pd.DataFrame:
    with sqlite3.connect(DB) as conn:
        df = pd.read_sql_query(QUERY, conn)

    if df.empty:
        raise RuntimeError("No LMArena ELO rows found. Run the data pipeline first.")

    df = df.rename(columns={"canonical_slug": "slug", "measured_at": "date"})
    df["date"] = pd.to_datetime(df["date"])
    df["score"] = df["score"].astype(float)
    df["developer_id"] = df["developer_id"].fillna("unknown")
    df["short_name"] = df["slug"].map(short_name)

    point_counts = df.groupby("slug")["date"].size()
    eligible = point_counts[point_counts >= MIN_POINTS].index
    df = df[df["slug"].isin(eligible)].copy()

    latest = df.sort_values("date").groupby("slug", as_index=False).tail(1)
    top_slugs = latest.nlargest(TOP_N, "score")["slug"]
    df = df[df["slug"].isin(top_slugs)].copy()

    if df.empty:
        raise RuntimeError("No LMArena ELO series matched the bake-off filters.")

    return df.sort_values(["slug", "date"])


def spread_label_y(last_df: pd.DataFrame, minimum_gap: float = 11.0) -> pd.Series:
    ordered = last_df.sort_values("score").copy()
    lower = float(last_df["score"].min()) - 38
    upper = float(last_df["score"].max()) + 28
    if len(ordered) > 1:
        minimum_gap = min(minimum_gap, (upper - lower) / (len(ordered) - 1))

    positions = ordered["score"].astype(float).tolist()
    for index in range(1, len(positions)):
        positions[index] = max(positions[index], positions[index - 1] + minimum_gap)

    if positions and positions[-1] > upper:
        positions[-1] = upper
        for index in range(len(positions) - 2, -1, -1):
            positions[index] = min(positions[index], positions[index + 1] - minimum_gap)

    if positions and positions[0] < lower:
        shift = lower - positions[0]
        positions = [position + shift for position in positions]

    return pd.Series(positions, index=ordered.index)


def build_plot(df: pd.DataFrame) -> ggplot:
    last_df = df.sort_values("date").groupby("slug", as_index=False).tail(1).copy()
    last_df["label_y"] = spread_label_y(last_df)
    last_df["label_date"] = last_df["date"] + pd.Timedelta(days=22)
    last_df["segment_end_date"] = last_df["date"] + pd.Timedelta(days=16)

    first_date = df["date"].min() - pd.Timedelta(days=20)
    last_date = df["date"].max() + pd.Timedelta(days=145)
    score_min = min(float(df["score"].min()) - 34, float(last_df["label_y"].min()) - 18)
    score_max = max(float(df["score"].max()) + 34, float(last_df["label_y"].max()) + 18)

    developers = sorted(df["developer_id"].unique())
    color_values = {developer: DEV_COLOR.get(developer, FALLBACK_COLOR) for developer in developers}

    return (
        ggplot(df, aes("date", "score", color="developer_id", group="slug"))
        + geom_line(size=1.15, alpha=0.92)
        + geom_segment(
            data=last_df,
            mapping=aes(x="date", xend="segment_end_date", y="score", yend="label_y", color="developer_id"),
            size=0.35,
            alpha=0.45,
            show_legend=False,
        )
        + geom_text(
            data=last_df,
            mapping=aes(x="label_date", y="label_y", label="short_name", color="developer_id"),
            ha="left",
            va="center",
            size=7.1,
            fontweight="semibold",
            show_legend=False,
        )
        + scale_color_manual(values=color_values)
        + scale_x_datetime(date_breaks="3 months", date_labels="%Y-%m", limits=(first_date, last_date))
        + labs(
            title="The LMArena ELO race",
            subtitle="Text Overall · best variant per model per day · Source: LMArena",
            x="",
            y="LMArena rating (Bradley-Terry)",
        )
        + theme_minimal(base_family="DejaVu Sans", base_size=12)
        + theme(
            figure_size=(16, 9),
            dpi=200,
            plot_background=element_rect(fill="#fbfaf7", color="none"),
            panel_background=element_rect(fill="#fbfaf7", color="none"),
            plot_title=element_text(size=22, weight="bold", color="#151515", margin={"b": 8}),
            plot_subtitle=element_text(size=12.5, color="#6b7280", margin={"b": 22}),
            plot_margin=0.035,
            panel_grid_minor=element_blank(),
            panel_grid_major_y=element_line(color="#e8e5de", size=0.55),
            panel_grid_major_x=element_blank(),
            axis_line=element_line(color="#d4d0c8", size=0.55),
            axis_ticks=element_blank(),
            axis_text_x=element_text(color="#60656f", size=9.5, rotation=0),
            axis_text_y=element_text(color="#60656f", size=10),
            axis_title_y=element_text(color="#414852", size=11, margin={"r": 12}),
            legend_position="none",
        )
    )


def render() -> Path:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    plot = build_plot(load_data())
    plot.save(OUT, width=16, height=9, dpi=200, verbose=False)
    return OUT


if __name__ == "__main__":
    path = render()
    print(f"{path.relative_to(REPO)} {path.stat().st_size} bytes")
