# Migrations

This section defines schema and state migration policy for Looptimum releases.

## Policy

1. Any schema-affecting change must include:
   - an explicit migration note document in this directory,
   - test fixtures under `tests/fixtures/state_versions/`,
   - compatibility tests that prove load/upgrade behavior.
2. `state/bo_state.json` is the authoritative artifact for state compatibility.
3. State schema uses semver in `state.schema_version`:
   - field name: `schema_version`
   - value format: `<major>.<minor>.<patch>`
4. Within `v0.3.x`, earlier `v0.3.x` states must load transparently:
   - warn-only deprecations are allowed,
   - no load failures are allowed for earlier `v0.3.x` state files.
5. Legacy `v0.2.x` state handling for the `v0.3.0` migration:
   - missing or `0.2.x` schema versions are upgraded in-memory,
   - upgraded schema version persists on the next mutating command,
   - runtime emits a loud migration warning with doc pointer.

## Canonical Fixtures

Compatibility fixture source of truth:

- `tests/fixtures/state_versions/`

Docs snapshots under `docs/examples/` are non-canonical examples and should not
be used as compatibility fixtures in tests.

## Support Window

- Current migration baseline: `v0.2.x -> v0.3.0`.
- Current compatibility guarantee: earlier `v0.3.x` state loads in `v0.3.x`.

## Migration Specs

- Template/checklist: `docs/migrations/template.md`
- Initial migration spec: `docs/migrations/v0.2.x-to-v0.3.0.md`
