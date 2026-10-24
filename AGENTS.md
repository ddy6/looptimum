# Engineering workflow

## Ax/BoTorch implementation and v1.0.0

- Follow the native Ax/BoTorch development plan in the workspace's private
  documentation. Keep private planning material outside this public repository.
- The intended release at the end of this work is GitHub tag `v1.0.0`.
  Complete compatibility, migration, documentation, and release checks before
  preparing that release; do not claim it is published during development.
- Work in substantial, coherent engineering slices. Complete as much useful
  implementation and verification as one sweep reasonably permits without
  sacrificing quality. Avoid unnecessary approval pauses for routine work.
- The user commits and pushes each completed slice. Leave changes uncommitted
  and suggest a specific commit message at each handoff. Do not commit, push,
  or create release tags as part of an engineering slice.
- Preserve existing proxy/direct-BoTorch defaults and evaluator contracts
  while introducing optional Ax support. Keep the ordinary environment lean.
- Verify Mypy in an environment installed from `requirements-dev.txt` without
  the optional optimizer stack. An Ax-enabled environment can hide missing
  optional-import errors that fail the lean GitHub type-check job.

## Long-running processes

- Finish independent implementation work before launching long checks. If a
  command returns an active process/session, record its ID and log, give a
  useful polling interval, and pause. Do not keep working while leaving an
  active check unreported, or poll again without the user's command.
- When further progress requires waiting for an active process, give the
  user a useful polling interval and pause immediately. The approximate
  three-minute limit below is a maximum, not a period to fill with inference.
  Large engineering slices do not justify active process watching. Resume
  polling only when the user commands it.
- If waiting on a process takes more than a few minutes (approximately three
  minutes), stop active monitoring and hand control back to the user. State
  what is running, retain its process/session ID and log location, and suggest
  a polling interval. Wait for the user's command before polling again.
- Polling intervals are guidance for the user, not permission to schedule
  automatic polling. Do not use repeated sleeps or background monitoring to
  bypass this workflow.
- At handoff, distinguish completed checks, running checks, and checks that
  have not run. Do not call an engineering slice verified while required
  checks are still pending.

## Website workflow

- The website publishes from GitHub. Do not launch a local worker/preview
  server or publish through Cloudflare for this work. Static builds and
  source/artifact checks are allowed.
