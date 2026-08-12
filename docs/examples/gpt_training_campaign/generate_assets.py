#!/usr/bin/env python3
"""Generate deterministic SVGs from the normalized public campaign files."""

from __future__ import annotations

import argparse
import csv
import json
from decimal import Decimal
from pathlib import Path
from typing import Iterable

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parents[2]
DEFAULT_SITE_PROOF = REPO_ROOT / "site" / "public" / "proof"

PROGRESSION_FIELDS = [
    "evaluation",
    "phase",
    "loss_index",
    "best_so_far_loss_index",
]
COMPARISON_FIELDS = ["candidate", "loss_index", "parameter_index"]
SUMMARY_FIELDS = {"campaign", "limitations", "schema_version", "selected_result"}
CAMPAIGN_FIELDS = {
    "evaluations",
    "guided_evaluations",
    "initialization_evaluations",
    "successful_evaluations",
    "tunable_control_count",
}
RESULT_FIELDS = {
    "baseline_loss_index",
    "baseline_parameter_index",
    "held_out_loss_improvement_percent",
    "parameter_reduction_percent_approx",
    "selected_loss_index",
    "selected_parameter_index",
}


def _load_csv(path: Path, fields: list[str]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != fields:
            raise ValueError(f"unexpected columns in {path.name}")
        return list(reader)


def _load_inputs() -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, object]]:
    progression = _load_csv(PACKAGE_ROOT / "campaign_progression.csv", PROGRESSION_FIELDS)
    comparison = _load_csv(PACKAGE_ROOT / "baseline_vs_selected.csv", COMPARISON_FIELDS)
    summary = json.loads((PACKAGE_ROOT / "campaign_summary.json").read_text(encoding="utf-8"))

    if set(summary) != SUMMARY_FIELDS:
        raise ValueError("unexpected campaign summary keys")
    campaign = summary.get("campaign")
    selected = summary.get("selected_result")
    if not isinstance(campaign, dict) or set(campaign) != CAMPAIGN_FIELDS:
        raise ValueError("unexpected campaign keys")
    if not isinstance(selected, dict) or set(selected) != RESULT_FIELDS:
        raise ValueError("unexpected selected result keys")
    if len(progression) != 10 or len(comparison) != 2:
        raise ValueError("unexpected normalized row count")

    return progression, comparison, summary


def _svg_document(width: int, height: int, title: str, description: str) -> list[str]:
    return [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" '
            'aria-labelledby="chart-title chart-description">'
        ),
        f'<title id="chart-title">{title}</title>',
        f'<desc id="chart-description">{description}</desc>',
        "<style>",
        "text { font-family: Avenir Next, Segoe UI, Helvetica, Arial, sans-serif; fill: #18251f; }",
        ".title { font-size: 24px; font-weight: 700; }",
        ".subtitle { font-size: 14px; fill: #45544d; }",
        ".axis-label { font-size: 13px; font-weight: 600; }",
        ".tick { font-size: 12px; fill: #45544d; }",
        ".legend { font-size: 12px; }",
        ".value { font-size: 13px; font-weight: 700; }",
        ".grid { stroke: #d8e1ea; stroke-width: 1; }",
        ".axis { stroke: #45544d; stroke-width: 1.4; }",
        "</style>",
        f'<rect width="{width}" height="{height}" rx="18" fill="#ffffff"/>',
    ]


def _write_svg(path: Path, lines: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _fmt(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _progression_svg(rows: list[dict[str, str]]) -> str:
    width, height = 960, 600
    left, right, top, bottom = 92, 34, 106, 112
    plot_width = width - left - right
    plot_height = height - top - bottom
    y_min, y_max = 96.0, 110.0

    def x_position(evaluation: int) -> float:
        return left + (evaluation - 1) * plot_width / 9

    def y_position(value: Decimal) -> float:
        return top + (y_max - float(value)) * plot_height / (y_max - y_min)

    parsed = [
        (
            int(row["evaluation"]),
            row["phase"],
            Decimal(row["loss_index"]),
            Decimal(row["best_so_far_loss_index"]),
        )
        for row in rows
    ]
    lines = _svg_document(
        width,
        height,
        "Normalized held-out loss across the campaign",
        (
            "Ten single-seed evaluations: four initialization evaluations followed by six "
            "guided evaluations. Best observed loss index is 98.98; lower is better."
        ),
    )
    lines.extend(
        [
            '<text class="title" x="40" y="42">Normalized campaign objective progression</text>',
            '<text class="subtitle" x="40" y="67">Ten single-seed evaluations; observed result from a small budget</text>',
            (
                f'<rect x="{left}" y="{top}" width="{x_position(4.5) - left:.1f}" '
                f'height="{plot_height}" fill="#eff6ff"/>'
            ),
            (
                f'<rect x="{x_position(4.5):.1f}" y="{top}" '
                f'width="{width - right - x_position(4.5):.1f}" height="{plot_height}" '
                'fill="#fff5eb"/>'
            ),
            f'<text class="tick" x="{left + 10}" y="{top + 20}">initialization</text>',
            f'<text class="tick" x="{x_position(4.5) + 10:.1f}" y="{top + 20}">guided</text>',
        ]
    )

    for tick in range(96, 111, 2):
        y = y_position(Decimal(tick))
        lines.append(
            f'<line class="grid" x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}"/>'
        )
        lines.append(f'<text class="tick" x="{left - 42}" y="{y + 4:.1f}">{tick}</text>')

    baseline_y = y_position(Decimal("100.00"))
    lines.append(
        f'<line x1="{left}" y1="{baseline_y:.1f}" x2="{width - right}" y2="{baseline_y:.1f}" '
        'stroke="#5b6470" stroke-width="1.8" stroke-dasharray="7 6"/>'
    )
    lines.append(
        f'<text class="tick" x="{width - right - 118}" y="{baseline_y - 8:.1f}">baseline 100.00</text>'
    )

    best_points = " ".join(
        f"{x_position(evaluation):.1f},{y_position(best):.1f}" for evaluation, _, _, best in parsed
    )
    lines.append(
        f'<polyline points="{best_points}" fill="none" stroke="#117733" stroke-width="3"/>'
    )

    for evaluation, phase, loss, _ in parsed:
        x = x_position(evaluation)
        y = y_position(loss)
        if phase == "initialization":
            lines.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="#0072b2" stroke="#ffffff" stroke-width="2"/>'
            )
        elif phase == "guided":
            lines.append(
                f'<rect x="{x - 6:.1f}" y="{y - 6:.1f}" width="12" height="12" '
                'fill="#d55e00" stroke="#ffffff" stroke-width="2"/>'
            )
        else:
            raise ValueError("unexpected public phase")
        lines.append(
            f'<text class="tick" x="{x - 4:.1f}" y="{top + plot_height + 24}">{evaluation}</text>'
        )

    selected_x = x_position(6)
    selected_y = y_position(Decimal("98.98"))
    lines.extend(
        [
            (
                f'<line x1="{selected_x:.1f}" y1="{selected_y:.1f}" '
                f'x2="{selected_x + 48:.1f}" y2="{selected_y - 40:.1f}" '
                'stroke="#18251f" stroke-width="1.2"/>'
            ),
            (
                f'<text class="value" x="{selected_x + 52:.1f}" '
                f'y="{selected_y - 43:.1f}">best observed 98.98</text>'
            ),
            f'<line class="axis" x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}"/>',
            (
                f'<line class="axis" x1="{left}" y1="{top + plot_height}" '
                f'x2="{width - right}" y2="{top + plot_height}"/>'
            ),
            (
                f'<text class="axis-label" x="{width / 2 - 34:.1f}" '
                f'y="{height - 64}">Evaluation</text>'
            ),
            (
                '<text class="axis-label" x="20" y="390" '
                'transform="rotate(-90 20 390)">Held-out loss index (lower is better)</text>'
            ),
            '<circle cx="118" cy="552" r="6" fill="#0072b2"/>',
            '<text class="legend" x="131" y="556">initialization evaluation</text>',
            '<rect x="325" y="546" width="12" height="12" fill="#d55e00"/>',
            '<text class="legend" x="344" y="556">guided evaluation</text>',
            '<line x1="510" y1="552" x2="542" y2="552" stroke="#117733" stroke-width="3"/>',
            '<text class="legend" x="550" y="556">best so far</text>',
            '<text class="tick" x="745" y="556">baseline = 100</text>',
            "</svg>",
        ]
    )
    return "\n".join(lines) + "\n"


def _comparison_svg(rows: list[dict[str, str]]) -> str:
    indexed = {row["candidate"]: row for row in rows}
    if set(indexed) != {"baseline", "selected"}:
        raise ValueError("unexpected public candidates")

    width, height = 960, 580
    chart_top, chart_bottom = 116, 456
    chart_height = chart_bottom - chart_top

    def bar_top(value: Decimal) -> float:
        return chart_bottom - float(value) * chart_height / 110.0

    panels = [
        ("Held-out loss index", "loss_index", 145),
        ("Normalized parameter index", "parameter_index", 565),
    ]
    colors = {"baseline": "#65717e", "selected": "#0072b2"}
    labels = {"baseline": "Fixed baseline", "selected": "Selected candidate"}
    lines = _svg_document(
        width,
        height,
        "Baseline and selected candidate indexed comparison",
        (
            "Both charts begin at zero. Held-out loss index is 100.00 for the fixed baseline "
            "and 98.98 for the selected candidate. Parameter index is 100.0 and 75.4."
        ),
    )
    lines.extend(
        [
            '<text class="title" x="40" y="42">Baseline versus selected candidate</text>',
            '<text class="subtitle" x="40" y="67">Separate indexed comparisons; both axes start at zero</text>',
        ]
    )

    for title, field, panel_left in panels:
        panel_right = panel_left + 330
        lines.append(f'<text class="axis-label" x="{panel_left}" y="96">{title}</text>')
        for tick in (0, 25, 50, 75, 100):
            y = chart_bottom - tick * chart_height / 110.0
            lines.append(
                f'<line class="grid" x1="{panel_left}" y1="{y:.1f}" x2="{panel_right}" y2="{y:.1f}"/>'
            )
            lines.append(f'<text class="tick" x="{panel_left - 34}" y="{y + 4:.1f}">{tick}</text>')
        lines.append(
            f'<line class="axis" x1="{panel_left}" y1="{chart_top}" x2="{panel_left}" y2="{chart_bottom}"/>'
        )
        lines.append(
            f'<line class="axis" x1="{panel_left}" y1="{chart_bottom}" x2="{panel_right}" y2="{chart_bottom}"/>'
        )

        for offset, candidate in ((55, "baseline"), (190, "selected")):
            value = Decimal(indexed[candidate][field])
            x = panel_left + offset
            y = bar_top(value)
            lines.append(
                f'<rect x="{x}" y="{y:.1f}" width="86" height="{chart_bottom - y:.1f}" '
                f'fill="{colors[candidate]}" rx="4"/>'
            )
            decimals = 2 if field == "loss_index" else 1
            lines.append(
                f'<text class="value" x="{x + 18}" y="{y - 9:.1f}">{float(value):.{decimals}f}</text>'
            )
            lines.append(
                f'<text class="tick" x="{x - 8}" y="{chart_bottom + 24}">{labels[candidate]}</text>'
            )

    lines.extend(
        [
            '<text class="subtitle" x="145" y="528">Loss index: 1.02% lower</text>',
            '<text class="subtitle" x="565" y="528">Parameter index: about 25% lower</text>',
            '<text class="tick" x="145" y="554">Observed single-seed result from a small campaign; selected does not mean globally optimal.</text>',
            "</svg>",
        ]
    )
    return "\n".join(lines) + "\n"


def generate(output_dir: Path, site_proof_dir: Path | None) -> None:
    progression, comparison, _ = _load_inputs()
    assets = {
        "campaign_objective_progression.svg": _progression_svg(progression),
        "baseline_vs_selected.svg": _comparison_svg(comparison),
    }
    for filename, content in assets.items():
        output_path = output_dir / filename
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
        if site_proof_dir is not None:
            mirrored_name = (
                "gpt_campaign_objective_progression.svg"
                if filename == "campaign_objective_progression.svg"
                else "gpt_baseline_vs_selected.svg"
            )
            mirror_path = site_proof_dir / mirrored_name
            mirror_path.parent.mkdir(parents=True, exist_ok=True)
            mirror_path.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=PACKAGE_ROOT)
    parser.add_argument("--site-proof-dir", type=Path, default=DEFAULT_SITE_PROOF)
    parser.add_argument("--skip-site-mirror", action="store_true")
    args = parser.parse_args()
    generate(args.output_dir, None if args.skip_site_mirror else args.site_proof_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
