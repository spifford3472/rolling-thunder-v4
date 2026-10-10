# Forge PSK Reporter normalized history — schema v5 (PSK-N2)

Scope: additive normalized reception and QSO-association storage. **Not approved for production deployment or raw-data deletion.** The PSK Reporter collector, global ten-minute pacing and HTTP 403/429 provider block are unchanged. No new provider requests are made by normalization.

## New tables

- `psk_reception`: stable fingerprint of source facts plus an occurrence index to retain repeated identical records within one query. One row per distinguishable reception, plus explicit duplicate occurrences where source fields collide. Original locator and quality flags are retained; missing/malformed grids never get invented coordinates.
- `psk_qso_reception`: the contact-to-reception many-to-many relationship. One reception can be associated with multiple contacts.
- `psk_normalization_audit`: per-contact reconciliation of matched-report counts and source SHA-256, including normalization version.
- `psk_query_normalization_audit`: independent full-provider query reconciliation, parsed/skipped counts and SHA-256. Unlinked observations are persisted even when no QSO can be identified.

These tables coexist with `pskreporter_query` (original XML + request metadata) and `qso_pskreporter_summary` (matched JSON + existing derived statistics). Existing clients remain unchanged.

## Backfill

First take a **consistent SQLite backup** with the SQLite backup API, and verify it separately. Run from the feature revision on a copied history database, not production, until PR approval:

```bash
python -m rolling_thunder.forge_psk_normalized_history --database /path/to/history.sqlite3 --backfill
python -m rolling_thunder.forge_psk_normalized_history --database /path/to/history.sqlite3 --backfill --apply
python -m rolling_thunder.forge_psk_normalized_history --database /path/to/history.sqlite3 --retention-preview
```

The dry-run does not modify the database. Backfill processes **all** provider XML receptions and preserves those unrelated to QSO matches. Query-to-QSO matches remain separate. For schema-v4 databases, normal repository initialization upgrades to v5 additively. The `--apply` mode inserts normalized rows but does not delete raw data or query providers. Repeat applying must not double-count. Reconcile the audit's counts against original per-QSO matched reports.

## Retention selection: **90 days**, disabled on production

The 90-day preview enumerates candidate XML older than the threshold; no background deletion job is scheduled. A separate operator-only `--prune-raw --apply` command is implemented, **NOT enabled or approved for production**. It requires an independent *existing* SQLite backup of the source containing byte-identical original XML, valid SQLite integrity check, full per-query normalization and reconciliation audit, zero skipped provider records, and verified QSO audit completeness. An audit failure aborts the entire transaction.

After a future production acceptance and **separate cleanup authorization**, the operator can run on a vetted database copy:

```bash
python -m rolling_thunder.forge_psk_normalized_history --database /path/to/history.sqlite3 --retention-preview
python -m rolling_thunder.forge_psk_normalized_history --database /path/to/history.sqlite3 --prune-raw --apply --backup-evidence /path/to/independent-sqlite-backup.sqlite3
```

**Do not run prune against production until separately approved.** The command clears provider `raw_xml` only; redundant matched-report JSON remains for backwards-compatible readers. Query records, hashes, observation rows, associations, and summaries are retained permanently. For a response with malformed/skipped records, pruning is blocked until a separately reviewed lossless quarantine design exists. No live PSK Reporter network retrieval is performed by either command.

## Rollback

Rollback the application package to the previous exact SHA. Additive schema v4/v5 tables remain dormant; do **not** downgrade or delete them automatically. Existing Wavelog, contact-sync, FT8 and offline feeder processes must remain untouched.

## CP2.4 read-only consumer

The newer CP2.4 outbound evidence reader and coverage audit use the same
`psk_reception` table in the schema-v5 PSK history database; they do not imply
an additional database or a second PSK Reporter provider. Existing PSK-N2
rollout evidence should be reused. The only additional acceptance gate is
current read-only table availability, outbound sample freshness, correct
receiver-grid/direction matching, and the evidence API's fail-neutral behavior.
This section does not authorize migrations, backfill, pruning or deployment.
