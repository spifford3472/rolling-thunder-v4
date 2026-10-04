# Forge Contact Synchronization and Wavelog Operations

This document is the architectural and operational reference for Rolling Thunder contact synchronization introduced by checkpoint #190.

## Core invariants

Rolling Thunder remains a local-first mobile logger. A QSO succeeds when it has been durably committed to the local Rolling Thunder SQLite database. Forge, WireGuard, DNS, mobile connectivity, Wavelog, QRZ, and every other remote service are outside that local transaction and cannot make local logging unavailable.

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
Station Location: Mobile
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

Required target:

- Station Logbook: `KI5VNB Main`
- Station Location: `Mobile`

Wavelog API v2 writes a QSO to a Station Location using `station_profile_id`. Rolling Thunder never stores or assumes that numeric ID. Forge calls the station-list endpoint and requires exactly one owned station location named `Mobile`; only that returned numeric ID can be used for QSO import.

If `Mobile` is absent or ambiguous, authentication fails, the response is malformed, or Wavelog is unavailable, Forge rejects the synchronization attempt. It never falls back to Home or any other station location. The local QSO remains unsynchronized and is retried later.

Wavelog's v2 station resource does not expose the enclosing Station Logbook name/link. Forge can therefore enforce `Mobile` programmatically, while `Mobile` -> `KI5VNB Main` remains a Wavelog server-side configuration invariant. `station_logbook_name` records the expected target in Forge configuration, and real acceptance must verify in Wavelog that `Mobile` belongs to and displays inside `KI5VNB Main` before merge.

## Wavelog API and token

Forge uses Wavelog API v2 bearer-token authentication. Production acceptance uses these token scopes:

- `station:read` — resolve `Mobile`;
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
| `notes` | `NOTES` when present |

Missing optional metadata never makes local logging fail. Existing QRZ enrichment marks an optional lookup failure complete without a grid, so QRZ unavailability cannot indefinitely block Wavelog synchronization.

Country on the LOG panel is display-only. It is resolved conservatively from an offline callsign-prefix table and falls back to `—`; rendering performs no network lookup and country is not a prerequisite for synchronization.

## Idempotency and uncertain outcomes

The local `contact_id` UUID is stable from QSO creation through Wavelog synchronization. The Pi sends:

```text
Idempotency-Key: <contact_id UUID>
```

Forge requires the header UUID to match the body `contact_id`. Before calling Wavelog, Forge transactionally records a ledger row containing the UUID, a SHA-256 of the stable Wavelog-bound payload plus target profile ID, the resolved profile ID, certainty state, and timestamps.

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
that healthy shared sync uploads completed FT8 contacts to the dynamically
resolved Mobile profile, including after QRZ lookup failure. The notification
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
Forge `/health` result, and Wavelog's current Mobile location/logbook mapping.
Do not rewrite states, re-log the QSO, delete the ledger, or replay RF as an
investigation shortcut. A performance-attempt record is not a contact receipt.

Keep the PR draft until installed acceptance. Preserve exact rollback SHAs,
configuration, and SQLite-safe Pi/Forge backups. On the approved fixed Pi build,
complete one explicitly authorized FT8 QSO and verify one local UUID, FT8 mode,
actual reports, original start time/frequency, frozen local grid and known remote
grid. Verify its LOG row becomes SYNC and exactly one Wavelog QSO appears in
Mobile under KI5VNB Main with the same fields. Confirm failed/aborted/unanswered
attempts produce no contacts. During a safe approved offline/retry test, confirm
local durability and eventual upload, then repeated Sync/restart without a
second Wavelog QSO. Verify an ordinary contact still follows the same path.
Confirm the next FT8 QSO captures fresh current GPS grid. A Pi-only callback
change does not require replacing Forge code/configuration or restarting the
spot/weather service.

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

The Pi SQLite database remains the local operational record. The Forge idempotency ledger is separate durable state and must be included in Forge backup coverage.

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

`GET /health` verifies that Forge can authenticate to Wavelog and resolve exactly one `Mobile` location. Health failure never makes local logging fail.

- **Forge/WireGuard unreachable:** local QSO remains; Pi records failed sync/retry state.
- **Wavelog unreachable/timeout:** Forge leaves its ledger pending; Pi retries later.
- **401/403:** token invalid/expired or required scope unavailable; local QSO remains unsynchronized.
- **missing/duplicate `Mobile`:** Forge refuses to choose another location.
- **malformed Wavelog response:** fail safely; local QSO remains.
- **timeout after possible remote success:** deterministic retry + Wavelog duplicate detection resolves uncertainty.
- **Forge restart:** durable ledger survives.
- **Pi restart:** local pending/failed contacts and retry metadata survive.
- **repeated manual Sync:** Pi single-flight plus Forge UUID ledger prevent overlapping/replayed writes.
- **database error:** report failure; never pretend synchronization succeeded.

## Real acceptance gate

CI/mocks are necessary but not sufficient. Before merge, acceptance must use:

1. the actual `anvilmobile` installation;
2. production Forge;
3. real Wavelog at `http://192.168.9.170:8086`;
4. one controlled test QSO/contact;
5. Wavelog verification that it is under Station Location `Mobile` and visible in Station Logbook `KI5VNB Main`;
6. LOG panel verification of unsynchronized -> synchronized;
7. one safe offline/retry case;
8. repeated manual/retry verification that only one Wavelog QSO exists.

The PR remains draft until this installed acceptance is complete.
