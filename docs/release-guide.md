# Release procedure

This repository publishes releases from reviewed commits and GitHub tags.
Changing package metadata or writing release notes does not publish a release.
The owner commits and pushes engineering slices; do not create a tag while
required checks are pending. There is no PyPI publication or website server
step in this procedure.

## v1.0.0 inputs

- Package metadata: `pyproject.toml`, version `1.0.0`, no default dependencies.
- Stable scope: [stability guarantees](stability-guarantees.md).
- Upgrade/rollback: [migration guide](migration-v1.md).
- Prepared notes: [v1.0.0](releases/v1.0.0.md) and [changelog](../CHANGELOG.md).
- Ax dependency/CPU profile and supported surface:
  [installation](ax-installation.md), [matrix](ax-support-matrix.md).
- Numerical evidence: [GP-fix comparison](../benchmarks/backend_comparison/gp_fix/readout.md).
  The original failed reference and older golden benchmark assets remain intact.

## Required evidence

Run the following on the final source tree using a lean dev environment:

```bash
python -m ruff format --check .
python -m ruff check .
python -m mypy
python scripts/check_release.py --expected-version 1.0.0
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
python scripts/check_release.py --expected-version 1.0.0 --require-clean
git rev-parse HEAD
gh run list --workflow ci.yml --branch main --limit 5 \
  --json databaseId,headSha,status,conclusion
```

Choose the CI run whose `headSha` exactly matches `git rev-parse HEAD`. It must
be completed with conclusion `success`, including all four Ax lanes and the
quality, lean unit, Mypy and release-smoke jobs. Inspect its jobs and download
its evidence before tagging. Do not treat a running/skipped lane as proof of
support. The final changelog date should match the intended publication date.

## Publish the tag

Only after the previous checks pass, the owner can create an annotated tag:

```bash
git tag -a v1.0.0 -m "Looptimum v1.0.0"
python scripts/check_release.py --expected-version 1.0.0 --tag v1.0.0 --require-clean
git push origin refs/tags/v1.0.0
```

The tag check rejects a mismatched version or a tag pointing at a different
commit. CI also applies it on tag pushes. Confirm the tag-triggered CI run
succeeds. Do not move an already published release tag to repair a defect;
prepare a reviewed patch release with its own notes and evidence.

If publishing a GitHub Release entry, use the prepared notes after tag CI:

```bash
gh release create v1.0.0 --verify-tag --title "Looptimum v1.0.0" \
  --notes-file docs/releases/v1.0.0.md
```

Tag push and GitHub Release creation are publication actions. This guide
prepares them; it does not authorize an agent to replace the owner's commit/
push workflow or report publication before those actions succeed.
