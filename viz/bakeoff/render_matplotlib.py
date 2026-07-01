"""Beautiful Matplotlib renderer for the LMArena ELO-over-time bake-off."""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

REPO = Path(__file__).resolve().parents[2]
DB = REPO / "db" / "modeldb.sqlite"
OUT = REPO / "viz" / "bakeoff" / "matplotlib.png"

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


@dataclass(frozen=True)
class Trace:
    slug: str
    developer: str
    points: tuple[tuple[date, float], ...]

    @property
    def short_name(self) -> str:
        return escape_text(self.slug.split("/", 1)[-1])

    @property
    def latest_score(self) -> float:
        return self.points[-1][1]

    @property
    def color(self) -> str:
        return DEV_COLOR.get(self.developer, FALLBACK_COLOR)


def escape_text(value: str) -> str:
    """Keep model names literal if a future slug contains a mathtext marker."""
    return value.replace("$", r"\$")


def load_traces() -> list[Trace]:
    by_model: dict[int, dict[str, object]] = defaultdict(lambda: {"points": []})
    with sqlite3.connect(DB) as conn:
        rows = conn.execute(QUERY).fetchall()

    for model_id, slug, developer, measured_at, score in rows:
        entry = by_model[model_id]
        entry["slug"] = slug
        entry["developer"] = developer or ""
        entry["points"].append((date.fromisoformat(measured_at), float(score)))

    traces = [
        Trace(
            slug=str(entry["slug"]),
            developer=str(entry["developer"]),
            points=tuple(entry["points"]),
        )
        for entry in by_model.values()
        if len(entry["points"]) >= 8
    ]
    traces.sort(key=lambda trace: trace.latest_score, reverse=True)
    return traces[:12]


def declutter_label_y(traces: list[Trace], minimum_gap: float = 9.5) -> dict[str, float]:
    """Greedily spread end labels apart while preserving their top-to-bottom order."""
    ordered = sorted(traces, key=lambda trace: trace.latest_score)
    lower = min(trace.latest_score for trace in traces) - 38
    upper = max(trace.latest_score for trace in traces) + 22
    if len(ordered) > 1:
        minimum_gap = min(minimum_gap, (upper - lower) / (len(ordered) - 1))

    y_positions = [trace.latest_score for trace in ordered]
    for index in range(1, len(y_positions)):
        y_positions[index] = max(y_positions[index], y_positions[index - 1] + minimum_gap)

    if y_positions and y_positions[-1] > upper:
        y_positions[-1] = upper
        for index in range(len(y_positions) - 2, -1, -1):
            y_positions[index] = min(y_positions[index], y_positions[index + 1] - minimum_gap)

    if y_positions and y_positions[0] < lower:
        shift = lower - y_positions[0]
        y_positions = [y + shift for y in y_positions]

    return {trace.slug: y for trace, y in zip(ordered, y_positions)}


def render() -> Path:
    traces = load_traces()
    if not traces:
        raise RuntimeError("No LMArena ELO traces found. Run the data pipeline first.")

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 12,
            "axes.titlesize": 24,
            "axes.labelsize": 12,
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "figure.facecolor": "#fafafa",
            "axes.facecolor": "#fafafa",
            "savefig.facecolor": "#fafafa",
        }
    )

    fig, ax = plt.subplots(figsize=(16, 9), dpi=200)
    fig.subplots_adjust(left=0.075, right=0.79, top=0.84, bottom=0.15)

    for trace in sorted(traces, key=lambda item: item.latest_score):
        xs = [point[0] for point in trace.points]
        ys = [point[1] for point in trace.points]
        ax.plot(
            xs,
            ys,
            color=trace.color,
            linewidth=2.25,
            alpha=0.9,
            solid_capstyle="round",
            solid_joinstyle="round",
            zorder=2,
        )
        ax.scatter(xs[-1], ys[-1], s=28, color=trace.color, edgecolor="#fafafa", linewidth=1.2, zorder=3)

    label_y = declutter_label_y(traces)
    last_date = max(trace.points[-1][0] for trace in traces)
    first_date = min(point[0] for trace in traces for point in trace.points)
    label_x = last_date + timedelta(days=18)

    for trace in sorted(traces, key=lambda item: item.latest_score, reverse=True):
        end_x, end_y = trace.points[-1]
        text_y = label_y[trace.slug]
        if abs(text_y - end_y) > 1:
            ax.plot(
                [end_x, label_x - timedelta(days=4)],
                [end_y, text_y],
                color=trace.color,
                linewidth=0.85,
                alpha=0.34,
                zorder=1,
            )
        ax.text(
            label_x,
            text_y,
            trace.short_name,
            color=trace.color,
            fontsize=10.2,
            fontweight="semibold",
            va="center",
            ha="left",
            clip_on=False,
            path_effects=[pe.withStroke(linewidth=3.2, foreground="#fafafa")],
        )

    min_score = min(point[1] for trace in traces for point in trace.points)
    max_score = max(point[1] for trace in traces for point in trace.points)
    ax.set_xlim(first_date - timedelta(days=20), last_date + timedelta(days=138))
    ax.set_ylim(min(min_score - 35, min(label_y.values()) - 18), max(max_score + 35, max(label_y.values()) + 18))

    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=8))
    ax.grid(axis="y", color="#111111", alpha=0.15, linewidth=0.8)
    ax.grid(axis="x", visible=False)
    ax.set_axisbelow(True)

    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#d9d9d9")
        ax.spines[side].set_linewidth(0.9)

    ax.tick_params(axis="both", colors="#555555", length=0, pad=8)
    ax.set_xlabel("")
    ax.set_ylabel("Bradley-Terry rating", color="#555555", labelpad=12)

    fig.text(0.075, 0.93, "The LMArena ELO race", fontsize=28, fontweight="bold", color="#111111")
    fig.text(
        0.075,
        0.89,
        "Text Overall · best variant per model per day · Source: LMArena",
        fontsize=13.5,
        color="#6f6f6f",
    )
    fig.text(0.075, 0.055, "Latest top 12 models with at least eight observed dates", fontsize=9.5, color="#8a8a8a")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=200)
    plt.close(fig)
    return OUT


def main() -> int:
    output = render()
    print(f"{output} {output.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
