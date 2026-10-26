# State Version Fixtures (Canonical)

Canonical Phase 3 compatibility fixtures for state-loading tests live in this
directory.

Fixture policy:

- These fixtures are the authoritative source for cross-version state-load
  compatibility tests.
- Docs snapshots under `docs/examples/` are non-canonical references and should
  not be used as compatibility test fixtures.
- New schema-affecting releases should add or update fixtures here and keep
  filenames explicit about target versions.

Current fixtures:

- `v0_2_x_missing_schema_version.json`
- `v0_2_2_explicit_schema_version.json`
- `v0_3_1_schema_version.json`
- `v0_4_0_ax_schema.json`: explicitly marked Ax state; its missing snapshot is
  intentional so this fixture does not claim exact optimizer restoration.
- `released_v0_4_0_state_reader.py.txt`: unmodified prefix of the released
  v0.4.0 shared runtime, through `normalize_state_schema_version`. Kept as text
  so lint/format tools cannot rewrite historical reader behavior. The sibling
  provenance JSON records source tag/commit/Git blob and full/fragment hashes.
  Compatibility tests execute this exact reader to prove legacy acceptance
  and Ax rejection without fetching tags in CI.
