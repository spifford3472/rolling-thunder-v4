# Forge PSK Reporter normalized history — schema v4

Scope: additive normalized reception and QSO-association storage. **Not approved for production deployment or raw-data deletion.** The PSK Reporter collector, global ten-minute pacing and HTTP 403/429 provider block are unchanged. No new provider requests are made by normalization.

## New tables

- `psk_reception`: stable fingerprint of source facts plus an occurrence index to retain repeated identical records within one query. One row per distinguishable reception, plus explicit duplicate occurrences where source fields collide. Original locator and quality flags are retained; missing/malformed grids never get invented coordinates.
- `psk_qso_reception`: the contact-to-reception many-to-many relationship. One reception can be associated with multiple contacts.
- `psk_normalization_audit`: per-contact reconciliation of matched-report counts and source SHA-256, including normalization version.

These tables coexist with `pskreporter_query` (original XML + request metadata) and `qso_pskreporter_summary` (matched JSON + existing derived statistics). Existing clients remain unchanged.

## Backfill

First take a **consistent SQLite backup** with the SQLite backup API, and verify it separately. Run from the feature revision on a copied history database, not production, until PR approval:

```bash
python -m rolling_thunder.forge_psk_normalized_history --database /path/to/history.sqlite3 --backfill
python -m rolling_thunder.forge_psk_normalized_history --database /path/to/history.sqlite3 --backfill --apply
python -m rolling_thunder.forge_psk_normalized_history --database /path/to/history.sqlite3 --retention-preview
```

The dry-run does not modify the database. The `--apply` mode inserts normalized rows but does not delete raw data or query providers. Repeat applying must not double-count. Reconcile the audit's counts against original per-QSO matched reports.

## Retention selection: **90 days**

Retention is a policy decision, **not an activated deletion operation**. The preview lists raw provider XML older than 90 days. All XML and matched JSON remain stored until a separate guarded cleanup implementation/review.

Future cleanup implementation must require explicit operator authorization, normalized/audit reconciliation for every affected query, verified backups, a grace period, and an independent dry-run. It must preserve query row IDs, query parameters, fingerprints, normalized receptions, associations, and summaries. An empty provider reply counts as success with zero reports; a failed reply must never be interpreted as zero reception.

## Rollback

Rollback the application package to the previous exact SHA. Additive schema v4 tables remain dormant; do **not** downgrade or delete them automatically. Existing Wavelog, contact-sync, FT8 and offline feeder processes must remain untouched.
