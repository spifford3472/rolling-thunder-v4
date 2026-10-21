# Forge Contact Synchronization and Wavelog Operations

This document is the architectural and operational reference for Rolling Thunder contact synchronization introduced by checkpoint #190.

## Core invariants

Rolling Thunder remains a local-first mobile logger. A QSO succeeds when it has been durably committed to the local Rolling Thunder SQLite database. Forge, WireGuard, DNS, mobile connectivity, Wavelog, QRZ, and every other remote service are outside that local transaction and cannot make local logging unavailable.

Contact payload format 5 adds a typed originating workflow, nullable configured
TX power, structured nullable weather slots, and an immutable weather-note flag.
Wavelog ADIF emits `TX_PWR` only when known and appends the exact `Contact Wx:` and
`Local Wx:` lines when requested. Contact synchronization performs no weather I/O:
it uploads the immutable structured weather values it receives, and formats an absent
value as `N/A`. The reusable weather provider remains available to separate background
workers, but public HTTP latency cannot delay station resolution, claim, or upload.
At local commit, the Pi best-effort snapshots only already-published state: fresh
callsign-info target weather proven to match the same callsign/location or grid, plus
non-stale retained local Forge weather proven to match the QSO's frozen local location.
Frozen local coordinates take precedence and use the same 10 km boundary as Forge's
default mobile weather refresh policy; when coordinates are unavailable, the frozen
six-character local grid must match the weather coordinates. Manual Browse/POTA/DX
commits and completed FT8 contacts share this path. Missing, stale, or mismatched
observations remain null, and retries reuse the stored payload rather than substituting
newer weather.

```text
Rolling Thunder UI / physical controls
        |
        | local commit first
        v
SQLite contacts table on anvilmobile
        |
        | ContactSyncService (background, restart-safe retry, single-flight)
        v
HttpHomePlatformClient
        |
        | private HTTP /contacts + Idempotency-Key=contact_id
        v
Forge contact-sync service :8767
        |
        | durable UUID-keyed idempotency ledger
        v
Wavelog API v2
        |
        | dynamically resolved station_profile_id
        v
Station Location: Mobile - XXXX - YY (verified dynamic), or Mobile - Unknown Location
```

The UI never talks to Wavelog and never performs synchronization HTTP, DNS waits, retry sleeps, or Wavelog authentication on the Tk event thread. A failed or uncertain remote operation never deletes or rolls back the local QSO.

## Why Forge owns Wavelog

The Pi already has a typed Home Platform boundary and background contact synchronization. Wavelog-specific authentication, endpoint behavior, station-location discovery, ADIF conversion, provider errors, duplicate handling, and remote idempotency therefore remain on Forge.

The Wavelog integration runs as a small independent Forge service instead of inside the spot/weather aggregator. That preserves the same trust boundary while preventing a Wavelog outage or bad Wavelog credential from taking down spot/weather ingestion.

The Pi Home Platform endpoint for this feature is:

```text
http://192.168.9.170:8767
```

The service is private/VPN-only and must not be exposed to the Internet.

## Wavelog target safety

Wavelog's official station/QSO/logbook semantics and a future read-only,
operator-provisioned resolver are audited separately in
`docs/WAVELOG_STATION_PROFILE_RESOLVER_DESIGN.md`. That proposal is not implemented
in this release and does not authorize automatic profile creation or production
changes.

Configured safety anchors:

- Station Logbook: `KI5VNB Main`
- legacy Station Location/template: `Mobile`

Wavelog API v2 writes a QSO to a Station Location using `station_profile_id`.
Rolling Thunder never assumes or scans numeric station or logbook IDs. Before the
Forge UUID ledger claim, Forge reads the owner-scoped station list, resolves exact
names without guessing IDs, resolves exactly one configured logbook by exact name,
and selects the final station target from immutable `Contact` fields. Forge does
durably retain an exact dynamic station name -> verified station ID and UUID recovery
binding in the contact-sync SQLite database after Wavelog has supplied that identity.

When `my_grid`, `my_state`, `my_cq_zone`, and `my_itu_zone` are all frozen and
usable, the station name is exactly `Mobile - XXXX - YY`. `XXXX` is the uppercase
four-character Maidenhead prefix and `YY` is the normalized two-letter state. The
station profile grid is the four-character prefix, while QSO ADIF retains the full
frozen `MY_GRIDSQUARE`. Existing exact-name stations are reused only when UUID,
callsign, DXCC, grid, state, CQ zone, and ITU zone are compatible with the requested
identity and validated legacy template.

`Contact.my_grid` remains the backward-compatible stored field, but it is validated
as the single authoritative six-character value. `my_grid6` aliases it and `my_grid4`
is always derived as `my_grid6[:4]`; there is no independently persisted routing grid.
POTA contact coordinates are frozen when available. Otherwise Forge may use the
trusted remote grid center for contact weather; it never invents a location.

Wavelog's `GET /index.php/api/v2/station` list may include only locations linked to
the owner's active logbook when the account's `active_log_only` option is enabled.
Its direct `GET /index.php/api/v2/station/{id}` lookup is ownership-checked but does
not apply that list filter. New stations are initially unlinked, so Forge must not
depend on list visibility after creation or during recovery.

If the exact dynamic station is absent, Forge creates it with `POST
/index.php/api/v2/station`, verifies the complete `201` station object, and
transactionally persists its exact name, positive ID, and UUID before attempting the
logbook link. Callsign and DXCC come from the validated configured legacy `Mobile`
profile; grid/state/CQ/ITU come only from the immutable contact. Forge never deletes,
renames, or mutates unrelated profiles.

On a later resolution where the list hides that exact name, Forge uses only its
durable verified binding to direct-fetch the known ID. It requires successful owned
API access, the same exact name and UUID, and full compatibility with the frozen
grid/state/CQ/ITU plus the current validated legacy template callsign/DXCC. A missing,
changed, or incompatible bound station fails closed; the binding is not silently
overwritten. A compatible visible exact-name station can establish or refresh the
binding.

Wavelog returns only a generic `409` for an identical station create and supplies no
existing ID. Forge first accepts a visible, fully verified exact match. If none is
visible, it can recover only through a pre-existing verified binding and direct GET.
An arbitrary external hidden-station race without such a binding fails closed with a
clear error. Forge never scans or guesses numeric IDs.

Forge reads `GET /index.php/api/v2/logbook`, requires exactly one configured
logbook name, and links a dynamic station with `PATCH` only when needed. Because
`station_ids` has replacement semantics, Forge preserves every prior ID, adds the
new ID, and verifies the result with another read. A station created by Rolling
Thunder is safe to reuse after a failed link or Forge restart because its verified
binding was committed before the link attempt. This guarantee does not extend to an
arbitrary hidden external station that produced an ID-less `409`. If frozen routing
data is insufficient, Forge resolves or creates the exact `Mobile - Unknown Location`
profile, verifies that it carries no grid/state/CQ/ITU metadata, binds it durably, and
links it to the configured logbook. The legacy `Mobile` profile remains the verified
template for callsign/DXCC and health checks, not the locationless QSO target. Dynamic
profiles are never patched to a six-character QSO grid. The legacy alignment helper
also uses only derived grid4, so neither legacy nor dynamic profiles chase moving
six-character subsquares.

Wavelog 3.2.3 parses the submitted full `MY_GRIDSQUARE`, but its import path then
unconditionally replaces `COL_MY_GRIDSQUARE` with the selected station profile's
grid. Its QSO PATCH resource does not permit `my_gridsquare`. Rolling Thunder therefore
remains authoritative for grid6 and derived grid4, configures station profiles with
grid4, and submits grid6 in ADIF, while Wavelog 3.2.3 stores grid4. Preserving grid6
inside Wavelog requires a separate provider/API change; Rolling Thunder must not
temporarily mutate a station profile to a moving grid6 as a workaround.

Absent/ambiguous legacy or dynamic names, incompatible metadata, an unlinked legacy
profile, malformed responses, unverifiable identity, failed creation, or failed
membership verification all fail closed. Forge never falls back to Home or another
station. The local QSO remains unsynchronized and is retried later. `/health` only
reads and validates the configured legacy profile/logbook membership; it never
creates or links a dynamic station.

## Wavelog API and token

Forge uses Wavelog API v2 bearer-token authentication. Production acceptance uses these token scopes:

Dynamic routing requires Wavelog 3.2.0 or newer: station management was introduced
in 3.1.0 and the v2 logbook membership API in 3.2.0. Confirm the installed Wavelog
version before test deployment.

- `station:read` — list/re-read exact legacy and dynamic station locations;
- `station:write` — create dynamic mobile station locations and retain legacy grid alignment;
- `logbook:read` — resolve `KI5VNB Main` and verify complete membership;
- `logbook:write` — link verified dynamic station locations while preserving existing IDs;
- `qso:write` — import the QSO;
- `qso:read` — verify the controlled acceptance QSO and duplicate behavior.

The token exists only in the Forge process environment:

```text
ROLLING_THUNDER_WAVELOG_V2_TOKEN
```

Never put a real Wavelog token, password, or API key in Git, YAML, issue/PR text, or command output committed to the repository.

## Contact mapping

Forge maps each immutable local `Contact` to one deterministic ADIF record and submits it with the resolved `Mobile` `station_profile_id`.

| Rolling Thunder | Wavelog / ADIF |
| --- | --- |
| `callsign` | `CALL` |
| `started_at` | UTC `QSO_DATE` + `TIME_ON` |
| `frequency_hz` | `FREQ` in ADIF MHz |
| derived band | `BAND` |
| `mode` | `MODE`; USB/LSB become `MODE=SSB` plus `SUBMODE` |
| `rst_sent` | `RST_SENT` |
| `rst_received` | `RST_RCVD` |
| `grid` | `GRIDSQUARE` when known |
| `my_grid` | `MY_GRIDSQUARE` when known |
| `pota_reference` | `POTA_REF` when present |
| `notes` | ADIF `NOTES`; exact existing text, otherwise exactly `Mobile QSO` |

The notes default is applied only during Wavelog-bound ADIF conversion; immutable
local `Contact` rows are not changed. Nonblank `Contact.notes` text is emitted
exactly, without prepending/appending/replacing text or duplicating the phrase.

Missing optional metadata never makes local logging fail. Existing QRZ enrichment marks an optional lookup failure complete without a grid, so QRZ unavailability cannot indefinitely block Wavelog synchronization.

Country on the LOG panel is display-only. It is resolved conservatively from an offline callsign-prefix table and falls back to `—`; rendering performs no network lookup and country is not a prerequisite for synchronization.

## Idempotency and uncertain outcomes

The local `contact_id` UUID is stable from QSO creation through Wavelog synchronization. The Pi sends:

```text
Idempotency-Key: <contact_id UUID>
```

Forge requires the header UUID to match the body `contact_id`. Forge first selects
and verifies the exact station target. Before the QSO write, it transactionally
records a ledger row containing the UUID, a SHA-256 of the actual stable
Wavelog-bound ADIF plus that exact target profile ID, the resolved profile ID,
certainty state, and timestamps.

A repeated UUID with changed QSO data or a different target station profile is rejected rather than silently replayed or mutated.

Lost-response behavior is deliberate:

1. Forge durably claims UUID A.
2. Wavelog imports A's QSO.
3. The response is lost or Forge restarts before marking its ledger synchronized.
4. Rolling Thunder retries A.
5. Forge reissues the same deterministic QSO because its durable state is still uncertain.
6. Wavelog duplicate detection reports the QSO skipped as a duplicate.
7. Forge marks A synchronized and returns `already_exists`.

A Wavelog duplicate is therefore a successful idempotent outcome. Once the Forge ledger says the UUID is synchronized, repeated retries/manual Sync presses return `already_exists` without another Wavelog write.

## Pi synchronization behavior

The existing `ContactRetryRepository` stores restart-safe retry metadata. `ContactSyncService` uses bounded exponential backoff defaults and checkpoint #190 adds a single-flight lock so periodic and manual runs cannot overlap.

Synchronization is opportunistic rather than dependent on a daily timer:

- successful local commit requests background synchronization immediately;
- unsynchronized contacts found at application startup request synchronization;
- newly observed pending contacts request synchronization;
- the configured periodic sync remains a secondary retry mechanism;
- Context Button #1 on LOG requests synchronization immediately;
- failed contacts retain restart-safe retry metadata and are retried only when due.

The FT8 runtime completion handler records worked-today state and notifies the
dashboard to request the same LOG background sync as ordinary/DMR commits.
`commit_completed` uses the shared enrichment readiness gate: known remote
grids are ready immediately; a missing grid with configured QRZ fallback waits
for the shared worker, which marks lookup failure ready without a grid. An
immediate sync request can precede enrichment completion; periodic sync remains
the fallback. No FT8-specific station selection or Wavelog uploader exists.

### Post-v4.4.0 FT8 investigation and production acceptance

Cloud regression reproduced a missing immediate FT8 post-commit sync request:
the completion handler updated worked-today state only. Cloud tests also showed
that healthy shared sync uploads completed FT8 contacts through the shared
Wavelog station-routing boundary, including after QRZ lookup failure. The notification
fix removes reliance on later LOG observation for the initial request; it does
not by itself explain permanently missing contacts or repair stalled enrichment
after a credential/configuration change. Production evidence is required.

Before deployment, record the installed Pi and Forge commit SHAs and relevant
service timestamps. Obtain the **configured** Pi database path from local
configuration; do not assume a path from this document. Run these queries using
SQLite read-only mode against the Pi database (or a SQLite-safe backup):

```sql
SELECT contact_id, callsign, mode, started_at, frequency_hz,
       rst_sent, rst_received, my_grid, grid, grid_source,
       enrichment_state, synchronization_state
FROM contacts WHERE mode = 'FT8'
ORDER BY started_at DESC LIMIT 20;

SELECT c.contact_id, c.enrichment_state, c.synchronization_state,
       r.attempt_count, r.next_attempt_at, r.last_error
FROM contacts AS c LEFT JOIN contact_sync_retries AS r
ON r.contact_id = c.contact_id
WHERE c.mode = 'FT8' AND c.synchronization_state <> 'synchronized'
ORDER BY c.started_at DESC LIMIT 20;
```

Compare an affected completed FT8 UUID with a known-good ordinary contact.
`pending_qrz` is ineligible even for manual Sync; check whether the Pi QRZ worker
is configured/running and whether it completed that lookup. `ready` + `pending`
requires investigation of sync scheduling/configuration; `failed` requires the
retry error. An absent local contact requires inspection of completion/logging
errors, not a station-profile change. Correlate the affected UUID with the Forge
ledger using SQLite read-only mode on `/var/lib/rolling-thunder/forge-contact-sync.db`:

```sql
SELECT contact_id, station_profile_id, state, remote_disposition,
       created_at, synchronized_at, updated_at
FROM forge_contact_sync_ledger WHERE contact_id = '<affected UUID>';
```

Collect Pi application/service logs and
`rolling-thunder-forge-contact-sync.service` journal entries for the QSO time and
subsequent sync attempts. Keep credentials out of collected output. Inspect the
non-secret Home Platform enabled/base URL settings, QRZ worker availability,
Forge `/health` result, and Wavelog's exact selected station/logbook mapping.
Do not rewrite states, re-log the QSO, delete the ledger, or replay RF as an
investigation shortcut. A performance-attempt record is not a contact receipt.

Keep the PR draft until installed acceptance. Preserve exact rollback SHAs,
configuration, and SQLite-safe Pi/Forge backups. On the approved fixed Pi build,
complete one explicitly authorized FT8 QSO and verify one local UUID, FT8 mode,
actual reports, original start time/frequency, frozen local grid and known remote
grid. Verify its LOG row becomes SYNC and exactly one Wavelog QSO appears in the
expected dynamic station (including `Mobile - Unknown Location` when appropriate) under `KI5VNB Main` with
the same fields. Confirm failed/aborted/unanswered
attempts produce no contacts. During a safe approved offline/retry test, confirm
local durability and eventual upload, then repeated Sync/restart without a
second Wavelog QSO. Verify an ordinary contact still follows the same path.
Confirm the next FT8 QSO captures fresh current GPS grid. A Pi-only callback
change does not require replacing Forge code/configuration or restarting the
spot/weather service.

### Development-only FT8 performance schema-4 recovery

FT8 performance telemetry is not QSO contact synchronization. `POST
/ft8-performance` writes only `ft8_performance_attempts`; it does not resolve a
station, claim `forge_contact_sync_ledger`, or call Wavelog. Retrying telemetry must
not be implemented by replaying contacts, relogging QSOs, changing Pi contact state,
or posting directly to Wavelog.

The recovery schema advances transactionally through the historical versions:

1. schema 1 creates the original performance table;
2. schema 2 adds nullable configured-power start/end/max columns;
3. schema 3 adds `busy_extension_attempts` with historical value zero; and
4. schema 4 adds checked nullable `local_latitude` and `local_longitude` columns.

Schema 4 does not rebuild the table, backfill coordinates, or recompute stored
payload hashes. New coordinate-bearing attempts retain both values. Existing rows
remain null in the new columns, while current and pre-coordinate hash forms continue
to support the established exact-replay decision. The newer `choice_at_utc` value is
owned by the Phase-B attempt ledger and is not added to this legacy query projection.

Before any separately approved production installation, record the exact installed
SHA/package and service timestamps, then take a SQLite-consistent backup of the
shared Forge contact-sync database using the approved deployment workflow. A raw
copy of a running WAL database is not an acceptable backup. Restore that backup to a
non-production path and run the migration there first. Compare pre/post counts and
stable identity/hash projections for all existing tables, including the expected
performance-attempt, contact-ledger, and station-binding counts; run `quick_check`,
`integrity_check`, and `foreign_key_check`; verify schema version 4 and both new
columns; and confirm all historical coordinate values remain null. Keep the backup,
installed SHA, candidate SHA, configuration identity, and verification output as the
rollback record.

Because an older schema-3 binary rejects schema 4 as newer, package-only downgrade is
not a working rollback. If validation fails before any new durable activity, stop
only the contact-sync component through the approved wrapper and restore the matched
pre-migration package plus SQLite-consistent backup. If any contact, binding, or
telemetry state changed after migration, restoring the whole shared database could
lose durable state; preserve it and use a reviewed forward fix instead. Never delete
the performance table or reset the schema marker as rollback.

Production evidence reconciliation is read-only until deployment is separately
approved. Capture Pi outbox counts by synchronization state and error class, the
oldest/newest creation times, retry counts/next-attempt times, and the Forge
performance UUID/count/hash set. After an approved cutover, allow only the ordinary
background telemetry scheduler to retry; do not post/replay contacts or QSOs. Verify
that each acknowledged attempt moves to synchronized, Forge gains at most one row
per previously absent attempt UUID, pre-existing Forge rows and hashes remain
unchanged, contact-ledger and station-binding counts remain unchanged, database
checks remain clean, and Wavelog receives zero QSO writes. Reconcile the final Pi
synchronized UUID set against Forge attempt UUIDs rather than comparing only totals.

An older failed row is always eligible once its capped retry time is due, while a
pending row is always eligible. `list_ready` orders the union by creation time and
then applies the configured batch limit. Therefore a set of older, repeatedly due
HTTP-422 rows larger than one batch can occupy every pass and starve newer pending
rows. High capped retry counts plus newer untouched pending rows are consistent with
that mechanism. This is the likely explanation for the observed pending backlog,
but it is not proven without read-only Pi configuration, row timestamps,
`next_attempt_at`, scheduler lifecycle, and logs. The recovery does not change retry
ordering; once the blocking 422 condition is corrected, bounded passes should drain
the older rows and then reach the pending rows.

## LOG panel

LOG is a normal dashboard context in the existing context-navigation cycle. It does not redefine Back, encoder movement, Context Button #2, tertiary actions, or unrelated global controls.

Only the newest ten local Rolling Thunder contacts are shown, newest first. Rows contain UTC date/time, callsign, band, offline country abbreviation (or `—`), and synchronization state using text/symbol plus color:

- `✓ SYNC` — synchronized;
- `○ WAIT` — pending;
- `! FAIL` — failed attempt.

Header:

```text
UNSYNCED <count> / TOTAL <count>
```

`UNSYNCED` includes every locally stored contact not yet marked `synchronized`, including failed contacts.

Context Button #1 is Sync Unsynced / Sync Now. It submits to a one-worker background executor and returns immediately. Tk refresh consumes only an immutable `LogPanelSnapshot`.

## Local retention

Retention preserves uncertain data over size targets:

1. Up to 5,000 contacts are retained normally.
2. Only when total contacts exceeds 5,000 does retention run.
3. In one immediate transaction, the repository selects the oldest at most 1,000 rows whose state is exactly `synchronized`.
4. Only those selected synchronized UUIDs are deleted and committed atomically.
5. Pending, failed, or uncertain contacts are never pruned.
6. If fewer than 1,000 synchronized rows are available, only those provably synchronized rows are deleted.

The database may therefore remain above 5,000 if preservation requires it. Latest-ten ordering remains newest-first after pruning.

## Backup and recovery

The Pi SQLite database remains the local operational record. The Forge UUID ledger
and verified dynamic-station binding table are separate durable state in the same
contact-sync SQLite database and must be included in Forge backup coverage.

Recovery rules:

- restoring an older Pi backup can reintroduce a locally pending QSO already present in Wavelog;
- a current Forge ledger prevents a second Wavelog write for a known synchronized UUID;
- if the Forge ledger is also rolled back/lost, deterministic Wavelog duplicate detection is the secondary defense;
- an older Forge ledger is never proof that Wavelog lacks a QSO;
- retention never deletes a contact whose remote state is uncertain.

Do not delete/recreate the Forge ledger as routine troubleshooting.

## Forge deployment

The contact-sync daemon is intentionally deployment-isolated from the existing Forge spot/weather service. The services share the `rollingthunder` service account and trusted private-network boundary, but they do **not** share an application checkout or Python virtual environment. This prevents a contact-sync deployment from implicitly upgrading, restarting, or otherwise changing the established `rolling-thunder-forge-spots.service` runtime on port 8766.

Checkpoint #190 adds:

```text
deploy/systemd/rolling-thunder-forge-contact-sync.service
deploy/systemd/forge-contact-sync.env.example
config/forge-contact-sync.example.yaml
```

Production contact-sync paths:

```text
/opt/rolling-thunder-forge-contact-sync
/opt/rolling-thunder-forge-contact-sync/.venv
/etc/rolling-thunder/forge-contact-sync.yaml
/etc/rolling-thunder/forge-contact-sync.env
/var/lib/rolling-thunder/forge-contact-sync.db
```

The existing spot/weather service remains independently deployed at:

```text
/opt/rolling-thunder-forge
/opt/rolling-thunder-forge/.venv
192.168.9.170:8766
```

Installing or updating checkpoint #190 contact synchronization must not replace the existing Forge checkout/venv or require a restart of `rolling-thunder-forge-spots.service`. The contact-sync application root should be installed from a known commit/artifact and its own venv should contain the tested `rolling-thunder` wheel plus its runtime dependencies.

The installed environment file should be readable only by service administrators and contain the real `ROLLING_THUNDER_WAVELOG_V2_TOKEN`. The systemd unit uses `StateDirectory=rolling-thunder`, `ProtectSystem=strict`, and permits state writes below `/var/lib/rolling-thunder`.

After installation/configuration changes:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now rolling-thunder-forge-contact-sync.service
sudo systemctl status --no-pager rolling-thunder-forge-contact-sync.service
```

## Pi configuration

On `anvilmobile`, enable the existing Home Platform client and point it to Forge, never Wavelog directly:

```yaml
home_platform:
  enabled: true
  base_url: "http://192.168.9.170:8767"
  request_timeout_s: 5.0
  health_poll_interval_s: 30.0
  contact_sync_interval_s: 30.0
  contact_sync_batch_size: 25
```

There is intentionally no Wavelog URL/token in Pi configuration. Retry/backoff remains owned by the existing contact synchronization service/retry repository; the periodic interval above is not required for correctness because post-commit and startup sync requests are opportunistic.

## Failure interpretation

`GET /health` verifies, read-only, that Forge can authenticate to Wavelog, resolve
exactly one configured legacy `Mobile`, resolve exactly one configured logbook, and
confirm legacy membership. It never creates or links a dynamic station. Health
failure never makes local logging fail.

- **Forge/WireGuard unreachable:** local QSO remains; Pi records failed sync/retry state.
- **Wavelog unreachable/timeout:** Forge leaves its ledger pending; Pi retries later.
- **401/403:** token invalid/expired or required scope unavailable; local QSO remains unsynchronized.
- **missing/duplicate/incompatible station:** Forge refuses to choose or mutate another location.
- **missing/duplicate logbook or failed link:** Forge leaves the contact unsynchronized; a later retry can direct-fetch and reuse a station that Rolling Thunder already created and bound.
- **hidden ID-less station conflict without a prior binding:** Forge fails closed because Wavelog supplies no safe ID; it does not scan IDs.
- **changed/missing/incompatible bound station:** Forge fails closed and preserves the binding for investigation rather than overwriting it.
- **malformed Wavelog response:** fail safely; local QSO remains.
- **invalid FT8 performance payload:** Forge returns HTTP 422 and logs the rejected field and validation reason without logging the request payload, so a blocking outbox record can be diagnosed from the service journal.
- **timeout after possible remote success:** deterministic retry + Wavelog duplicate detection resolves uncertainty.
- **Forge restart:** durable UUID ledger and verified station bindings survive.
- **Pi restart:** local pending/failed contacts and retry metadata survive.
- **repeated manual Sync:** Pi single-flight plus Forge UUID ledger prevent overlapping/replayed writes.
- **database error:** report failure; never pretend synchronization succeeded.

## Real acceptance gate

CI/mocks are necessary but not sufficient. Before merge, acceptance must use:

1. the actual `anvilmobile` installation;
2. production Forge;
3. real Wavelog at `http://192.168.9.170:8086`;
4. one controlled test QSO/contact;
5. Wavelog verification that a location-complete contact is under the exact dynamic
   station name and visible in Station Logbook `KI5VNB Main`;
6. LOG panel verification of unsynchronized -> synchronized;
7. one safe offline/retry case;
8. repeated manual/retry verification that only one Wavelog QSO exists;
9. one locationless/historical contact confirming `Mobile - Unknown Location`
   routing with no fabricated grid/state/CQ/ITU metadata;
10. capture confirming Rolling Thunder submits the full frozen `MY_GRIDSQUARE` and
    expected ADIF `NOTES`, while the dynamic profile and Wavelog 3.2.3 stored QSO
    retain grid4 because of the documented provider overwrite.

The PR remains draft until this installed acceptance is complete.

## Immutable QSO location (Checkpoint A)

`Contact.my_latitude` and `Contact.my_longitude` are optional paired local-station
coordinates, bounded to ±90 and ±180 degrees. Booleans, non-finite values and
partial pairs are rejected. They describe this QSO, not the contacted station.
Ordinary logging resolves coordinates and `my_grid` from the GPSState captured
before the commit worker starts, using the existing connected/fixed/fresh
(maximum age 10 seconds) rule. FT8 successful logging uses the latitude,
longitude and grid frozen in FT8QsoContext at authorization; the next authorization
captures its own location. Failed/aborted attempts create no Contact. No sync or
retry operation reads current GPS to fill historical coordinates.
Missing GPS remains valid, and historical contacts retain NULL coordinates.

Pi SQLite schema 16 adds two nullable REAL columns to schema 15 with ALTER TABLE;
no historical backfill or table rebuild occurs. Complete-contact JSON exports and
verified backups use format 3; imports retain formats 1 and 2 with absent
coordinates defaulting to None. Older importers cannot read format 3.

The existing Pi `/contacts` body serializes the complete Contact, including the
new fields. Updated Forge validates that same shared model; old senders without
coordinates remain accepted. **Upgrade and verify the actual Forge contact-sync
venv before enabling the updated Pi sender:** older Forge models reject extra
fields, including fields serialized as null. Inspect installed import paths and
source, not just the checkout/version string. No Forge ledger migration is needed.
Local idempotent replay includes coordinates and rejects changed-location UUIDs.
Forge's existing hash remains based on station profile and Wavelog-bound ADIF,
so coordinate-only differences do not change that hash.

Coordinates are not added to ADIF and synchronization never reads current GPS or
calls a weather provider.
Checkpoints C/D/E now use the frozen Checkpoint A/B fields to select, safely create,
verify, and link dynamic mobile station locations. Locationless/historical contacts
retain legacy `Mobile` routing and grid4-only profile alignment. The blank-only Wavelog
default is implemented in ADIF `NOTES` (not a separate comments field). See
[owner acceptance and rollback](CHECKPOINT_A_ACCEPTANCE.md) for the earlier schema
checkpoint; the current routing contract is this document.
