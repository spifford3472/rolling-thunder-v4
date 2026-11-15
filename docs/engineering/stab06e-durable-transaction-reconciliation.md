# STAB-06E — durable deployment transaction journal and fail-closed recovery

Status: **offline candidate / draft only** (2026-11-14 UTC). No installation, deployment, radio or host state change.

## Design and ownership

The root-owned deployment wrapper remains the **single** authorized mutation path and must acquire its existing deployment flock before invoking the stable journal helper. The stdlib-only `deploy/rolling-thunder-deployment-journal.py` is intended for separate, owner-approved root installation at `/usr/local/libexec/rolling-thunder-deployment-journal.py`; its record is intended for a pre-created private root directory `/var/lib/rolling-thunder-deploy/transaction.json` (0700 directory and 0600 record). Neither location is created or altered on AnvilMobile by this PR.

The journal records a random transaction ID, exact previous and target Git SHAs, expected SQLite backup path, timestamp and phase. It atomically replaces a temporary JSON record with `fsync` of its file and parent directory. Any malformed or suspicious journal fails closed. A `begin` refuses any existing record other than a committed transaction. `phase` requires an adjacent forward phase transition or an explicit rollback/review state. `commit` is allowed only from the final verifying phase.

The offline `deploy/rolling-thunder-deploy.candidate` now creates a durable `prepared` record after reading the current SHA and before Git fetch; transitions through `stopping`, `backing_up`, `checkout`, `installing`, `migrating`, `starting`, `verifying`, and finally `committed` **only after** bounded UI readiness and exact target SHA verification. A rollback is recorded as `rolling_back` but cannot auto-commit. A killed shell cannot remove, erase or automatically reconcile a pending record. The next attempted deployment is refused before Git fetch or service mutation.

## Failure and recovery policy

**No automatic recovery action following an incomplete deployment**. The journal is intentionally not automatically cleared on normal failure, shell exit, SIGKILL, or power loss. The responsible operator must inspect the recorded phase, independently verify current checkout SHA, actual running process/cgroup, dashboard responsiveness, SQLite integrity/schema version, QSO preservation, backup availability and exact version compatibility before a separately authorized recovery. An incomplete record is evidence, not authority to install old code or restore old data. No automatic `resolve` or `force-clear` API exists in this version.

An older version may lack the new Tk heartbeat; a started service or successful software PTT release is not proof of readiness or physical radio receive. Recovery must keep CAT/PTT unknown where de-key was not independently verified. Never overwrite newer QSOs or migrated SQLite data with a predeployment copy. Crash-safe journal durability is a software property under normal filesystem semantics; it does not prove hardware write-cache/power-loss guarantees, nor that the wrapper's existing unchecked commands and rollback path are all corrected.

## Offline validation

`tests/test_deployment_transaction_journal.py` exercises every interrupted phase (including rollback), corruption and symlink rejection, strict transitions, private permissions, durable commit and refusal to force-clear. `tests/test_deployment_wrapper_offline.py` adds failure carryover and corrupt-journal refusal to its fake-Git/fake-systemd/SQLite suite. `tests/test_deployment_wrapper_candidate.py` checks that journaling starts before fetch, all phases are ordered, and commit precedes success reporting.

## Remaining pre-installation gates

- Review actual installed root-owned wrapper hash, protected service drop-ins, fixed journal/helper paths and ownership; preserve existing narrowly authorized deployment entry points.
- Add explicit, independently verified operator reconciliation procedure and authorization to resolve a blocked transaction without overwriting contacts. Do not silently bypass the journal on rollback.
- Test power-loss interruption, failed journal writes/fsync, abnormal shell termination and post-rollback degraded readiness; validate exact runtime identity and database compatibility.
- Review how the helper remains stable across code checkout/install and how the existing privileged wrapper is staged and rolled back independently of application code.
- Commit any actual 192.168.9/10 or OPNsense-related host/infrastructure change record in `spifford3472/ki5vnb-qth-infrastructure` with paths, permissions, jobs, integrations, validation, rollback and history.
- Separate owner approvals remain required for merge, privileged install, parked deployment/restart and RF.

## Change history and rollback

2026-11-14: Added offline stable journal helper, candidate wrapper phase markers and hardware-free interrupted/retry tests. Rollback is source revert; no production installation occurred.
