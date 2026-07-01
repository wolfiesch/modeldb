"""Render the Altair entry for the LMArena ELO race bake-off."""
from __future__ import annotations

import os
import sqlite3
from datetime import timedelta
from pathlib import Path

import altair as alt
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
DB = REPO / "db" / "modeldb.sqlite"
PNG = REPO / "viz" / "bakeoff" / "altair.png"

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
DOMAIN = list(DEV_COLOR) + ["other"]
RANGE = list(DEV_COLOR.values()) + [FALLBACK_COLOR]


def load_data() -> pd.DataFrame:
    with sqlite3.connect(DB) as conn:
        raw = pd.read_sql_query(QUERY, conn)

    if raw.empty:
        raise RuntimeError("No LMArena ELO rows found. Run the data pipeline first.")

    raw = raw.rename(columns={"canonical_slug": "slug", "measured_at": "date"})
    raw["date"] = pd.to_datetime(raw["date"])
    raw["score"] = raw["score"].astype(float)
    raw["developer_id"] = raw["developer_id"].fillna("other")
    raw.loc[~raw["developer_id"].isin(DEV_COLOR), "developer_id"] = "other"
    raw["short_name"] = raw["slug"].str.split("/", n=1).str[-1]

    point_counts = raw.groupby("model_id").size()
    eligible_ids = point_counts[point_counts >= 8].index
    eligible = raw[raw["model_id"].isin(eligible_ids)].copy()

    latest = eligible.sort_values(["model_id", "date"]).groupby("model_id", as_index=False).tail(1)
    top_ids = latest.nlargest(12, "score")["model_id"]
    df = eligible[eligible["model_id"].isin(top_ids)].copy()
    df["model_order"] = df["model_id"].map({model_id: order for order, model_id in enumerate(top_ids)})
    return df.sort_values(["model_order", "date"]).reset_index(drop=True)


def label_positions(df: pd.DataFrame) -> pd.DataFrame:
    labels = df.sort_values(["model_id", "date"]).groupby("model_id", as_index=False).tail(1).copy()
    labels = labels.sort_values("score").reset_index(drop=True)

    lower = float(df["score"].min()) - 34.0
    upper = float(df["score"].max()) + 30.0
    gap = min(10.5, (upper - lower) / max(len(labels) - 1, 1))
    positions = labels["score"].astype(float).tolist()

    for index in range(1, len(positions)):
        positions[index] = max(positions[index], positions[index - 1] + gap)

    if positions and positions[-1] > upper:
        positions[-1] = upper
        for index in range(len(positions) - 2, -1, -1):
            positions[index] = min(positions[index], positions[index + 1] - gap)

    if positions and positions[0] < lower:
        shift = lower - positions[0]
        positions = [position + shift for position in positions]

    max_date = df["date"].max()
    labels["label_score"] = positions
    labels["label_date"] = max_date + timedelta(days=18)
    return labels.sort_values("model_order").reset_index(drop=True)


def build_chart(df: pd.DataFrame) -> alt.Chart:
    if df.empty:
        raise RuntimeError("No LMArena ELO series matched the bake-off filters.")

    labels = label_positions(df)
    max_date = df["date"].max()
    x_domain = [df["date"].min() - timedelta(days=18), max_date + timedelta(days=118)]
    y_domain = [min(float(df["score"].min()) - 34, float(labels["label_score"].min()) - 18), max(float(df["score"].max()) + 34, float(labels["label_score"].max()) + 18)]

    color = alt.Color(
        "developer_id:N",
        scale=alt.Scale(domain=DOMAIN, range=RANGE),
        legend=None,
    )

    base = alt.Chart(df).encode(
        x=alt.X(
            "date:T",
            scale=alt.Scale(domain=x_domain, nice=False),
            axis=alt.Axis(format="%Y-%m", title=None, tickCount="month", labelAngle=0, labelPadding=9),
        ),
        y=alt.Y(
            "score:Q",
            scale=alt.Scale(zero=False, domain=y_domain, nice=False),
            axis=alt.Axis(title="Bradley-Terry rating", titlePadding=16, labelPadding=8, tickCount=8),
        ),
        color=color,
        detail="slug:N",
        order="date:T",
    )

    lines = base.mark_line(strokeWidth=2.8, opacity=0.88, interpolate="monotone")

    endpoints = (
        alt.Chart(labels)
        .mark_circle(size=72, stroke="#fbfaf7", strokeWidth=1.7)
        .encode(
            x="date:T",
            y="score:Q",
            color=color,
        )
    )

    connectors = (
        alt.Chart(labels)
        .mark_rule(opacity=0.34, strokeWidth=1.0)
        .encode(
            x="date:T",
            y="score:Q",
            x2="label_date:T",
            y2="label_score:Q",
            color=color,
        )
    )

    text = (
        alt.Chart(labels)
        .mark_text(align="left", baseline="middle", dx=6, font="Helvetica", fontSize=14, fontWeight=600)
        .encode(
            x="label_date:T",
            y="label_score:Q",
            text="short_name:N",
            color=color,
        )
    )

    title = alt.TitleParams(
        text="The LMArena ELO race",
        subtitle="Text Overall · best variant per model per day · Source: LMArena",
        anchor="start",
        font="Helvetica",
        fontSize=34,
        fontWeight="bold",
        color="#111111",
        subtitleFont="Helvetica",
        subtitleFontSize=16,
        subtitleColor="#666666",
        offset=22,
    )

    return (
        (lines + connectors + endpoints + text)
        .properties(width=1400, height=760, title=title, background="#fbfaf7")
        .configure_view(strokeWidth=0)
        .configure_axis(
            grid=True,
            gridColor="#eeeeee",
            gridOpacity=0.95,
            domainColor="#cccccc",
            tickColor="#d9d9d9",
            labelColor="#5f6368",
            titleColor="#555555",
            labelFont="Helvetica",
            titleFont="Helvetica",
            labelFontSize=13,
            titleFontSize=15,
        )
        .configure_axisX(grid=False)
        .configure(background="#fbfaf7", padding={"left": 86, "right": 210, "top": 72, "bottom": 68})
    )


def render() -> Path:
    PNG.parent.mkdir(parents=True, exist_ok=True)
    chart = build_chart(load_data())
    try:
        chart.save(PNG, scale_factor=2)
    except TypeError:
        chart.save(PNG)
    return PNG


if __name__ == "__main__":
    output = render()
    print(f"{output.relative_to(REPO)} {os.path.getsize(output)} bytes")
