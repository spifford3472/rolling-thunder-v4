# PSK Reporter automatic queue feeder — installation gate

This checkpoint is **not** authorization to deploy or enable anything.

The feeder reads only already-synchronized FT8 contacts with complete snapshots,
joins full terminal attempt data, and queues events into PSK's durable SQLite event
table. It never calls PSK Reporter and never starts the PSK provider worker.
Repeated invocations skip UUIDs already in the queue (including pending,
completed, and expired), so crashes after queue insertion are replay-safe.

## Preconditions for a separately approved activation

1. Deploy exact merged code to the isolated Forge PSK release.
2. Install and start the independent Forge contact-sync snapshot feature from
   PR #249. Its snapshot database is
   `/var/lib/rolling-thunder/forge-contact-sync-contact-snapshots.db`.
3. Confirm PSK's queue DB is initialized at
   `/var/lib/rolling-thunder-forge-pskreporter/orchestration.sqlite3`.
4. Grant the restricted service identity **read-only** filesystem and SQLite
   access to both contact-sync databases and the directory path to each file,
   and **write** access only to the PSK queue directory. Validate with a manual
   one-shot dry run first; do not weaken file permissions globally.
5. Install the supplied service and timer units but keep the timer disabled
   until explicitly authorized. Never enable the PSK provider during this step.
6. Verify queue health, deduplication, and the continuing Wavelog sync service.

The timer runs one bounded batch of 50 every ~minute, *not* a PSK Reporter
query. The provider worker retains its separate ten-minute retrieval gate and
must remain disabled until explicitly approved.

Historical contacts without complete snapshots will not appear automatically;
their backfill requires a separate, verified reconciliation workflow.
