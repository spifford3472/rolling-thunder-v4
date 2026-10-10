# Checkpoint A owner acceptance and rollback

> Historical checkpoint note: this runbook records Checkpoint A's scope. Checkpoints
> B–E are now implemented in current code. Current Wavelog routing,
> station/logbook management, and ADIF `NOTES` behavior are defined by
> [Forge Contact Synchronization](FORGE_CONTACT_SYNC.md); the legacy-only
> expectations below are not current acceptance criteria.

Status: prepared procedure; not executed. Cloud does not deploy or merge.
Wait for green Continuous Integration / Python quality checks on the exact PR SHA.
Keep the PR draft until installed owner acceptance and explicit approval.
Baseline: `4e416e6af7a3e354f627e77af43ce11ad58b9086`.
Branch: `feature/mobile-qso-immutable-location`.

## Stage A: preserve production before any migration

Run only this first block on anvilmobile, then review its output before proceeding.
It records HEAD/service unit, backs up local YAML without printing contents and
uses SQLite's backup API (including live WAL data). Contact-only JSON is not a
complete rollback database. This block does not migrate or stop production.

```bash
cd /home/geoff/projects/rolling-thunder-v4
umask 077
checkpoint_backup="$HOME/rolling-thunder-checkpoint-a-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$checkpoint_backup"
git rev-parse HEAD | tee "$checkpoint_backup/production-head.txt"
git status --short --branch
systemctl cat rolling-thunder.service > "$checkpoint_backup/rolling-thunder.service.txt"
python3 - "$checkpoint_backup" <<'PY'
import pathlib
import shutil
import sqlite3
import sys
root = pathlib.Path('/home/geoff/projects/rolling-thunder-v4')
backup = pathlib.Path(sys.argv[1])
source = root / 'config/data/rolling-thunder.db'
with sqlite3.connect(f'{source.as_uri()}?mode=ro', uri=True) as live:
    with sqlite3.connect(backup / 'rolling-thunder-schema15.db') as saved:
        live.backup(saved)
        version = saved.execute('SELECT schema_version FROM schema_metadata WHERE singleton_id=1').fetchone()[0]
        assert version == 15, f'Unexpected schema {version}; stop and reconcile'
        assert saved.execute('PRAGMA integrity_check').fetchone() == ('ok',)
        assert saved.execute('PRAGMA foreign_key_check').fetchall() == []
        print('Backup schema:', version)
        print('Contacts:', saved.execute('SELECT COUNT(*) FROM contacts').fetchone()[0])
        print('States:', saved.execute('SELECT synchronization_state, COUNT(*) FROM contacts GROUP BY synchronization_state').fetchall())
for path in (root / 'config').rglob('*'):
    if path.is_file() and path.suffix.lower() in {'.yaml', '.yml'}:
        target = backup / path.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
print('Verified backup:', backup)
PY
```

If HEAD differs from the baseline, stop and reconcile approved changes. Preserve
this backup location and verify free space/ownership before continuing.

## Stage B: isolated exact-commit validation

Provide the next terminal block only after Stage A output is reviewed.
Owner fetches the feature branch into a separate worktree, verifies its HEAD equals
the reviewed PR SHA, and creates a separate development venv there. Do not switch
the editable production checkout yet; do not copy example YAML over local config.
Run the contact/location/controller/FT8 authorization/logging/HTTP/Forge API,
backup/import/export/storage/retry/sync tests and quality gates from that worktree.

Make a working copy of the **closed verified Stage A backup**, never raw-copy the
live database. Before migration record every old contact column/row (including
created_at/updated_at), retry rows and FT8 performance rows. Initialize only the
copy with the worktree's storage.initialize_database. Verify schema 16, identical
old rows/counts/states/timestamps, NULL coordinate pairs on all historical rows,
unchanged retry/performance rows, clean foreign_key_check and integrity_check.
Repeat initialization to prove normal versioning makes it a no-op.

## Stage C: installed contract and controlled application acceptance

Each production-changing step requires a separately reviewed owner terminal block.
Before updating the Pi sender, owner records Forge source HEAD, installed version,
and actual import paths using
`/opt/rolling-thunder-forge-contact-sync/.venv/bin/python` for `rolling_thunder`,
`rolling_thunder.domain`, and `rolling_thunder.forge_contact_sync_api`. Inspect the
actual Contact.model_fields for both coordinate names. Preserve the Forge unit,
configuration/environment privately and take a SQLite-safe ledger backup.
Install the reviewed shared package into the **contact-sync private venv** first,
verify the actual imports/model fields, then perform owner-controlled contact-sync
restart and health check. Do not change routing/configuration/ledger schema or the
independent spot/weather service. A version string alone is insufficient proof.

Owner then stops the Pi service, records stop status, makes a final SQLite-safe
schema-15 backup capturing contacts since Stage A, and installs the exact reviewed
Pi code while preserving local YAML. Owner starts the service and verifies schema
16, historical data/states and service health. Do not send synthetic/fabricated
QSOs to production Wavelog or transmit merely to test columns.

Use deterministic tests and the copied database first to demonstrate ordinary
fixed-GPS capture, no-fix logging, post-capture movement, next-contact freshness,
FT8 frozen coordinates, unsuccessful outcomes and immediate sync notification.
For installed end-to-end proof, use only an owner-approved legitimate contact/QSO.
Inspect its local UUID/my_grid/my_latitude/my_longitude, move/change current GPS
safely, and inspect the same row again. A subsequent approved contact may capture
a different position. Confirm the row synchronizes through the installed Forge
package; the historical Checkpoint A expectation was exactly one QSO in legacy
Mobile / KI5VNB Main, no new station, existing grid PATCH behavior and no new
comment rule. Repeated manual
sync/retry/restart must not duplicate that QSO. Verify FT8 immediate sync and
friend, Browse/POTA/DX/DMR behavior. Record exact SHAs and results before approval.

## Rollback

Schema-15 code refuses schema 16. There is no downgrade migration. Stop the Pi
service before rollback. Restore the recorded application commit, matching local
configuration and the final pre-migration SQLite-safe backup as one coordinated
rollback. Preserve the schema-16 database (including WAL state via SQLite backup)
before replacement; archive any contacts logged since migration for later reviewed
recovery, since restoring an older backup loses those local additions. Ensure no
process holds the database open and handle obsolete WAL/SHM sidecars under the
reviewed restoration procedure; do not place an old main database beside stale WAL.
Verify ownership, integrity, supported schema and historical counts before restart.
Keep the current Forge ledger whenever possible to prevent duplicate Wavelog writes.
If rolling Forge back too, roll back the Pi sender first: old Forge rejects expanded
Contact payloads. Never delete/recreate the ledger or improvise a schema downgrade.

At this historical checkpoint, later state/CQ/ITU derivation, dynamic station
selection/creation, and the blank-only ADIF `NOTES=Mobile QSO` rule were outside
scope. They are implemented by the current Checkpoints B–E code and documented in
`FORGE_CONTACT_SYNC.md`.
