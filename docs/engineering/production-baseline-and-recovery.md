# Production baseline and recovery inventory

## Purpose and evidence rule

This document is the R0-01 inventory for issue #340. It separates verified
production observations from repository state and from unverified assumptions.
An installed identity is never inferred from a development checkout, package
version, backup archive, or GitHub `main`.

The last complete host inventory below was collected on 2026-10-16 through
authorized metadata-only inspection. Restricted checks on 2026-10-21 and a
reviewed read-only resumption on 2026-10-22 confirmed current service/timer
state and the installed C6 release, but could not read the Pi checkout identity,
direct-install Forge provenance, or protected backup/database contents. Therefore
this inventory is suitable recovery context but does **not** clear a new
deployment identity/recovery gate without the remaining minimum helper output.

## Repository baseline

On 2026-10-22 the live GitHub `main` ref and the fresh isolated resumption
workspace both resolved to:

```text
d7a3b574dc53d213764eff341ad77ae976df57e1
```

The resumption branch was `engineering/resume-340-345-353-20261022` and clean at
that source before mission changes. Repository identity does not establish either
host's running version.

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

The 2026-10-22 restricted check reconfirmed `rolling-thunder.service`
active/running/enabled with PID 335866, start time 2026-10-20 18:30:05 EDT,
working directory `/home/geoff/projects/rolling-thunder-v4`, and the expected unit
path. The snapshot timer last triggered 2026-10-22 01:30 EDT and the delivery
timer last triggered 05:05:01 EDT; both remain active/waiting. The restricted
account was denied traversal of the production checkout, so current HEAD,
detached/branch state and cleanliness remain unverified. It also lacks journal
access, so #345 timing/error evidence remains unavailable without a helper.

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

The 2026-10-22 reviewed Forge check adds current evidence:

- contact sync remains active/running from 2026-10-21 20:04:04 EDT;
- C6 `current` resolves to immutable repository commit
  `858e95e59b131193d92ffefadf7134ab043d8f20` (merge PR #328);
- the C6 service ran at 2026-10-22 02:10:05 EDT and exited 0, while its timer
  remains active/waiting for 08:10 EDT;
- NOAA refresh last triggered 02:00:01 EDT and remains scheduled for 08:00 EDT;
- the C6 service identity is `rolling-thunder-propagation`, with the known config
  and protected database paths; the database remains unreadable to `geoff`;
- PSK Reporter still resolves to `e09903b5fe06bd5ca350f80648acf45d5d7011c6`,
  and the PSK evidence unit still executes immutable release `47c7421b...`; and
- callsign-info, contact-sync, spots, propagation, propagation-QSO, PSK evidence,
  and PSK Reporter services were active. Direct installs and the propagation
  release links remain unverified where current permissions do not expose their
  immutable source identity.

These facts establish service and C6 release identity only. They do not establish
C6 database integrity/coverage, current direct-install source provenance, or a
safe deployment baseline.

## Backup and representative restore evidence

The 2026-10-16 R0-02 AnvilVault/PBS snapshot was independently restored to
temporary paths. The Pi database and all 11 Forge SQLite databases passed
SQLite integrity checks. Both archives and all 14 manifest-covered files
matched their recorded hashes and sizes. This is representative restore
evidence and establishes the recovery method without overwriting production.

On 2026-10-22 the Pi snapshot/delivery timers remained current. Forge
`rolling-thunder-r02-forge-backup.service` ran from 02:00:01 to 02:00:05 EDT and
exited successfully; `r02-forge-forward.service` ran from 05:10:04 to 05:10:06
EDT and exited successfully. The protected R0-02 directory still prevents this
account from validating the fresh manifest, hashes, SQLite checks or coverage.

The separate user `forge-radio-config-backup.service` failed on 2026-10-19 while
copying a permission-restricted `hamtools/dmrfill/dmrfill` path. Its earlier
ham-application archive phase reported completion, but the later radio/Node-RED
backup did not complete. This is a real gap for that separate recovery asset; it
does not prove R0-02 failure and was neither repaired nor restarted under #340.

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

The exact minimum authorized helper/read output still needed is:

1. Pi helper output containing only current checkout SHA, branch/detached state,
   cleanliness, effective service entrypoint, and a reliable operator-use state;
   no journal payload or configuration contents are required for #340.
2. Forge deployment-state/helper output mapping callsign-info, contact-sync,
   spots and unreadable release links to exact pushed commits where recorded;
   an absent mapping should be reported as an irreducible provenance gap.
3. Latest Pi and Forge R0-02 manifest timestamp, covered asset count/identities,
   archive hash result, SQLite integrity/foreign-key summary, forward result, and
   confirmation that the independently restored 2026-10-16 recovery point is
   retained. Raw archives, databases and secrets are not required.
4. Separate radio-config backup follow-up only if the owner wants that recovery
   asset repaired; #340 needs only the failure disposition above and does not
   authorize a restart, permission change or unrelated repair.

No production restart or deployment is needed solely to finish this inventory.
