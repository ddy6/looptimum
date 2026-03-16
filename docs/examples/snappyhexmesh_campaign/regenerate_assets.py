#!/usr/bin/env python3
"""Regenerate SVG plots for the sanitized snappyHexMesh case study."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent
PLOTS_DIR = ROOT / "validation" / "plots"


def _load_observations() -> list[dict[str, str]]:
    path = ROOT / "campaign" / "observations.csv"
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _load_summary() -> dict[str, object]:
    path = ROOT / "validation" / "solver_pass_summary.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _load_major_metrics() -> list[dict[str, str]]:
    path = ROOT / "validation" / "major_metric_comparison.csv"
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _svg_header(width: int, height: int) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        "<style>",
        "text { font-family: Helvetica, Arial, sans-serif; fill: #1f1f1f; }",
        ".title { font-size: 18px; font-weight: 700; }",
        ".label { font-size: 12px; }",
        ".small { font-size: 11px; fill: #555; }",
        ".axis { stroke: #333; stroke-width: 1.2; }",
        ".grid { stroke: #ddd; stroke-width: 1; }",
        "</style>",
    ]


def _write_svg(path: Path, lines: Iterable[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _fmt_int(value: float) -> str:
    return f"{int(round(value)):,}"


def _plot_objective_progression() -> None:
    rows = _load_observations()
    data = [(int(row["trial_id"]), float(row["objective_loss"])) for row in rows]
    width, height = 900, 420
    margin_left, margin_bottom, margin_top, margin_right = 70, 55, 55, 30
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom

    losses = [loss for _, loss in data]
    logs = [math.log10(loss) for loss in losses]
    min_log = min(logs)
    max_log = max(logs)

    def x_pos(trial_id: int) -> float:
        return margin_left + ((trial_id - 1) / (len(data) - 1)) * plot_w

    def y_pos(loss: float) -> float:
        scaled = (math.log10(loss) - min_log) / (max_log - min_log)
        return margin_top + plot_h - scaled * plot_h

    lines = _svg_header(width, height)
    random_end_x = x_pos(8)
    lines.append(
        f'<rect x="{margin_left}" y="{margin_top}" width="{random_end_x - margin_left}" '
        f'height="{plot_h}" fill="#f3efe2"/>'
    )
    lines.append(
        f'<rect x="{random_end_x}" y="{margin_top}" width="{plot_w - (random_end_x - margin_left)}" '
        f'height="{plot_h}" fill="#e8f0f2"/>'
    )
    for tick in [1, 2, 3, 4, 5]:
        loss_tick = 10**tick
        if min(losses) <= loss_tick <= max(losses):
            y = y_pos(loss_tick)
            lines.append(
                f'<line class="grid" x1="{margin_left}" y1="{y:.1f}" x2="{width - margin_right}" y2="{y:.1f}"/>'
            )
            lines.append(f'<text class="small" x="10" y="{y + 4:.1f}">1e{tick}</text>')
    lines.append(
        f'<line class="axis" x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{height - margin_bottom}"/>'
    )
    lines.append(
        f'<line class="axis" x1="{margin_left}" y1="{height - margin_bottom}" x2="{width - margin_right}" y2="{height - margin_bottom}"/>'
    )
    points = []
    for trial_id, loss in data:
        x = x_pos(trial_id)
        y = y_pos(loss)
        points.append(f"{x:.1f},{y:.1f}")
        fill = "#c54d3f" if trial_id in {8, 15, 16} else "#1f6f8b"
        lines.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="{fill}"/>')
    lines.append(
        f'<polyline fill="none" stroke="#1f6f8b" stroke-width="2" points="{" ".join(points)}"/>'
    )
    for trial_id in [1, 5, 8, 10, 15, 21]:
        x = x_pos(trial_id)
        lines.append(
            f'<text class="small" x="{x - 4:.1f}" y="{height - margin_bottom + 18}">{trial_id}</text>'
        )
    lines.append(
        f'<text class="title" x="{margin_left}" y="28">Campaign objective progression</text>'
    )
    lines.append(
        f'<text class="small" x="{margin_left}" y="44">Random phase: trials 1-8 | Surrogate-guided phase: trials 9-21</text>'
    )
    lines.append(f'<text class="label" x="{width / 2 - 20:.1f}" y="{height - 10}">trial_id</text>')
    lines.append(
        f'<text class="label" x="18" y="{margin_top - 12}" transform="rotate(-90 18,{margin_top - 12})">objective_loss (log10)</text>'
    )
    lines.append("</svg>")
    _write_svg(PLOTS_DIR / "campaign_objective_progression.svg", lines)


def _plot_cell_count() -> None:
    summary = _load_summary()
    fine = float(summary["reference_total_cells"])
    coarse = float(summary["selected_total_cells"])
    reduction = float(summary["cell_count_reduction_pct"])
    width, height = 700, 420
    margin_left, margin_bottom, margin_top, margin_right = 80, 55, 55, 30
    plot_h = height - margin_top - margin_bottom
    max_value = max(fine, coarse)

    def bar_height(value: float) -> float:
        return (value / max_value) * plot_h

    lines = _svg_header(width, height)
    lines.append(
        f'<line class="axis" x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{height - margin_bottom}"/>'
    )
    lines.append(
        f'<line class="axis" x1="{margin_left}" y1="{height - margin_bottom}" x2="{width - margin_right}" y2="{height - margin_bottom}"/>'
    )
    entries = [
        ("fine reference", fine, "#6b8ba4"),
        ("validated coarse", coarse, "#c54d3f"),
    ]
    bar_w = 140
    gap = 120
    start_x = margin_left + 90
    for idx, (label, value, color) in enumerate(entries):
        x = start_x + idx * (bar_w + gap)
        h = bar_height(value)
        y = height - margin_bottom - h
        lines.append(f'<rect x="{x}" y="{y:.1f}" width="{bar_w}" height="{h:.1f}" fill="{color}"/>')
        lines.append(
            f'<text class="label" x="{x + 10}" y="{height - margin_bottom + 20}">{label}</text>'
        )
        lines.append(f'<text class="small" x="{x + 20}" y="{y - 8:.1f}">{_fmt_int(value)}</text>')
    lines.append(
        f'<text class="title" x="{margin_left}" y="28">Fine vs coarse mesh cell count</text>'
    )
    lines.append(
        f'<text class="small" x="{margin_left}" y="44">Cell-count reduction: {reduction:.1f}%</text>'
    )
    lines.append("</svg>")
    _write_svg(PLOTS_DIR / "fine_vs_coarse_cell_count.svg", lines)


def _plot_solver_runtime() -> None:
    summary = _load_summary()
    fine = float(summary["reference_solver_wall_clock_seconds"])
    coarse = float(summary["selected_solver_wall_clock_seconds"])
    reduction = float(summary["solver_runtime_reduction_pct"])
    speedup = float(summary["solver_speedup_vs_reference"])
    width, height = 700, 420
    margin_left, margin_bottom, margin_top, margin_right = 80, 55, 55, 30
    plot_h = height - margin_top - margin_bottom
    max_value = max(fine, coarse)

    def bar_height(value: float) -> float:
        return (value / max_value) * plot_h

    lines = _svg_header(width, height)
    lines.append(
        f'<line class="axis" x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{height - margin_bottom}"/>'
    )
    lines.append(
        f'<line class="axis" x1="{margin_left}" y1="{height - margin_bottom}" x2="{width - margin_right}" y2="{height - margin_bottom}"/>'
    )
    entries = [
        ("fine reference", fine, "#6b8ba4"),
        ("validated coarse", coarse, "#c54d3f"),
    ]
    bar_w = 140
    gap = 120
    start_x = margin_left + 90
    for idx, (label, value, color) in enumerate(entries):
        x = start_x + idx * (bar_w + gap)
        h = bar_height(value)
        y = height - margin_bottom - h
        lines.append(f'<rect x="{x}" y="{y:.1f}" width="{bar_w}" height="{h:.1f}" fill="{color}"/>')
        lines.append(
            f'<text class="label" x="{x + 10}" y="{height - margin_bottom + 20}">{label}</text>'
        )
        lines.append(f'<text class="small" x="{x + 12}" y="{y - 8:.1f}">{_fmt_int(value)} s</text>')
    lines.append(
        f'<text class="title" x="{margin_left}" y="28">Fine vs coarse solver wall clock</text>'
    )
    lines.append(
        f'<text class="small" x="{margin_left}" y="44">Runtime reduction: {reduction:.1f}% | Speedup: {speedup:.1f}x</text>'
    )
    lines.append("</svg>")
    _write_svg(PLOTS_DIR / "fine_vs_coarse_solver_runtime.svg", lines)


def _plot_outlet_flow_drift() -> None:
    rows = [row for row in _load_major_metrics() if row["category"] == "outlet_flow"]
    width, height = 900, 420
    margin_left, margin_bottom, margin_top, margin_right = 70, 70, 55, 30
    plot_h = height - margin_top - margin_bottom
    max_value = 1.1

    lines = _svg_header(width, height)
    lines.append(
        f'<line class="axis" x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{height - margin_bottom}"/>'
    )
    lines.append(
        f'<line class="axis" x1="{margin_left}" y1="{height - margin_bottom}" x2="{width - margin_right}" y2="{height - margin_bottom}"/>'
    )
    threshold_y = margin_top + plot_h - (1.0 / max_value) * plot_h
    lines.append(
        f'<line x1="{margin_left}" y1="{threshold_y:.1f}" x2="{width - margin_right}" y2="{threshold_y:.1f}" stroke="#b66" stroke-dasharray="6 4" stroke-width="1.5"/>'
    )
    lines.append(
        f'<text class="small" x="{width - margin_right - 130}" y="{threshold_y - 6:.1f}">1.0% threshold</text>'
    )
    bar_w = 60
    gap = 26
    start_x = margin_left + 30
    for idx, row in enumerate(rows):
        value = abs(float(row["relative_drift_percent"]))
        x = start_x + idx * (bar_w + gap)
        h = (value / max_value) * plot_h
        y = height - margin_bottom - h
        lines.append(f'<rect x="{x}" y="{y:.1f}" width="{bar_w}" height="{h:.1f}" fill="#1f6f8b"/>')
        lines.append(
            f'<text class="small" x="{x + 6}" y="{height - margin_bottom + 18}">b{idx + 1:02d}</text>'
        )
        lines.append(f'<text class="small" x="{x + 4}" y="{y - 8:.1f}">{value:.3f}%</text>')
    lines.append(
        f'<text class="title" x="{margin_left}" y="28">Major outlet-flow relative drift</text>'
    )
    lines.append(
        f'<text class="small" x="{margin_left}" y="44">All anonymized branch-level outlet flows remain within the 1.0% threshold</text>'
    )
    lines.append("</svg>")
    _write_svg(PLOTS_DIR / "outlet_flow_relative_drift.svg", lines)


def _plot_aggregate_pressure_drift() -> None:
    target_ids = ["map_all_mmhg", "pp_all_mmhg", "pp_primary_branch_mmhg"]
    lookup = {row["metric_id"]: row for row in _load_major_metrics()}
    rows = [lookup[item] for item in target_ids]
    width, height = 760, 420
    margin_left, margin_bottom, margin_top, margin_right = 70, 70, 55, 30
    plot_h = height - margin_top - margin_bottom
    max_value = 0.55

    lines = _svg_header(width, height)
    lines.append(
        f'<line class="axis" x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{height - margin_bottom}"/>'
    )
    lines.append(
        f'<line class="axis" x1="{margin_left}" y1="{height - margin_bottom}" x2="{width - margin_right}" y2="{height - margin_bottom}"/>'
    )
    threshold_y = margin_top + plot_h - (0.5 / max_value) * plot_h
    lines.append(
        f'<line x1="{margin_left}" y1="{threshold_y:.1f}" x2="{width - margin_right}" y2="{threshold_y:.1f}" stroke="#b66" stroke-dasharray="6 4" stroke-width="1.5"/>'
    )
    lines.append(
        f'<text class="small" x="{width - margin_right - 155}" y="{threshold_y - 6:.1f}">0.5 mmHg threshold</text>'
    )
    labels = ["MAP all", "PP all", "PP primary"]
    bar_w = 120
    gap = 65
    start_x = margin_left + 60
    for idx, (row, label) in enumerate(zip(rows, labels)):
        value = abs(float(row["drift"]))
        x = start_x + idx * (bar_w + gap)
        h = (value / max_value) * plot_h
        y = height - margin_bottom - h
        lines.append(f'<rect x="{x}" y="{y:.1f}" width="{bar_w}" height="{h:.1f}" fill="#c54d3f"/>')
        lines.append(
            f'<text class="label" x="{x + 18}" y="{height - margin_bottom + 18}">{label}</text>'
        )
        lines.append(f'<text class="small" x="{x + 24}" y="{y - 8:.1f}">{value:.3f} mmHg</text>')
    lines.append(f'<text class="title" x="{margin_left}" y="28">Aggregate pressure drift</text>')
    lines.append(
        f'<text class="small" x="{margin_left}" y="44">All published aggregate pressure checks remain within 0.5 mmHg</text>'
    )
    lines.append("</svg>")
    _write_svg(PLOTS_DIR / "aggregate_pressure_drift.svg", lines)


def main() -> int:
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    _plot_objective_progression()
    _plot_cell_count()
    _plot_solver_runtime()
    _plot_outlet_flow_drift()
    _plot_aggregate_pressure_drift()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
