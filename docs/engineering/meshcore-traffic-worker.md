# MeshCore durable traffic worker — Issue #395 follow-on

## Current state and authority

The independently runnable traffic worker is already merged and deployed as
source, but its **continuous user service is not installed or enabled**. The
staged systemd unit introduced by this milestone remains inactive unless
separately approved and installed. The running `meshcore-collector.service` is unchanged and remains the sole USB
owner. Rolling Thunder and SCOUT's distinct broker credentials/cursors remain
independent.

The component may only read **public** broker messages over the existing
owner-only Unix socket and, after durable local processing, ACK the same
authorized public consumer cursor. It does not connect to the radio, serial
port, CAT, PTT, internet, Nominatim, GPS, Tkinter, SCOUT speech, voice commands,
dashboard notifications, or MeshCore transmission. There is no map or journey
relevance decision and no automatic driving alert.

## Data and processing flow

1. `meshcore_public_consumer.py`: authenticated `GET /v1/messages/public`
   on `/run/user/1000/meshcore-broker.sock` using one existing locally
   protected token file for an explicit consumer identity. It never previews
   private/quarantine.
2. `meshcore_public_intelligence.py`: requires the operator-approved exact
   #traffic slot/name; presently **slot 1 #traffic**. The existing pure incident
   classifier returns **unverified candidates**. Other verified public
   channels (currently slot 0 Public) are still durably recorded as ignored,
   not misclassified as traffic.
3. `meshcore_traffic_ledger.py`: a **separate schema-1 owner-only SQLite**
   database. For each public broker message ID, it persists message digest,
   channel metadata, received time, classification and one disposition:
   `candidate`, `duplicate`, `ignored`. Does not store raw text or any
   private frame. A 30-minute **rolling window** suppresses identical normalized
   candidate text from the same verified channel as additional candidates.
   Every duplicate is still tracked by distinct source ID.
4. `meshcore_traffic_worker.py`: bounded 1–100 items per pass; processes
   **one item at a time**, waiting for FULL synchronous SQLite commit, then
   invokes explicit `acknowledge_processed(message_id)`. Failure before
   commit means **no ACK**. A crash/error between commit and broker ACK leads
   to idempotent replay and safe retry of that exact ACK. The replayed message
   ID must hash to identical contents or the worker fails closed.
5. `meshcore_traffic_worker_main.py`: separate manual `--once` or
   `--loop` entry point; owner-only lock and nonblocking advisory flock
   prevent simultaneous workers against one database. Continuous mode
   uses a bounded 2–120 s poll cadence, exponential retry up to 120 seconds
   when the broker is unavailable, and handles termination between cycles.
   The live worker is **not started automatically by Rolling Thunder**.

**Ordering and recovery:** Processing uses the broker's ascending message IDs.
Each item is committed before the matching ACK. If an ACK fails, processing
stops and the next run retries the same ID without a second candidate row.
No messages are silently deleted, and another consumer's cursor is never
advanced. A source payload change under an existing ID fails closed. The
worker does not assume exactly-once transport, only idempotent durable local
processing and at-least-once broker delivery until ACK.

**Storage/backpressure:** maximum 250,000 ledger rows (or less when configured);
at capacity the worker stops **without ACK** rather than pruning historical
evidence. Only normalized cryptographic digests and report attributes are
retained; no personal/private text. Existing broker capacity and private
retention policies remain separate. Owner-only directories 0700 and
database/lock files 0600 are required.

## Manual dry-run invocation (do not enable while driving)

After a separately owner-approved exact-SHA source deployment and a parked
read-only preflight, a **single explicitly authorized** live worker invocation
could be:

```bash
/home/geoff/projects/rolling-thunder-v4/.venv/bin/python \
  -m rolling_thunder.meshcore_traffic_worker_main \
  --socket /run/user/1000/meshcore-broker.sock \
  --credential /home/geoff/.config/rolling-thunder/meshcore-broker-credentials/rolling-thunder.token \
  --database /home/geoff/.local/share/meshcore-collector/meshcore-traffic-ledger.db \
  --traffic-slot 1 --batch-size 25 --once
```

**This command is a mutating acceptance action, not an ordinary read-only
preview.** It will create a new local database and ACK up to 25 public
messages on the specified Rolling Thunder consumer cursor. Never run it on
the operator or SCOUT token by accident. It does not send RF or display
alerts. The existing 25-message preview command remains read-only and safe
for health verification; use that instead when preserving consumer cursor
state is required.

The source repository now includes a **staged, uninstalled** systemd user-unit
`deploy/meshcore-traffic-worker.user.service`. It is not enabled by source
checkout, merge, or the existing deployment wrapper. There is no timer, cron
job, dashboard/Tk composition, or network listener. Service installation and
activation require separate operator approval and parked acceptance.

### Staged supervision contract (NOT active)

- Standalone `meshcore_traffic_worker_main.py --loop`, 10-second polling,
  25 messages per bounded pass; the existing ledger's nonblocking `flock`
  prevents a second consumer using the same database.
- The worker authenticates **only** with `rolling-thunder.token` and retains
  the SCOUT cursor, without ever acquiring the MeshCore USB port.
- `After=meshcore-collector.service` orders startup if both are started;
  the worker does not require or restart the collector. Broker outage uses
  the existing bounded exponential retry (up to 120 seconds).
- `Restart=on-failure`, 10-second retry, 5 starts per 300 seconds, clean
  SIGTERM/20-second stop timeout. Persistent fatal SQLite errors are **not**
  retried indefinitely by the Python loop and may trigger the systemd start
  limit; operator review is required before recovery.
- `MemoryMax=128M`, `CPUQuota=15%`, `TasksMax=24`, `IOWeight=50`,
  `UMask=0077`, `ProtectSystem=strict`, `ProtectHome=read-only`,
  `NoNewPrivileges=yes` and a writable exception limited to the existing
  owner-private MeshCore data directory. No additional listeners.
- `journalctl --user -u meshcore-traffic-worker.service` reports startup,
  broker-retry/fatal errors and redacted count-only progress after each
  nonempty cycle or five minutes of inactivity. It does not emit payloads,
  credential contents or message text. No new health HTTP endpoint.
- Poll and batch parameters are configurable by operator-reviewed systemd
  unit/drop-in changes; do not edit production source. Service is analysis-only,
  and will never issue notifications, route changes, geocoding or RF commands.

### Parked activation checklist (approval required)

1. Verify exact source/production SHA, parked state, `systemctl --user status`
   for the dashboard and collector, broker status, GPS freshness and FT8 health.
   A stopped dashboard is a blocker to *claiming* dashboard regression success;
   do not silently start it.
2. Preserve a consistent SQLite backup of the broker and traffic ledger using
   SQLite's online backup API; record SHA, file permissions, cursor positions,
   schema versions, `PRAGMA integrity_check`, and owner-only credentials **without
   printing any tokens or private messages**. Do not move or overwrite files.
3. Verify the dedicated worker isn't already running; verify user manager,
   installed service paths, data-directory mode 0700, credential file mode 0600
   and the exact authenticated existing Rolling Thunder public cursor.
4. Only after separate explicit approval, install the reviewed template to
   `%h/.config/systemd/user/meshcore-traffic-worker.service` with mode 0600,
   run `systemctl --user daemon-reload`, and explicitly enable/start this **one**
   unit. A source deployment does not perform those actions.
5. Monitor the service journal/status, broker socket and collector status,
   ledger receipts, cursor isolation, resource usage and bounded retry. Verify
   real ACK only after commit, replay after a controlled isolated interruption,
   and no FT8, GPS or dashboard degradation during a representative drive.
6. Commit required QTH infrastructure change records before completion.

**Rollback:** with separate authorization stop/disable only
`meshcore-traffic-worker.service` and check it is inactive, preserving broker,
collector, SCOUT cursor, token and every SQLite file. Restore the saved user
unit/drop-in configuration (if one existed), daemon-reload, and confirm both
collector and dashboard behavior independently. If source rollback is needed,
use the restricted exact-SHA wrapper after parked owner approval; NEVER restore
older broker/QSO/traffic ledgers over newer data. Report any unprocessed public
backlog rather than automatically pruning it. Service activation remains an
independent gate from merge and source deployment.

## Test and release gates

Tests cover independent broker+real Unix API end-to-end with a private frame
present, per-consumer ACK isolation, repeated identical traffic text, general
Public ignored, rolling dedupe window, incomplete ACK followed by restart and
idempotent retry, malformed/replayed message fail-closed, capacity stop,
0600/0700 permission checks and restart durability. Run full `ruff check .`,
`mypy src/rolling_thunder`, `pytest`, `git diff --check`, and GitHub CI on
the exact branch. Hardware receive and private-message acceptance remain
unverified until real #traffic/DM frames arrive. This slice never creates
an on-air test.

## Rollback and change history

No production process, configuration, job or schema changes are authorized
by this service-template source merge alone. To undo a later approved source deployment use the
exact prior installed SHA through the restricted deployment wrapper. To
disable a future independent worker, stop its dedicated process **without**
stopping the existing collector, preserve its ledger and token credentials,
and confirm Rolling Thunder, FT8 and the MeshCore passive/broker APIs remain
healthy. Never replace existing contact/broker databases to undo this feature.

- 2026-11-11: accepted architecture for a no-RF, background, separate durable
  traffic consumer; built isolated ledger, exact-slot incident classification,
  duplicate suppression, commit-before-ACK worker and separately gated CLI
  with hardware-free regression coverage.

- 2026-11-11: staged independent, bounded systemd user-service template and
  redacted periodic count-only health logs; offline regression and service
  contract tests. No unit installed, started, or enabled in production.
