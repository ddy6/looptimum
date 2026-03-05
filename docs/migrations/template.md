# Migration Spec Template

Use this template for any schema-affecting change.

## Metadata

- Migration id: `<release-or-change-id>`
- Source versions: `<from-version-range>`
- Target version: `<to-version>`
- Owner: `<name>`
- Date: `<YYYY-MM-DD>`

## Scope

- Artifacts affected:
  - `state/bo_state.json`
  - payload schemas (`suggestion`, `ingest`, `doctor`, `report`) as applicable
  - any derived artifacts with schema-sensitive fields
- Out-of-scope:
  - `<explicitly list>`

## Contract Changes

- Added:
  - `<fields>`
- Changed:
  - `<fields/semantics>`
- Deprecated:
  - `<fields/paths>`
- Removed:
  - `<fields/paths>`

## Compatibility Behavior

- Load behavior for old artifacts:
  - `<rules>`
- Upgrade behavior:
  - `<in-memory vs persisted behavior>`
- Warning/error policy:
  - `<messages + fatal/non-fatal>`

## Test Plan Checklist

- [ ] Canonical fixtures added/updated under `tests/fixtures/state_versions/`
- [ ] Compatibility tests cover old fixture load behavior
- [ ] Upgrade-path tests cover old fixture -> current runtime -> valid outputs
- [ ] Rejection tests cover unsupported future/incompatible schema versions
- [ ] Payload schema assertions updated (`suggest`/`ingest`/`doctor`/`report`)

## Operational Notes

- Rollout/rollback guidance:
  - `<notes>`
- Required operator actions:
  - `<actions>`

## References

- Code PR/commit: `<ref>`
- Changelog entry: `<ref>`
- Related docs: `<ref>`
