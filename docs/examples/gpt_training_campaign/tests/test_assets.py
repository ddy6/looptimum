from __future__ import annotations

import csv
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]
SITE_PROOF = REPO_ROOT / "site" / "public" / "proof"
SITE_BRAND = REPO_ROOT / "site" / "public" / "brand"
SITE_PAGE = REPO_ROOT / "site" / "src" / "pages" / "evidence" / "gpt-training.astro"


class PublicCampaignAssetTests(unittest.TestCase):
    maxDiff = None

    def test_tracked_public_package_excludes_cache_artifacts(self) -> None:
        tracked = subprocess.run(
            [
                "git",
                "ls-files",
                "-z",
                "--",
                "docs/examples/gpt_training_campaign",
            ],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
        ).stdout.split(b"\0")
        tracked = [entry for entry in tracked if entry]
        self.assertTrue(tracked)
        for relative_bytes in tracked:
            relative = Path(relative_bytes.decode("utf-8"))
            self.assertNotIn("__pycache__", relative.parts)
            self.assertNotEqual(relative.suffix, ".pyc")
        for path in PACKAGE_ROOT.rglob("*"):
            self.assertNotIn("__pycache__", path.parts)
            self.assertNotEqual(path.suffix, ".pyc")

    def test_site_proof_assets_are_intrinsically_accessible(self) -> None:
        for path in SITE_PROOF.glob("*.svg"):
            text = path.read_text(encoding="utf-8")
            self.assertIn('role="img"', text)
            self.assertIn("<title", text)
            self.assertIn("<desc", text)
            self.assertIn('viewBox="', text)

    def test_site_brand_pngs_contain_only_approved_chunks(self) -> None:
        allowed_chunks = {b"IHDR", b"sRGB", b"eXIf", b"IDAT", b"IEND"}
        for path in SITE_BRAND.glob("*.png"):
            payload = path.read_bytes()
            self.assertEqual(payload[:8], b"\x89PNG\r\n\x1a\n")
            offset = 8
            chunks: list[bytes] = []
            while offset < len(payload):
                length = struct.unpack(">I", payload[offset : offset + 4])[0]
                chunk_type = payload[offset + 4 : offset + 8]
                chunks.append(chunk_type)
                offset += length + 12
                if chunk_type == b"IEND":
                    break
            self.assertTrue(chunks)
            self.assertEqual(chunks[-1], b"IEND")
            self.assertTrue(set(chunks) <= allowed_chunks)

    def test_summary_has_exact_schema_and_values(self) -> None:
        summary = json.loads((PACKAGE_ROOT / "campaign_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(
            set(summary),
            {"campaign", "limitations", "schema_version", "selected_result"},
        )
        self.assertEqual(
            set(summary["campaign"]),
            {
                "evaluations",
                "guided_evaluations",
                "initialization_evaluations",
                "successful_evaluations",
                "tunable_control_count",
            },
        )
        self.assertEqual(
            set(summary["selected_result"]),
            {
                "baseline_loss_index",
                "baseline_parameter_index",
                "held_out_loss_improvement_percent",
                "parameter_reduction_percent_approx",
                "selected_loss_index",
                "selected_parameter_index",
            },
        )
        self.assertEqual(summary["schema_version"], "anonymized-gpt-campaign-v1")
        self.assertEqual(
            summary["campaign"],
            {
                "evaluations": 10,
                "guided_evaluations": 6,
                "initialization_evaluations": 4,
                "successful_evaluations": 10,
                "tunable_control_count": 4,
            },
        )
        self.assertEqual(
            summary["selected_result"],
            {
                "baseline_loss_index": 100.0,
                "baseline_parameter_index": 100.0,
                "held_out_loss_improvement_percent": 1.02,
                "parameter_reduction_percent_approx": 25,
                "selected_loss_index": 98.98,
                "selected_parameter_index": 75.4,
            },
        )
        self.assertEqual(
            summary["limitations"],
            ["single_seed", "small_budget", "observed_result_not_global_optimum"],
        )

    def test_progression_has_exact_schema_arithmetic_and_rounding(self) -> None:
        with (PACKAGE_ROOT / "campaign_progression.csv").open(
            newline="", encoding="utf-8"
        ) as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
        self.assertEqual(
            reader.fieldnames,
            ["evaluation", "phase", "loss_index", "best_so_far_loss_index"],
        )
        self.assertEqual(len(rows), 10)
        self.assertEqual([int(row["evaluation"]) for row in rows], list(range(1, 11)))
        self.assertEqual([row["phase"] for row in rows[:4]], ["initialization"] * 4)
        self.assertEqual([row["phase"] for row in rows[4:]], ["guided"] * 6)
        for row in rows:
            self.assertRegex(row["loss_index"], r"^\d+\.\d{2}$")
            self.assertRegex(row["best_so_far_loss_index"], r"^\d+\.\d{2}$")
            self.assertTrue(Decimal(row["loss_index"]).is_finite())
            self.assertTrue(Decimal(row["best_so_far_loss_index"]).is_finite())
        best = [Decimal(row["best_so_far_loss_index"]) for row in rows]
        self.assertTrue(all(current <= previous for previous, current in zip(best, best[1:])))
        self.assertEqual(best[-1], Decimal("98.98"))
        guided_losses = [Decimal(row["loss_index"]) for row in rows[4:]]
        all_losses = [Decimal(row["loss_index"]) for row in rows]
        self.assertEqual(sorted(guided_losses)[:2], sorted(all_losses)[:2])

    def test_comparison_has_exact_schema_and_values(self) -> None:
        with (PACKAGE_ROOT / "baseline_vs_selected.csv").open(
            newline="", encoding="utf-8"
        ) as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
        self.assertEqual(reader.fieldnames, ["candidate", "loss_index", "parameter_index"])
        self.assertEqual(
            rows,
            [
                {"candidate": "baseline", "loss_index": "100.00", "parameter_index": "100.0"},
                {"candidate": "selected", "loss_index": "98.98", "parameter_index": "75.4"},
            ],
        )

    def test_figure_regeneration_is_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            subprocess.run(
                [
                    sys.executable,
                    str(PACKAGE_ROOT / "generate_assets.py"),
                    "--output-dir",
                    temp_dir,
                    "--skip-site-mirror",
                ],
                check=True,
            )
            for name in ("campaign_objective_progression.svg", "baseline_vs_selected.svg"):
                self.assertEqual(
                    (Path(temp_dir) / name).read_bytes(),
                    (PACKAGE_ROOT / name).read_bytes(),
                )

    def test_site_assets_are_exact_mirrors(self) -> None:
        pairs = [
            (
                PACKAGE_ROOT / "campaign_objective_progression.svg",
                SITE_PROOF / "gpt_campaign_objective_progression.svg",
            ),
            (
                PACKAGE_ROOT / "baseline_vs_selected.svg",
                SITE_PROOF / "gpt_baseline_vs_selected.svg",
            ),
        ]
        for source, mirror in pairs:
            self.assertEqual(source.read_bytes(), mirror.read_bytes())

    def test_figures_are_accessible_and_metadata_free(self) -> None:
        for path in (
            PACKAGE_ROOT / "campaign_objective_progression.svg",
            PACKAGE_ROOT / "baseline_vs_selected.svg",
        ):
            text = path.read_text(encoding="utf-8")
            self.assertIn('role="img"', text)
            self.assertIn("<title id=", text)
            self.assertIn("<desc id=", text)
            self.assertIn('viewBox="0 0 ', text)
            self.assertNotIn("<!--", text)
            self.assertNotRegex(text, r"/(?:Users|srv|opt)/")
            self.assertNotRegex(text, r"\b[0-9a-f]{40}\b|\b[0-9a-f]{64}\b")
            self.assertNotRegex(text, r"\b\d{4}-\d{2}-\d{2}(?:T|\b)")

    def test_limitations_are_adjacent_to_public_results(self) -> None:
        readme = (PACKAGE_ROOT / "README.md").read_text(encoding="utf-8").lower()
        page = SITE_PAGE.read_text(encoding="utf-8").lower()
        for text in (readme, page):
            self.assertIn("single-seed", text)
            self.assertIn("small-budget", text)
            self.assertIn("global optimality", text)
            self.assertIn("statistical significance", text)


if __name__ == "__main__":
    unittest.main()
