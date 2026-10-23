# Production baseline and recovery inventory

## Final R0-01 disposition — evidence collected 2026-10-22

Issue #340's read-only inventory is complete with the provenance limitations below
explicitly recorded. This is a dated observation, not a claim that production
still matches it indefinitely or that another issue is deployed or accepted.
Historical overnight handoffs are superseded by this inventory for #340.

No production restart, deployment, restore, database/configuration modification,
permission change, provider request or radio action was required. The owner
performed one fixed-scope administrator read; no permanent privileged access was
installed. Missing Git provenance remains an affected-component deployment gate.

## Source baseline and evidence boundaries

The isolated mission source began at GitHub main
`d7a3b574dc53d213764eff341ad77ae976df57e1`; main was independently checked
after PR #356 at `5572872dee7ddd937ad5ff959714fdb603092908`. Neither development
source nor GitHub main establishes production identity. Installed metadata,
service entrypoints, checkout identity and backup evidence are recorded separately.

The final owner-run report was read from
`/home/geoff/r0340-protected-evidence.json`, timestamp Oct 22 20:04:45 EDT,
owned by geoff, mode 0600. Its SHA-256 is
`187dfbc08a767f3b58bfc8005a2169291c760b5630e31f17701e6b5145522f0a`.
Report source is private infrastructure PR #4, pinned commit
`928501ee4f9e9d3f7e874f9951d6b85fc07451de`;
script SHA-256 is
`96d9593478094932b765eaf4ea28fb74836a9e9d4120da225abd93171cacd2c8`.
No credentials, configuration contents or QSO rows are included in this inventory.

## anvilmobile production identity

Owner-authorized read-only inspection on Oct 22 10:17–10:20 EDT established:

| Asset | Observed identity |
|---|---|
| Main unit | `rolling-thunder.service`, active/running/enabled |
| Process | PID 335866, started Oct 20 18:30:05 EDT |
| Entrypoint | `/usr/bin/bash /home/geoff/projects/rolling-thunder-v4/deploy/rolling-thunder-autostart` |
| Checkout | `/home/geoff/projects/rolling-thunder-v4`, clean detached HEAD |
| Checkout commit | `1f2f7c5c739757bd2e5746aa10597b8b9440bf27`, GitHub merge #354 |
| Process association | Unit WorkingDirectory and process cwd match checkout; executable `/usr/bin/python3.13` |
| Runtime config | `config/rolling-thunder.yaml`; `config/antenna-reference.yaml` |
| Durable database | `config/data/rolling-thunder.db` |
| Backup timers | `r02-pi-snapshot.timer`; `r02-pi-deliver.timer`, active/waiting |

This is checkout/entrypoint association, not proof every loaded Python byte equals
the current disk after any in-place changes since process start. No restart was
performed to resolve that deployment-acceptance distinction. Operator-use state
remains unknown: establish it before any Pi restart or deployment.

FT8 evidence/period secret-environment files were root-owned mode 0600; completed
QSO delivery metadata was root:geoff mode 0640 in the Oct 16 inventory. Contents
were not read. Current configuration must be preserved privately before changes.

## Forge production identities

| Component | Evidence and identity |
|---|---|
| Callsign information | Oct 22 administrator report: `rolling-thunder==4.4.0`, local/archive origin; root `/opt/rolling-thunder-forge-callsign-info` |
| Contact sync | Oct 22 administrator report: `rolling-thunder==4.4.1`, local/archive origin; root `/opt/rolling-thunder-forge-contact-sync` |
| Spots/weather/radar | Oct 22 clean detached editable checkout `/opt/rolling-thunder-forge` at `28f798ada0f81e2638797f3a56ebc7c172bb4ea4` |
| Propagation collector | Last directly verified Oct 16 immutable release `fb9efe09314a07d4fe1dc08cb25bdeffd6213038` |
| Propagation QSO worker | Last directly verified Oct 16 immutable release `24762a12580e5827db8b616539be37981cbcdb54` |
| PSK Reporter | Oct 22 release `e09903b5fe06bd5ca350f80648acf45d5d7011c6` |
| PSK evidence listener | Oct 22 unit executes release `47c7421b8fde560258643328b6c7ed7de1cc1b18` |
| VOACAP C6 baseline | Oct 22 current release `858e95e59b131193d92ffefadf7134ab043d8f20` (merge #328) |

Callsign, contact-sync, spots, propagation, propagation-QSO, PSK Reporter and PSK
evidence services were active in the Oct 22 inspection. Contact sync had been
running since Oct 21 20:04:04 EDT. The C6 timer was active; the Oct 22 02:10:05
EDT service exited 0. NOAA refresh was scheduled. These are service observations,
not proof of C6 forecast freshness, slot coverage or #353 operational acceptance.
Propagation collector/QSO release identities above retain their Oct 16 evidence
date; their current link targets were not independently reverified on Oct 22.

State roots include `/var/lib/rolling-thunder-forge-callsign-info`,
`/var/lib/rolling-thunder`, `/var/lib/rolling-thunder-forge-propagation`,
`/var/lib/rolling-thunder-forge-propagation-qso`, and
`/var/lib/rolling-thunder-forge-pskreporter`. The C6 database is
`/var/lib/rolling-thunder-forge-propagation/c6-predicted-ssn-baseline-20261013.sqlite3`.
Observed Forge YAML metadata was root/service-group mode 0640; service-separated
state roots were mode 0750. Configuration contents are excluded.

### Direct-install provenance limitation and recovery disposition

The fixed metadata/marker checks returned no VCS commit for callsign-info or
contact-sync. This is a bounded inspection, not proof no deployment record exists
elsewhere. Version numbers and fingerprints must never be relabelled Git SHAs.

| Installed distribution | Python files | Deterministic source-tree SHA-256 |
|---|---:|---|
| Callsign-info 4.4.0 | 275 | `3c1a57e385abc5c7dca09d42eb13ec72aeded0dc4c6f872f0bde38d1c4cf2827` |
| Contact-sync 4.4.1 | 341 | `d668fb4b3681e353302e9380a4f382e1ff61cc2dfe93f2694efd4720b0713b75` |

These fingerprints identify the inspected Python sources only; they are not
complete recoverable package artifacts. Before replacing either install, preserve
the existing installation/environment, unit/configuration and consistent data,
verify the preserved rollback artifact against this identity, and record the new
immutable release commit. If that cannot be done through an approved deployment
path, stop that deployment. Do not rebuild an assumed old commit from the version.
No source-history certainty is manufactured merely to close an inventory.

## Backup and representative restore evidence

### Pi snapshot and delivery

The actual root is `/mnt/rolling-thunder-data/backups/rolling-thunder`.
Snapshot `20261022T053001Z` uses SQLite online backup. Independent reads verified
database and both configuration-file sizes/SHA-256 without printing configuration;
query-only integrity was OK and foreign-key violations were zero. The
`20261016T053004Z` snapshot manifest remained present.

The Oct 22 10:05:51 EDT delivery journal confirmed the latest copy hash-verified
on Forge. Its inbox archive
`/srv/backups/rolling-thunder-mobile-inbox/20261022T053001Z.tar.gz`
was independently hashed:
`3b5eab6f0dc7f9b2b45cf64d8a7df24c5abb444210c212c17cd47dfec32fdfc8`.
This matches the forwarding job's Oct 22 01:40:06 EDT
`R02_ANVILVAULT_VERIFIED` record. The Oct 16 Pi inbox archive was retained.

### Forge protected snapshot

The administrator report independently read existing snapshot
`/var/backups/rolling-thunder/r02/20261022T060001Z`.
Manifest status was complete, method `sqlite3.Connection.backup`.
All eleven declared assets matched their manifest sizes and SHA-256, passed
SQLite integrity, and had zero foreign-key violations:

- `contact-sync/forge-contact-sync.db`
- `contact-sync/forge-contact-sync-contact-snapshots.db`
- `spots/forge-spots.db`
- `callsign/known-callsigns.sqlite3`
- `propagation/c4-baseline.sqlite3`
- `propagation/c6-predicted-ssn-baseline-20261013.sqlite3`
- `propagation/propagation-history.sqlite3`
- `propagation-qso/ingestion.sqlite3`
- `propagation-qso/history.sqlite3`
- `pskreporter/orchestration.sqlite3`
- `pskreporter/history.sqlite3`

The Oct 16 Forge snapshot directory was retained. Backup copies were opened with
read-only immutable SQLite and query-only checks; no live databases were opened
by the report and no sidecars or new backups were created.

Reviewed root-owned snapshot/forward scripts use SQLite backup and compare local
and destination hashes. The Oct 22 job journal records all eleven integrity PASS
results, snapshot completion and off-host archive verification:
`0b5ce569820c5fe6405be7f9f70fc0d909e289d133f4813f48fb56c83e9b841b`.
Off-host verification is evidence from that job/journal, not a new independent
destination read. The administrator report checked local snapshot files only.

### Restore scope and separate failed asset

The Oct 16 R0-02 AnvilVault/PBS snapshot was previously restored into isolated
temporary paths: Pi plus all eleven Forge SQLite integrity checks passed, both
archives and all fourteen manifest-covered assets matched hashes/sizes. This
remains representative restore evidence. No new full restore of Oct 22 is claimed,
and local retention checks do not independently establish current PBS retention.

The separate user `forge-radio-config-backup.service` failed Oct 19 while
copying permission-restricted `hamtools/dmrfill/dmrfill`. Its radio/Node-RED
backup phase did not complete. That separate asset requires a focused repair;
it does not invalidate the independently checked R0-02 snapshot. It was not
repaired or restarted under this read-only inventory.

## Recovery rules and remaining deployment gates

1. Use SQLite backup or consistent snapshots; never copy active databases casually.
2. Restore to isolated paths and check integrity/foreign keys before recovery.
3. Never overwrite newer contacts, telemetry, forecasts or synchronization ledgers
   with old databases. Preserve new records and reconcile forward.
4. Preserve code, environment, unit/configuration and durable data as distinct assets.
5. Recheck dated production identity and fresh recovery readiness for the component
   being deployed; resolve its source-provenance/rollback limitation first.
6. Establish safe operator-use state before Pi changes. Use only approved deployment
   paths and separately verify feature-specific acceptance such as C6 coverage.

The read-only inventory and its gaps are evidenced, satisfying #340's inventory
criterion. #345, #353, #357 and #359 retain their own implementation, deployment
and acceptance status; this inventory does not clear those gates automatically.
