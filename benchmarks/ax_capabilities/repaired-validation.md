# Repaired-source validation protocol

Status: separately authorized, completed and independently audited on commit
`be806882df5286e983db51672f15949b790760ec`. All 40 campaigns completed 960 calls
and every hard gate passed; see the [separate results](repaired/readout.md).
The original 39/40 result and failed one-shot continuation remain historical
evidence. Their two unused evaluator slots do not authorize another attempt.

Use the same four workload definitions, paired arms, seeds `17,23,41,67,97`,
measurement streams, objective definitions and Pareto reference. Run all 40
campaigns from fresh portable controllers under one frozen repaired-source
manifest in a fresh output directory. Do not resume or splice the earlier matrix.

The approved new cap is **960 additional evaluator invocations**: 24 per
campaign, including six initialization slots. Failures consume slots; there are
no replacement evaluations or automatic retries. The historical total stays
958, so the cumulative benchmark cap is 1,918. At most two workers may run;
each campaign has 600 seconds, with the unchanged 120-second numerical worker
timeout and eight generation attempts per requested public candidate.

Before execution, retain the exact source/configuration/protocol hashes, Python
and six numerical dependency versions. Abort on a mismatch. Preserve every
failed case, command receipt, attempted evaluation, generation phase/rejection
count, canonical state and restore checkpoint. No seed/reference tuning or
budget extension follows a failure.

Acceptance requires all 40 campaigns to complete their fixed budgets, valid
unique public candidates, no partial allocation, recomputed counts and metrics,
modeled Ax generation, and public seeded restore with exact trial IDs/typed
choices and absolute float tolerance `1e-7`. Independently audit the raw receipts.
Report paired values, median differences and ranges without a superiority
requirement. Preserve failures even if this new matrix does not pass.

Publish a separate new summary/readout after the run. Never overwrite the
original `summary.json`, `audit.json`, `continuation.json` or their raw evidence.
