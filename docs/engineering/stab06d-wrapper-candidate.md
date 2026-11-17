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

It also checks the backup directory before service stop, fails if backup ownership/permissions cannot be secured, and reports attempted recovery failures. When backup creation or backup permission setup fails after the original service was stopped, it starts the unchanged release, runs the same bounded application-readiness probe, and leaves the journal at `requires_review`; a successful `systemctl start` alone is not reported as recovery. The probe requires the system-level service, expected user, MainPID, cgroup, exactly one dashboard process and a fresh Tk-callback heartbeat.

Rollback now verifies that the exact previous checkout was restored and that its editable install succeeded **before** restarting the service. It then runs the same bounded application-readiness probe. A failed checkout/install leaves the service stopped; a failed rollback readiness check leaves the transaction journal in `rolling_back` and reports recovery as unverified. A prior release that lacks the readiness module therefore fails closed and requires independent manual review; it is not silently called healthy.

`ui_readiness.py` atomically writes a small marker into the user's private XDG runtime directory. It updates only from the Tk event loop: blocked UI callbacks cannot keep the marker fresh. This proves callback liveness, **not** operator workflow, GPS, radio state, physical receive/PTT release, or durable QSO correctness.

## Deterministic verification

- `tests/test_deployment_wrapper_candidate.py`: Bash syntax, nonexecutable source, lock-before-mutation ordering, backup gate and readiness wiring.
- `tests/test_deployment_wrapper_offline.py`: isolated, path-rewritten fake Git/systemd/SQLite wrapper; overlapping deploy refusal, malformed SHA, backup-failure recovery readiness and review-journal behavior, schema-changing rollback refusal preserving contacts, failed start with prior-code rollback, no restart after failed previous-code restoration, and rollback readiness refusal.
- `tests/test_ui_deployment_readiness.py`: display-free Tk callback fake, freshness, private marker ownership, process/cgroup/UID checks, wrong service state and duplicate-dashboard refusal.

## Remaining hard safety gates

The candidate remains uninstalled and requires protected installed-file comparison, durable interrupted-transaction reconciliation, failure-injection for wrong checkout SHA and abrupt power loss, plus owner-approved parked acceptance. A previous release without the new readiness module cannot pass rollback readiness and remains an explicit manual-review state. No `systemctl is-active`, heartbeat, or successful `TX0;` is independent proof of hardware de-key. Existing CAT/PTT uncertainty remains.

Before any root-wrapper installation or parked production acceptance, verify the protected FT8 drop-in, recorded hashes, and exact target, current and rollback SHAs. Commit all installed service/wrapper configuration paths, integrations, validation, rollback and history in `spifford3472/ki5vnb-qth-infrastructure`. Obtain separate owner approvals for merge, installation, deployment/restart and RF.

## Change history / rollback

2026-11-14: Captured the operator-authorized wrapper, wrote an uninstalled candidate, added Tk heartbeat/readiness and offline failure injection. Revert the draft source commit to remove the candidate; no installed host configuration has changed.
2026-11-16: Require previous-code SHA/install verification and dashboard readiness before reporting a recovered rollback; added deterministic refusal tests. No production files or services were changed.
