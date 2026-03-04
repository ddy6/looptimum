# Decision-Trace Examples

This folder holds Phase 6 trust-building decision-trace artifacts:

- `golden_acquisition_log.jsonl`: deterministic sample acquisition log
- `golden_acquisition_log.md`: field-by-field annotation and generation command
- `cli_transcript.md`: text transcript of `suggest -> evaluate -> ingest -> status`
- `regenerate_golden_log.sh`: one-command regeneration script for the golden log

These artifacts are integration/audit references, not benchmark claims.

Note:

- The golden log export uses normalized synthetic timestamps so regenerated files
  are stable in version control.

Regeneration command:

```bash
bash docs/examples/decision_trace/regenerate_golden_log.sh
```
