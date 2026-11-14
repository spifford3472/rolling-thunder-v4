# STAB-06F — Read-only inspection and approval-gated recovery reconciliation

Status: **offline, uninstalled draft**; 2026-11-14 UTC. This work follows draft PRs #443 and #444. No changes to AnvilMobile system services, production code, privileges, running radios, or databases.

## Design boundaries and source ownership

The read-only inspector (`deploy/rolling-thunder-recovery-inspect.py`) gathers evidence but has **no capability to start/stop services, modify Git, restore backups, change the journal, update SQLite, or transmit**. The separate reconciler (`deploy/rolling-thunder-reconcile.py`) has one narrow authority: after fresh independent verification and an explicitly approved, bound receipt, write a *reconciled* attestation into the journal. It never performs rollback, package installation, database writes, service restart or CAT/PTT actions.

The stable journal helper (`deploy/rolling-thunder-deployment-journal.py`) gains a `reconciled` terminal state. The next deployment archives the completed/reconciled prior record under `history-<transaction_id>.json` before replacing it. An unsafe or conflicting history file fails closed. No generic clear/force/recover CLI exists. A committed transaction still remains separate from a reviewed reconciliation.

## Intended configuration / installation paths (NOT installed)

- Installed system-level unit: `/etc/systemd/system/rolling-thunder.service` and its separately reviewed drop-ins.
- Existing privileged deployment wrapper: `/usr/local/sbin/rolling-thunder-deploy`.
- Deployment mutex: `/run/rolling-thunder-deploy.lock` (root-owned regular file, mode 0600, trusted root-owned directory).
- Stable helpers (intended only after separate approval): `/usr/local/libexec/rolling-thunder-deployment-journal.py`, `rolling-thunder-recovery-inspect.py`, `rolling-thunder-reconcile.py` in that directory, never in the mutable application checkout.
- Journal / archived history: `/var/lib/rolling-thunder-deploy/transaction.json`, `history-<transaction_id>.json`; directory owner root, mode 0700; files root-owned, mode 0600.
- Approval receipts: separately controlled root-owned private (0700) directory and 0600 file, generated only after **explicit operator approval**. The root-only receipt is a local approval mechanism, **not a cryptographic proof** that a particular human approved; the hosting approval workflow and audit log must be reviewed before installation.
- Database: `/home/geoff/projects/rolling-thunder-v4/config/data/rolling-thunder.db`; backups `/var/backups/rolling-thunder-deploy/`.
- Dashboard event loop heartbeat: `/run/user/<geoff_uid>/rolling-thunder-ui-readiness.json`.
- No cron, timer, background executor, new systemd unit, port, socket, API, HTTP endpoint, or persistent service is added by STAB-06F.

## Read-only evidence and classifications

The inspector reads the journal, current checkout SHA via `git rev-parse --verify HEAD` with optional locks disabled, system-level `systemctl show`, one expected user-owned dashboard PID and cgroup, optional fresh Tk heartbeat, and current/backup SQLite integrity, foreign keys, schema hash, metadata and user_version. It compares current contact count and the complete multiset of backup contact records against the current database without exporting callsigns, contact hashes, or writing records. A deleted/replaced QSO cannot be hidden by adding a new contact with the same total count. The inspector's disposition **always says `blocked_manual_review`**, even if all observations appear healthy.

SQLite is opened with `mode=ro&immutable=1` to avoid creating or modifying sidecars. Any existing WAL file or a concurrently changing database fails closed and requires a separately authorized parked-consistent snapshot. A failed or missing backup, corrupt journal, missing service, duplicated process, mismatched SHA, schema conflict or missing Tk marker cannot be called healthy. An old version without a Tk marker is reported `responsiveness=unverified`, never silently upgraded to verified.

The inspector **does not independently prove which Git commit loaded the running Python process** merely by comparing checkout SHA. An approved owner receipt must independently attest the running-code identity and specify its verification method. Software process exit or `TX0;` cannot verify physical radio receive/PTT de-key; this remains outside this software release gate.

## Controlled reconciliation (only after future approved installation)

1. While parked with no active TX or deployment, acquire and retain the same existing exclusive deployment lock.
2. Run the installed stable read-only inspector, compare transaction ID, expected previous/target SHAs, available immutable DB/backup evidence, actual process/cgroup, and fresh UI heartbeat.
3. Investigate any unverified observation. An owner must explicitly authorize the **specific** transaction and observed report fingerprint, expected running SHA and a documented independent running-identity verification method. Require an expiration timestamp and approval ID. The approval receipt must be root-owned and privately stored outside the mutable checkout.
4. The separate reconciler re-runs inspection **under the lock** and requires exact approval binding, fresh expiration, intact journal, matching running SHA, good schema and integrity, contact count not regressed, every backup QSO row still present, single expected service process and fresh Tk callback. It then only attests `reconciled` and records the approval/evidence hash. No recovery action, restore, or restart occurs.
5. The next normal deployment archives the prior reconciled record before starting a new transaction. If any step is indeterminate, **leave the journal blocked** and escalate for manual owner-approved recovery; never force-clear or silently overwrite SQLite.

This candidate intentionally does not authorize reconciliation of a legacy version lacking the heartbeat or an active WAL. It requires additional parked identity/snapshot acceptance procedures rather than falsely calling either healthy.

## Security and recovery review

- Approval and journal files must be root-owned, private, symlink-resistant; the executor must be launched from a stable privileged path, never directly from a Git checkout. The privileged CLI offers no override for production journal, lock, repo or database paths.
- Approval replay is refused because each transaction is assigned a random ID, the receipt binds an exact report SHA256 and expected SHA, the `reconciled` phase is terminal, and the approval expires. Root access remains trusted; avoid broad sudoers grants.
- Atomic journal and archive updates fsync file and parent. A failed file sync, directory sync, rename, SIGKILL or conflicting archive leaves a pending blocked record rather than claiming commit.
- An older release's systemd-active status cannot substitute for UI readiness. A person must independently verify the actual running version before approving any rollback, and any SQLite schema migration must be checked against that version.
- Merely attesting the current version cannot prove a full crash-to-healthy recovery sequence; rollback/restart execution remains separately authorized and out of scope. Do not allow a rolling vehicle or transmitting radio to serve as a recovery test.
- The current candidate is NOT install-ready until a trusted authenticated owner-approval workflow, real parked power-loss/SQLite/WAL acceptance, protected FT8 service drop-in inspection and recorded installed wrapper hashes are verified. Do not merge draft PRs or install from CI alone.

## Tests and validation

- `tests/test_recovery_inspector.py`: inspect current/backup DB, schema, contact counts, corrupt records, WAL, missing backup, old-version unknown marker, and no file mutation.
- `tests/test_recovery_process_identity.py`: actual systemd/proc classifier with fake `/proc`; duplicate, wrong PID, mismatched cgroup and legacy no-heartbeat state.
- `tests/test_recovery_reconciliation.py`: exact owner-approval binding, expiration, fail-closed safety checks, lock serialization, replay and preserved transaction history.
- `tests/test_recovery_failure_injection.py`: child SIGKILL at simulated phase; temporary-file/parent fsync and rename failures; malicious journal refusal.
- Existing STAB-06C/D/E tests remain mandatory, plus Ruff, strict MyPy, full pytest, and Git whitespace checks.

## Installation, rollback and change history

2026-11-14: Implemented and tested **offline only**. No host permissions, wrappers, jobs, integrations or infrastructure changes were installed. Revert this PR to remove the source candidate.

Before a future approved production change, document and commit all installation paths, integrations, validation, rollback, job/unit changes and this change history in private `spifford3472/ki5vnb-qth-infrastructure`. Keep backups and journals after rollback; do not restore outdated databases over new QSOs. Merge, privileged installation, parked deployment/restart and RF acceptance each require independent explicit owner authorization.
