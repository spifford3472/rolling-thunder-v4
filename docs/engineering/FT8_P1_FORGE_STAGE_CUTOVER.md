# FT8-P1 Forge staging and controlled cutover — PR #255

Release candidate: `cbdec404d6a4e67846c7f2dca2f25dec9846110c` (refresh and re-review if PR HEAD changes).

**State: PREPARED ONLY. No production installation, secret provisioning, service restart, or RF authorization.** The Forge contact-sync service is shared with Wavelog contact uploads, so even a Forge-only release requires an operator-approved maintenance window, independent review, and immediate rollback readiness.

## Confirmed preflight (October 10, 2026)

- Clean development worktree, branch `feature/ft8-p1-power-advisor`; draft PR #255.
- Running Forge contact-sync binary: `/opt/rolling-thunder-forge-contact-sync/.venv/bin/rolling-thunder-forge-contact-sync`, package version 4.4.0. The version alone does not establish its source SHA; capture the deployed artifact hash and package metadata before cutover.
- Unit runs as `rollingthunder`, reads `/etc/rolling-thunder/forge-contact-sync.env` and `/etc/rolling-thunder/forge-contact-sync.yaml`; both are mode 0640, owned `root:rollingthunder`. Unit has hardening and `StateDirectory=rolling-thunder`.
- New FT8 token key was absent in the existing environment file. Its absence is expected before installation; no token value was inspected, generated, or logged.
- Isolated API/storage/correlation tests: 15 passed. A *read-only SQLite backup* of the production contact-sync database was migrated in a mode-0700 temporary staging directory; migration added nullable TX offset and `PRAGMA quick_check` returned `ok`. Original DB was not migrated.
- Contact-sync, PSK Reporter, and callsign-info services were active during checks. No service restart.

## Credential contract — operator review required

The code expects `ROLLING_THUNDER_FT8_PERIOD_TOKEN` as the **same dedicated, high-entropy bearer token** in the Forge contact-sync and Pi client processes. This is not a Wavelog key, GitHub credential, WireGuard key, or general login token.

For the existing Forge unit, the least disruptive approved option is to add this variable to its *already protected*, root-owned 0640 `EnvironmentFile` through a root-only local procedure **after** inspecting backups, current file content, and process-environment exposure risk. Environment variables can be exposed to privileged debuggers and child processes: this is not equivalent to systemd encrypted credentials. Do not print values in terminals, shell history, journal, trace logs, or PRs; do not place secrets into repository tracked files. If using `LoadCredential` instead, implement an explicit `..._FILE` reader in the application first: merely declaring `LoadCredential` will not populate `os.environ` and will fail closed. Verify permissions, unit environment, and restart semantics before activating the endpoint.

Do not provision a Forge-only token and assume the Pi has it; deliver the same dedicated token over an approved protected channel, validate securely on each host without echoing it, and keep the private listener limited to WireGuard/firewall networks. Rotating this token is a coordinated two-sided change. A missing token must yield fail-closed behavior on `/ft8-period`, without affecting ordinary `/contacts` requests.

## Mandatory checks before approval

1. Independent PR review, branch protection/CI, final exact SHA, unchanged unrelated services, and migration/retry/auth regression tests.
2. Verify current production package and available rollback wheel/source, unit, env/config, DB size, free space, and same-filesystem backup target. Make an on-disk SQLite consistent backup immediately before cutover; do not copy only the `.db` file while WAL writes may be active.
3. Stage the *approved exact-SHA artifact* in a separate nonproduction path and isolated virtual environment. Verify wheel SHA-256, dependencies, importability, and API contract tests against synthetic or copied data. Never run staging against production Wavelog API or radio hardware.
4. Exercise no-token, wrong-token, correct-token, identical replay, changed replay, SQLite restart/migration, and error handling in an isolated listener/process. Confirm private port binding and no secret appears in output.
5. Document explicit go/no-go and rollback operator decision, maintenance window, expected contact-sync interruption, and deployment helper procedure. No implicit merge.

## Approved deployment sequence (instructions only; do not execute yet)

- Capture timestamp, old package artifact/checksum, unit/config checksums, current service/ledger health, database backup and integrity check. Protect each backup with mode 0600 and appropriate ownership.
- Under explicit approval, install the pinned Forge package into the independently managed contact-sync runtime using the documented exact-SHA deployment helper; provision the dedicated secret with approved secure method; restart **only** `rolling-thunder-forge-contact-sync.service`.
- Confirm service healthy and `/contacts` behavior unchanged; use non-RF synthetic `/ft8-period` requests on the private listener, checking missing/wrong bearer denied and accepted/duplicate/conflicting replay behavior. Check Wavelog sync and PSK Reporter service independently; do not restart PSK-N2.
- If any acceptance fails, stop new FT8 uploads and restore the previous executable/configuration/service configuration. **Preserve all durable SQLite and outbox records created after cutover. Never overwrite newer evidence with an older DB backup.** Reconcile incompatible schema/API before reopening writes.
- Only after Forge acceptance, separately approve the Pi release and no-RF validation. Physical transmission/watchdog acceptance remains another gate.

## Operator approvals not yet granted

- Independent reviewer and final SHA signoff: pending
- Secret provisioning method and exposure review: pending
- Forge installation/restart: pending
- Pi installation/restart: pending
- Any RF tests: pending
