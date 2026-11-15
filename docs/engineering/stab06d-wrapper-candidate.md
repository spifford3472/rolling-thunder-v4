# STAB-06D — captured wrapper and offline transaction candidate

Status: **uninstalled, offline draft** (2026-11-14 UTC). No production restart, privilege changes, deployment, or RF operations.

## Installed source evidence

- Source: `/usr/local/sbin/rolling-thunder-deploy` (root-owned).
- Operator-authorized read-only snapshot: `/home/geoff/rolling-thunder-review/installed-wrapper-20261114T035408Z.sh`.
- Captured SHA256: `476ecdbdbcc70bcb1025ac1ce97bae1982b98d8842d5e333ea43632378512daf`; 7,257 bytes, 255 lines; Bash syntax valid.
- The isolated Forge copy has the same SHA256. The separately printed installed-root-file hash was not captured by this session; compare it in an authorized verification before installation.
- `deploy/rolling-thunder-deploy.candidate` is a **nonexecutable source candidate**, not an authorized installer or running wrapper.

## Existing behavior and candidate corrections

The captured script validates a 40-character lowercase target SHA and remote branch containment, checks out the exact commit, stops the system service, creates a SQLite online backup, updates the editable Python installation, performs migrations/integrity checks, restarts the service and attempts schema-compatible old-code rollback while preserving the current database. Its original three-second `systemctl is-active` check did not verify actual UI readiness, and it contained no deployment transaction lock.

The candidate adds an exclusive, nonblocking `flock` under root-owned `/run/rolling-thunder-deploy.lock` before any Git fetch, stop, backup, checkout, or mutation, retaining descriptor 9 through rollback. It checks root ownership and private 0600 permissions for existing locks and refuses obvious unsafe lock paths; review the trusted-parent and no-symlink assumptions before privileged installation.

It also checks the backup directory before service stop, fails if backup ownership/permissions cannot be secured, and reports attempted recovery failures. It replaces the three-second activity check with a bounded 210-second `deployment_readiness.py` probe requiring the system-level service, expected user, MainPID, cgroup, exactly one dashboard process and a fresh Tk-callback heartbeat.

`ui_readiness.py` atomically writes a small marker into the user's private XDG runtime directory. It updates only from the Tk event loop: blocked UI callbacks cannot keep the marker fresh. This proves callback liveness, **not** operator workflow, GPS, radio state, physical receive/PTT release, or durable QSO correctness.

## Deterministic verification

- `tests/test_deployment_wrapper_candidate.py`: Bash syntax, nonexecutable source, lock-before-mutation ordering, backup gate and readiness wiring.
- `tests/test_deployment_wrapper_offline.py`: isolated, path-rewritten fake Git/systemd/SQLite wrapper; overlapping deploy refusal, malformed SHA, failed backup with prior-service restart attempt, schema-changing rollback refusal preserving contacts, and failed start with prior-code rollback.
- `tests/test_ui_deployment_readiness.py`: display-free Tk callback fake, freshness, private marker ownership, process/cgroup/UID checks, wrong service state and duplicate-dashboard refusal.

## Remaining hard safety gates

The candidate still requires durable interrupted-transaction reconciliation, further failure-injection for failed installation, rollback restart/readiness, wrong checkout SHA, and abrupt power loss. An old-code rollback may lack the new heartbeat and must be reported as *not independently readiness-verified*. No `systemctl is-active`, heartbeat, or successful `TX0;` is independent proof of hardware de-key. Existing CAT/PTT uncertainty remains.

Before any root-wrapper installation or parked production acceptance, verify the protected FT8 drop-in, recorded hashes, and exact target, current and rollback SHAs. Commit all installed service/wrapper configuration paths, integrations, validation, rollback and history in `spifford3472/ki5vnb-qth-infrastructure`. Obtain separate owner approvals for merge, installation, deployment/restart and RF.

## Change history / rollback

2026-11-14: Captured the operator-authorized wrapper, wrote an uninstalled candidate, added Tk heartbeat/readiness and offline failure injection. Revert the draft source commit to remove the candidate; no installed host configuration has changed.
