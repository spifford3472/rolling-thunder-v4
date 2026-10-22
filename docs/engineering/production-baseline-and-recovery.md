# Production baseline and recovery inventory

## Purpose and evidence rule

This document is the R0-01 inventory for issue #340. It separates verified
production observations from repository state and from unverified assumptions.
An installed identity is never inferred from a development checkout, package
version, backup archive, or GitHub `main`.

The last complete host inventory below was collected on 2026-10-16 through
authorized metadata-only inspection. A 2026-10-21 restricted-agent preflight
confirmed service availability and timer activity but could not re-read the
installed source identities or protected backup/database contents. Therefore
this inventory is suitable recovery context but does **not** clear a new
deployment identity/recovery gate without a fresh authorized check.

## Repository baseline

On 2026-10-21 the live GitHub `main` ref and the isolated overnight workspace
both resolved to:

```text
d7a3b574dc53d213764eff341ad77ae976df57e1
```

The workspace branch was `engineering/overnight-340-345-353` and clean before
mission changes. Repository identity does not establish either host's running
version.

## anvilmobile inventory

| Asset | Last verified production evidence |
|---|---|
| Main unit | `rolling-thunder.service`, installed under `/etc/systemd/system/` |
| Entrypoint | `/usr/bin/bash /home/geoff/projects/rolling-thunder-v4/deploy/rolling-thunder-autostart` |
| Working/source path | `/home/geoff/projects/rolling-thunder-v4` |
| Source identity (2026-10-16) | clean detached HEAD `0c79f2a7eebea23bf586ac218be3bb4e3ab8dd9f` |
| Runtime config | `config/rolling-thunder.yaml`; `config/antenna-reference.yaml` |
| Primary durable database | `config/data/rolling-thunder.db` |
| Secret environment metadata | FT8 evidence/period files mode `0600` root-owned; completed-QSO delivery file mode `0640` root:`geoff`; contents not inventoried |
| Backup timers | `r02-pi-snapshot.timer`; `r02-pi-deliver.timer` |

The 2026-10-21 restricted health preflight reported the main service active and
enabled and both backup timers scheduled. It did not expose the current checkout
SHA or a fresh backup manifest. A Pi restart or deployment remains prohibited
until installed identity, backup readiness, and operating state are positively
verified through approved interfaces.

## Forge inventory

| Component | Runtime/state identity last verified 2026-10-16 |
|---|---|
| Callsign information | direct install `rolling-thunder==4.4.0`; temporary build-source URL did not identify an immutable commit; state `/var/lib/rolling-thunder-forge-callsign-info` |
| Contact sync | direct install `rolling-thunder==4.4.0`; temporary build-source URL did not identify an immutable commit; durable state under `/var/lib/rolling-thunder` |
| Spots/weather/radar | direct editable source `file:///opt/rolling-thunder-forge`; database `/var/lib/rolling-thunder/forge-spots.db` |
| Propagation collector | immutable release `fb9efe09314a07d4fe1dc08cb25bdeffd6213038`; state `/var/lib/rolling-thunder-forge-propagation` |
| Propagation QSO worker | immutable release `24762a12580e5827db8b616539be37981cbcdb54`; state `/var/lib/rolling-thunder-forge-propagation-qso` |
| PSK Reporter | immutable release `e09903b5fe06bd5ca350f80648acf45d5d7011c6`; state `/var/lib/rolling-thunder-forge-pskreporter` |
| PSK evidence listener | immutable release `47c7421b8fde560258643328b6c7ed7de1cc1b18` |
| VOACAP C6 baseline | dedicated timer/service; protected database `/var/lib/rolling-thunder-forge-propagation/c6-predicted-ssn-baseline-20261013.sqlite3` |

The immutable release identifiers above were reconciled to valid repository
commits. The three direct installs retain an explicit provenance limitation:
package metadata alone is insufficient to recover their exact source commit.
Do not infer one from version `4.4.0` or a nearby deployment.

Active Forge YAML files observed in 2026 were root-owned, service-group-readable
mode `0640`; contents and credentials are deliberately excluded here. Durable
state roots were service-separated mode `0750`. Current configuration contents
must be backed up without being printed or committed.

The 2026-10-21 restricted preflight confirmed contact sync active, the R0-02
forward result successful, and the VOACAP timer active with its last service
exit successful. It could not inspect the protected C6 database, journal, or
backup contents. A successful oneshot exit does not prove forecast persistence.

## Backup and representative restore evidence

The 2026-10-16 R0-02 AnvilVault/PBS snapshot was independently restored to
temporary paths. The Pi database and all 11 Forge SQLite databases passed
SQLite integrity checks. Both archives and all 14 manifest-covered files
matched their recorded hashes and sizes. This is representative restore
evidence and establishes the recovery method without overwriting production.

On 2026-10-21 the Pi snapshot/delivery timers and Forge forward result were
recent and successful, but the restricted account could not inspect the
root-only R0-02 directory or validate a fresh manifest. The failed unrelated
`forge-radio-config-backup.service` must be investigated independently; it does
not by itself prove R0-02 failure, but it may affect recovery for radio/Node-RED
configuration outside Rolling Thunder's manifest.

Recovery rules:

1. Use SQLite backup semantics or a consistent snapshot, never an uncoordinated
   live database copy.
2. Restore into isolated temporary paths and run integrity/foreign-key checks
   before considering production recovery.
3. Never restore an old database over newer contacts, telemetry, forecasts, or
   synchronization ledgers.
4. Preserve new records and reconcile forward when rollback code is compatible
   with the current schema.
5. Keep secrets/configuration, code releases, unit files, and durable data as
   separate recovery assets.

## Open gates and exact next action

R0-01 remains `IN_PROGRESS`, not `DONE`, because the current Pi checkout SHA,
the current Forge direct-install source identities, and a fresh protected backup
manifest were not available through this runner's approved read-only interface.
Production deployment is blocked by that uncertainty.

The next authorized metadata-only check must provide:

1. Pi `rolling-thunder.service` effective entrypoint, working directory, current
   checkout SHA/detached state/cleanliness, and reliable operator-use state.
2. Forge component release/current-link targets plus immutable provenance for
   direct installs where available; irreducible gaps remain explicitly recorded.
3. Latest Pi and Forge R0-02 manifest timestamps, coverage, hash/integrity result,
   and retention of the independently restored 2026-10-16 recovery point.
4. Disposition of `forge-radio-config-backup.service` only to determine whether
   a relevant recovery asset is missing; no unrelated repair or restart is
   authorized by #340.

No production restart or deployment is needed solely to finish this inventory.
