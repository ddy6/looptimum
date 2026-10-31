# Installing the CPU Ax controller

Ax is optional. Only the environment generating suggestions or rebuilding an
optimizer needs this stack. Evaluators, ingestion, status/reporting, worker
leases, retirement, cancellation, canonical import, and allocation-publication
repair continue to work without importing Ax, Torch, BoTorch, GPyTorch or NumPy.
The default controller still uses the existing legacy backend.

## Tested profile and targets

The [runtime constraints](../templates/_shared/ax-constraints.txt) pin the full
dependency closure, including `botorch[pymoo]`. The numerical core is Ax 1.3.1,
BoTorch 0.18.1, Torch 2.14.1, GPyTorch 1.15.2, NumPy 2.4.6 and SciPy 1.17.1.
Setuptools is pinned at 80.9.0 to meet Torch's declared minimum; a successful
numerical run alone does not establish that an installation is consistent.

| Controller target | Verification |
| --- | --- |
| Linux x86_64, CPython 3.11 and 3.12 | Required Ax CI lanes, CPU Torch wheel |
| macOS arm64, CPython 3.11 and 3.12 | Required Ax CI lanes, PyPI Torch wheel, CPU generation |
| Other OS/architectures/interpreters, CUDA/MPS execution | Outside this installation profile |

These are the supported CPU release targets. Each required CI lane builds a wheelhouse,
installs it into a fresh virtual environment without an index, runs `pip check`,
probes real model generation and seeded JSON restart, runs the integration and
recovery suite, and executes the mixed external-evaluator example. CI retains
the exact wheel inventory, hashes, installation versions, probe and test receipt.
All four lanes passed for implementation commit `70e2e58`
([CI run](https://github.com/ddy6/looptimum/actions/runs/40289436046));
the final release commit must pass them again before tagging.
The [GitHub runner reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
identifies `macos-15` as arm64; the installer also checks the actual architecture.

Package pins describe a tested profile; the per-target generated lock records
the actual wheel hashes. Linux uses Torch's `+cpu` distribution from the
[official CPU index](https://download.pytorch.org/whl/cpu).
Do not substitute PyPI's Linux Torch build, which can resolve CUDA packages.
The builder downloads Torch separately and supplies that local wheel to the
Ax resolver. All remaining packages come from PyPI; no extra index is mixed in.

## Connected preparation

Prepare on the **same OS, architecture and CPython minor** as the target.
Use a machine with a compatible macOS deployment target or Linux glibc baseline;
the bundle is not a universal cross-platform artifact. This workflow downloads
wheels only and fails if an exact binary dependency cannot be resolved.

From the repository root:

```bash
python3.11 templates/_shared/vendor_copy.py templates/bo_client /tmp/ax-controller
python3.11 /tmp/ax-controller/ax_install.py build /tmp/ax-wheelhouse
python3.11 /tmp/ax-controller/ax_install.py check /tmp/ax-wheelhouse
```

Use `bo_client_full` instead for the full template. Both portable copies contain
`ax_install.py`, `ax-constraints.txt` and `requirements-ax.txt`, with all paths
rewritten for use outside the repository. The installer needs only Python's
standard library and pip, and does not import the numerical stack.

The destination must not exist. Downloads and resolution happen in a temporary
directory; failure does not publish a partial wheelhouse or replace an existing
bundle. A successful bundle contains:

- `wheels/`: one wheel per resolved runtime distribution;
- `requirements.lock`: exact versions and SHA-256 hashes, including Linux `+cpu`;
- `ax-constraints.txt`: the source profile;
- `manifest.json`: target, profile digest, package names, versions and wheel hashes.

Archive and transfer the whole wheelhouse along with the portable controller.
Keep the bundle with campaign backups so the matching environment can be
recreated later. Wheel hashes detect accidental changes; they are not signatures
and do not authenticate the source of a transferred bundle.

## Offline installation

On the matching target, create a **fresh** virtual environment using its local
Python installation. Standard `venv` includes pip through `ensurepip` without
downloading packages. Do not upgrade pip over the network on the offline host.

```bash
python3.11 -I -m venv /tmp/ax-runtime
python3.11 /tmp/ax-controller/ax_install.py install /tmp/ax-wheelhouse \
  --python /tmp/ax-runtime/bin/python --receipt /tmp/ax-installation.json
```

The installer checks OS/architecture/Python minor, profile digest, wheel
metadata and hashes, exact inventory, and the generated lock before invoking
pip. Pip runs with Python `-I` to ignore inherited Python paths, home and user
site packages. Installation uses `--isolated --no-index --find-links --require-hashes`
with binary wheels only. Requirements contain package/version pins, never
direct URLs. No source build, dependency index, or package download is needed.
`pip check` and an installed-version comparison must pass before the receipt
is written. A failed install may leave a partially populated environment;
discard it and retry with a fresh environment after correcting the cause.
This workflow verifies local package installation; it does not configure
network isolation or certify an arbitrary third-party evaluator.

When the repository is available, verify numerical imports and real model
generation using the installed interpreter:

```bash
/tmp/ax-runtime/bin/python scripts/probe_ax_compatibility.py \
  --output /tmp/ax-compatibility.json
/tmp/ax-runtime/bin/python examples/ax_pipeline_tuning/run_pipeline_loop.py \
  --destination /tmp/ax-pipeline-verification --steps 4 --initialization 2
```

The probe rejects a CUDA Torch build, runs on CPU, and checks a seeded modeled
proposal after JSON save/reload. The pipeline example exercises a fresh portable
controller, actual model-guided selection, and an external standard-library
evaluator and ingestion under `python -S`. It needs no package index. Preserve
both receipts and the example state as installation evidence.

## Repository installs and environment changes

For convenience, `pip install '.[ax]'` still installs the optional Ax dependency
from a checkout. It pins Ax, but does **not** freeze the full runtime or select
Linux CPU Torch. Use the wheelhouse workflow for reproducible CPU environments.
The templates' `requirements-ax.txt` applies the complete constraints; install
CPU Torch first on Linux when using that manual route.

An existing campaign guards the six recorded numerical dependency versions;
the installation receipt additionally records all installed distributions.
Changing any of the six requires restoring the matching environment or an
explicit [optimizer rebuild](ax-backend.md#rebuild-a-lost-optimizer-snapshot).
Rebuild starts a new lineage and is not exact continuation. Updates to a tested
profile need fresh wheelhouses and compatibility evidence on each target.
Identical suggestions across operating systems, Python minors or dependency
versions are not promised.
