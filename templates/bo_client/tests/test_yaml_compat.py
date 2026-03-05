from __future__ import annotations

from conftest import run_cmd


def _rename_objective_schema_to_yaml(template_copy) -> None:
    src = template_copy / "objective_schema.json"
    dst = template_copy / "objective_schema.yaml"
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    src.unlink()


def test_yaml_contract_requires_compat_mode(template_copy) -> None:
    _rename_objective_schema_to_yaml(template_copy)
    out = run_cmd(template_copy, "suggest", expect_ok=False)
    assert out.returncode != 0
    assert "YAML compatibility mode is disabled" in out.stderr


def test_yaml_contract_works_when_compat_mode_is_enabled(template_copy) -> None:
    _rename_objective_schema_to_yaml(template_copy)
    out = run_cmd(
        template_copy,
        "suggest",
        env={"LOOPTIMUM_YAML_COMPAT_MODE": "1"},
    )
    assert out.returncode == 0
    assert "YAML compatibility mode used for objective_schema.yaml" in out.stderr
