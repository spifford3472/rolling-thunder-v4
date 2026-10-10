# Wavelog upstream-image restoration — full operator checklist (NOT executed)

**Decision, 2026-10-08:** Wavelog upstream rejected the custom ADIF `MY_GRIDSQUARE` override. Its station-location profile is authoritative for a QSO's station grid, downstream maps, awards, distance, and per-location LoTW/eQSL/ClubLog settings. Rolling Thunder must retain its precise six-character local grid but must not assume an imported ADIF field overrides the Wavelog station profile.

**Required target state:** the Wavelog application runs an unmodified official
`ghcr.io/wavelog/wavelog` image pinned by reviewed digest. Rolling Thunder contains
no custom Wavelog patch, installed-version watcher, upgrade latch, upload interlock,
Pi warning, or watcher credential. Contact sync keeps its pre-integration mainline
runtime behavior. The official semantics audit and a future non-creating resolver
proposal are in `docs/WAVELOG_STATION_PROFILE_RESOLVER_DESIGN.md`.

## Read-only inventory verified on Forge, 2026-10-08 12:50 EDT

- Compose project: `wavelog`; compose directory `/home/geoff/docker/wavelog`; configuration file `compose.yml`.
- Services: `wavelog-db`, `wavelog-main`.
- Current application image: `wavelog-local:3.2.3-mygridsquare-3aab86969`; local image ID `sha256:fe85bfaa6c98c714969a42082eb8679e4eb486a03721d0bcd7ecb1a69841ade9`.
- DB image: `mariadb:11.8`; DB volume `wavelog_wavelog-dbdata` mounted at `/var/lib/mysql`.
- Application volumes: `wavelog_wavelog-uploads` at `/var/www/html/uploads`; `wavelog_wavelog-userdata` at `/var/www/html/userdata`; `wavelog_wavelog-config` at `/var/www/html/application/config/docker`.
- Forge contact-sync service was active; propagation collector inactive.
- **No Docker, Compose, database, production file, or contact-sync changes were made.**

## Approval gates before changing production

1. Obtain explicit owner authorization for this separate Wavelog/Compose maintenance and a brief coordinated interruption. Do not treat authorization for the passive propagation collector as authorization to change Wavelog.
2. Inspect the actual `compose.yml` and overrides with secret-safe tooling; record the full application image ID, configuration, volume mappings, and exact contact-sync deployment state. Do not print API keys, DB passwords, or unredacted `docker compose config` to logs.
3. Verify the *actual* official upstream `ghcr.io/wavelog/wavelog:3.2.3` image exists, is appropriate for the current database schema, and pin its **resolved immutable digest**. The tag/digest has **not** been verified here. Confirm no pending migrations or incompatible custom changes.
4. Make a verified, encrypted, off-host MariaDB-consistent logical backup (e.g. approved `mariadb-dump --single-transaction --routines --events --triggers` using secret-safe credential handling) **and** independently preserve all four named volumes and Compose/override files. Capture a backup manifest and checksum, and verify a test restore in isolation. Do not rely on `docker export` as a database backup.
5. Inventory current QSOs, station locations, station IDs, station/logbook bindings, upload retry ledger, LoTW/eQSL/ClubLog settings, and any pending unsynced Rolling Thunder contacts. Save before/after counts; preserve original local contact IDs and grid snapshots.

## Controlled maintenance sequence — manual only

1. Announce the window. Coordinate a temporary hold of **remote Wavelog uploads** so contacts remain locally durable and queued; do not change the radio, Pi, or local QSO capture.
2. Verify the backup and recovery path. Preserve the custom image and existing Compose definition unchanged as rollback artifacts.
3. Change **only** the approved Wavelog application image reference in a reviewed Compose configuration to the pinned upstream digest; do not recreate or erase the database, uploads, userdata, or config volumes. Keep MariaDB image unchanged.
4. Recreate only `wavelog-main` under operator supervision. Watch logs for startup, migration, schema and application errors. If any error appears, stop and restore the prior application image and configuration.
5. Validate the UI and authenticated API, station profiles, six-character profile grids, QSO counts, selected station IDs, existing LoTW/eQSL/ClubLog settings, and representative maps/awards. Verify a controlled QSO import into the **correct existing** station location; imported ADIF `MY_GRIDSQUARE` is **not** expected to override it.
6. Resume the existing contact-sync service only after an explicit operator check. Verify one controlled contact, idempotent duplicate handling, no missing QSOs, stable UUID/ledger, and queued-contact retry without data loss. Compare before/after counts.
7. Record official image digest, database/volume backup IDs, results, maintenance window, and operator approval.

## Rolling Thunder and propagation rollout sequencing

1. Review the cleaned immutable Rolling Thunder wheel and checksum. Confirm its
   archive has no `wavelog_version` modules, `/wavelog-version` route, version-watch
   configuration, legacy watcher credential, upload guard, or Pi warning.
2. Do not install the Rolling Thunder wheel as part of the Wavelog maintenance
   window. Wavelog image restoration, Rolling Thunder code deployment, and
   propagation activation are separate approvals and rollback domains.
3. After Wavelog is running the pinned unmodified upstream image, validate existing
   contact-sync behavior with one controlled queued contact. Do not create a station
   profile automatically for this acceptance; use an operator-reviewed existing
   target and stop if the required target is absent or ambiguous.
4. Keep the propagation environmental collector disabled throughout Wavelog
   restoration. Its later rollout may use only the propagation-specific checklist in
   `docs/FORGE_PROPAGATION_DEPLOYMENT_PROPOSAL.md` and must not restart Wavelog,
   contact sync, the Pi, spot services, or radio services.
5. Keep the completed-QSO ingestion and VOACAP gates disabled; its staged listener,
   unit, configuration, and one-attempt producer client do not authorize a live
   source. PSK Reporter orchestration remains without a production process or
   producer.

## Failure and rollback

- Before irreversible migrations, restore the exact saved Compose configuration and original local application image ID, then verify application health and the preserved DB/volumes.
- If schema/data migration occurred, application-image rollback alone may be unsafe: restore the matched, tested MariaDB + uploads/userdata/config backup set, not an unmatched database snapshot. Coordinate contact replay against preserved local durable queues and idempotency ledger.
- Never delete/recreate volumes, purge the UUID ledger, rewrite station IDs, auto-create station profiles, or discard locally unsynced QSOs as a shortcut.
- Do not automatically create, rotate, patch, link, or delete station profiles during
  rollback or acceptance. A future read-only resolver is a separate design requiring
  station-location/QSL-policy review and explicit approval.

## Integration release prerequisite

The integration worktree has removed the uncommitted Wavelog version-watch API,
latch, upload guard, Pi warning, watcher credential/configuration, and associated
tests/docs while preserving the local six-character grid and mainline contact-sync
code. The release candidate remains provisional until the recorded full pytest,
Ruff, strict MyPy, pre-commit, `git diff --check`, and rebuilt-wheel verification
all pass.
