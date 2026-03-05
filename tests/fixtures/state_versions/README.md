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
