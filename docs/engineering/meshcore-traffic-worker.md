# MeshCore durable traffic worker — Issue #395 follow-on

## Current state and authority

This source-only milestone introduces an independently runnable, **disabled by
default** background public-message processor. It has **not** been installed,
started as a service, merged, or deployed by adding the source files. The
running `meshcore-collector.service` is unchanged and remains the sole USB
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

Continuous `--loop --poll-seconds 10` requires separate explicit approval
for user-service activation, resource and soak tests, named unit supervision,
security review and infrastructure documentation. No systemd unit/drop-in,
cron job, timer, dashboard/Tk composition, or network listener is added here.

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
by a source merge alone. To undo a later approved source deployment use the
exact prior installed SHA through the restricted deployment wrapper. To
disable a future independent worker, stop its dedicated process **without**
stopping the existing collector, preserve its ledger and token credentials,
and confirm Rolling Thunder, FT8 and the MeshCore passive/broker APIs remain
healthy. Never replace existing contact/broker databases to undo this feature.

- 2026-11-11: accepted architecture for a no-RF, background, separate durable
  traffic consumer; built isolated ledger, exact-slot incident classification,
  duplicate suppression, commit-before-ACK worker and separately gated CLI
  with hardware-free regression coverage.
