# Release procedure

This repository publishes releases from reviewed commits and GitHub tags.
Changing package metadata or writing release notes does not publish a release.
The owner commits and pushes engineering slices; do not create a tag while
required checks are pending. There is no PyPI publication or website server
step in this procedure.

Published tags and releases are immutable. Both `v1.0.0` and `v1.1.0` are already
published; preserve their identities and prepare a new version for later changes.

## Released v1.1.0 reference

[Looptimum v1.1.0](https://github.com/ddy6/looptimum/releases/tag/v1.1.0) was published
on 2026-11-05 from commit `ffe6f6b95e495e3befdb9e7fdf18af053073c701`.
Its [source CI](https://github.com/ddy6/looptimum/actions/runs/42098079847) and
[tag CI](https://github.com/ddy6/looptimum/actions/runs/42101654431) each passed all ten
required jobs. All four Ax artifacts per run were downloaded and verified, with
270 passing integration tests per lane, zero skips and matching pinned targets.

- Package metadata: `pyproject.toml`, version `1.1.0`, no default dependencies.
- Stable scope: [stability guarantees](stability-guarantees.md).
- Upgrade/rollback: [migration guide](migration-v1.md).
- Published notes: [v1.1.0](releases/v1.1.0.md) and [changelog](../CHANGELOG.md).
- Ax dependency/CPU profile and supported surface:
  [installation](ax-installation.md), [matrix](ax-support-matrix.md).
- Ax contract-2 evidence: [audited C5 matrix](../benchmarks/ax_capabilities/repaired/readout.md),
  40 campaigns / 960 evaluations on the recorded repaired-source commit.
- Numerical evidence: [GP-fix comparison](../benchmarks/backend_comparison/gp_fix/readout.md).
  The original failed reference and older golden benchmark assets remain intact.

## Required evidence

For a future release, first select a new version and update package/preview
metadata, release notes, changelog and current version references together.
The commands below use `X.Y.Z` as a placeholder: replace every occurrence with
that new version. Do not rerun publication commands for an existing release.

Run the following on the final source tree using a lean dev environment:

```bash
python -m ruff format --check .
python -m ruff check .
python -m mypy
python scripts/check_release.py --expected-version X.Y.Z
python scripts/check_internal_links.py --paths README.md docs quickstart client_harness_template
python scripts/check_docs_consistency.py
python scripts/check_ci_playbook_sync.py
python scripts/check_benchmark_sanity.py
python -m pytest -q templates client_harness_template/tests service/tests
python -m unittest discover -s docs/examples/gpt_training_campaign/tests -p 'test*.py' -v
python scripts/release_smoke.py
```

CI's release-smoke job also builds the package wheel with its pinned build
backend and checks the wheel's version, optional Ax dependency and service
assets against source metadata. It also installs that wheel without an index
or dependencies into a fresh venv, then checks its installed version and the
absence of numerical packages. The wheel contains the service package; generate
portable controllers from the repository, not from a presumed controller SDK.

All four required Ax lanes must pass on the exact release commit:
Linux x86_64 and macOS arm64, each on CPython 3.11 and 3.12. Each verifies
fresh hashed wheelhouse installation, `pip check`, CPU model/restart probe,
optional integration/recovery tests, the mixed evaluator and backend smoke.
Retain the `ax-evidence-*` artifacts and the run URL with the release record.
Passing an earlier implementation commit is insufficient for the release.

The 200-campaign reference need not be regenerated for version/doc changes.
Regenerate separate evidence if numerical policy changes; never overwrite
the earlier reference to conceal a failure. Follow `AGENTS.md` when a process
remains active: report its session/log and polling interval, then wait for the
owner's command. Do not monitor it continuously.

## Commit, push and verify

Commit the prepared release slice and push it through the normal repository
workflow. Then, from that exact commit and a clean tree:

```bash
python scripts/check_release.py --expected-version X.Y.Z --require-clean
git rev-parse HEAD
gh run list --workflow ci.yml --branch main --limit 5 \
  --json databaseId,headSha,status,conclusion
```

Choose the CI run whose `headSha` exactly matches `git rev-parse HEAD`. It must
be completed with conclusion `success`, including all four Ax lanes and the
quality, lean unit, Mypy, release-smoke and Node 24 site-validation jobs. Inspect
its jobs and download its evidence before tagging. Do not treat a running/skipped lane as proof of
support. The final changelog date should match the intended publication date.

## Publish the tag

Only after the previous checks pass, the owner can create an annotated tag:

```bash
git tag -a vX.Y.Z -m "Looptimum vX.Y.Z"
python scripts/check_release.py --expected-version X.Y.Z --tag vX.Y.Z --require-clean
git push origin refs/tags/vX.Y.Z
```

The tag check rejects a mismatched version or a tag pointing at a different
commit. CI also applies it on tag pushes. Confirm the tag-triggered CI run
succeeds. Do not move an already published release tag to repair a defect;
prepare a reviewed patch release with its own notes and evidence.

If publishing a GitHub Release entry, use the prepared notes after tag CI:

```bash
gh release create vX.Y.Z --verify-tag --title "Looptimum vX.Y.Z" \
  --notes-file docs/releases/vX.Y.Z.md
```

Tag push and GitHub Release creation are publication actions. This guide
prepares them; it does not authorize an agent to replace the owner's commit/
push workflow or report publication before those actions succeed.
