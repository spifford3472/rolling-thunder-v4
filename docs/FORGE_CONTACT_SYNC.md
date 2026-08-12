# Forge Contact Synchronization and Wavelog Operations

This document is the operational and architectural reference for Rolling Thunder contact synchronization introduced by checkpoint #190.

## Purpose and non-negotiable invariants

Rolling Thunder remains a local-first mobile logger. A QSO is successful when it has been durably committed to the local Rolling Thunder SQLite database. Forge, WireGuard, DNS, mobile connectivity, Wavelog, QRZ, and every other remote service are outside that local transaction and cannot make local logging unavailable.

The synchronization path is:

```text
Rolling Thunder UI / physical controls
        |
        | local commit first
        v
SQLite contacts table on anvilmobile
        |
        | ContactSyncService (background, retry/backoff, single-flight)
        v
HttpHomePlatformClient
        |
        | private HTTP /contacts + stable Idempotency-Key=contact_id
        v
Forge contact-sync service :8767
        |
        | durable UUID-keyed idempotency ledger
        v
Wavelog API v2
        |
        | explicitly resolved station_profile_id
        v
Station Location: Mobile
```

The UI never talks to Wavelog and never performs synchronization HTTP, DNS waits, retry sleeps, or Wavelog authentication on the Tk event thread.

A failed or uncertain remote operation never deletes or rolls back the local QSO.

## Why Forge owns Wavelog

The Pi already has a typed Home Platform boundary and a background contact synchronization service. Wavelog-specific concerns therefore remain on Forge:

- bearer-token authentication;
- Wavelog endpoint behavior;
- station-location discovery;
- ADIF conversion;
- provider error interpretation;
- remote duplicate handling;
- durable remote idempotency bookkeeping.

The Wavelog integration runs as a small independent Forge service rather than being embedded in the spot/weather aggregator. That preserves the same trust boundary while preventing a bad Wavelog credential or Wavelog outage from taking down spot/weather ingestion.

The private default Rolling Thunder Home Platform URL for this feature is:

```text
http://192.168.9.170:8767
```

This service must remain reachable only through the existing trusted private/VPN network policy. It is not intended to be Internet-facing.

## Wavelog target safety

The required target is:

- Station Logbook: `KI5VNB Main`
- Station Location: `Mobile`

The Wavelog v2 QSO API writes to a **Station Location** using `station_profile_id`. Rolling Thunder never stores or assumes that numeric ID. Forge calls the Wavelog station-list endpoint and requires exactly one station location whose name is `Mobile`, then uses the returned numeric ID for the QSO import.

If `Mobile` is absent, duplicated, the response is malformed, authentication fails, or Wavelog is unavailable, Forge rejects the synchronization attempt. The local QSO remains unsynchronized and is retried later.

Wavelog's v2 station resource does not expose the enclosing Station Logbook name/link as part of the station object. Consequently, Forge can enforce the `Mobile` station-location identity programmatically, but the `Mobile` -> `KI5VNB Main` Station Logbook association is a Wavelog server-side configuration invariant. The deployment configuration records the expected logbook name, and real acceptance must verify in the Wavelog UI that the resolved `Mobile` location belongs to and displays inside `KI5VNB Main` before this feature is merged or treated as production-ready.

This limitation does **not** permit a fallback to Home or any other station location. Forge never chooses another profile when `Mobile` cannot be resolved exactly.

## Wavelog API and token

Forge uses Wavelog API v2 with bearer-token authentication.

Required token scopes for production acceptance are:

- `station:read` — resolve the `Mobile` station profile;
- `qso:write` — import the QSO;
- `qso:read` — verify the controlled acceptance QSO and duplicate behavior.

The token is supplied only through the process environment:

```text
ROLLING_THUNDER_WAVELOG_V2_TOKEN
```

Do not put a Wavelog token, password, API key, or other credential in Git, YAML examples, issue comments, PR comments, command history, or acceptance output pasted into GitHub.

## Contact mapping

Forge maps the immutable local `Contact` into one deterministic ADIF record. The ADIF import is submitted with the resolved `Mobile` `station_profile_id`.

| Rolling Thunder | Wavelog / ADIF |
| --- | --- |
| `callsign` | `CALL` |
| `started_at` | UTC `QSO_DATE` + `TIME_ON` |
| `frequency_hz` | `FREQ` in ADIF MHz |
| derived band | `BAND` |
| `mode` | `MODE`; USB/LSB are represented as `MODE=SSB` plus `SUBMODE` |
| `rst_sent` | `RST_SENT` |
| `rst_received` | `RST_RCVD` |
| `grid` | `GRIDSQUARE` when known |
| `my_grid` | `MY_GRIDSQUARE` when known |
| `pota_reference` | `POTA_REF` when present |
| `notes` | `NOTES` when present |

Missing optional metadata never makes local logging fail. QRZ enrichment failure completes as an optional-enrichment miss, so QRZ unavailability does not indefinitely block Wavelog synchronization.

Country shown by the LOG panel is display-only. It is resolved conservatively from an offline callsign-prefix table and falls back to `—`; rendering never performs a network lookup and country is not a prerequisite for Wavelog synchronization.

## Idempotency and uncertain outcomes

The local Rolling Thunder `contact_id` UUID is the stable idempotency identity from creation through Wavelog synchronization.

The Pi sends:

```text
Idempotency-Key: <contact_id UUID>
```

Forge requires that header to match the `contact_id` in the request body. Forge then records, transactionally, a ledger row containing:

- the UUID;
- a SHA-256 of the stable Wavelog-bound payload plus station profile ID;
- the resolved Wavelog station profile ID;
- pending/synchronized certainty state;
- the final Wavelog import disposition and timestamps.

A repeated UUID with changed QSO data or a changed target station profile is rejected rather than silently mutating/replaying the remote contact.

Forge writes the pending ledger claim **before** calling Wavelog. After Wavelog reports the record imported or skipped as a duplicate, Forge marks the UUID synchronized.

This makes the important lost-response case safe:

1. Forge durably claims UUID A.
2. Wavelog imports UUID A's QSO.
3. The response is lost or Forge restarts before its ledger can be marked synchronized.
4. Rolling Thunder retries UUID A.
5. Forge sees the durable pending claim and reissues the same deterministic QSO.
6. Wavelog's normal duplicate detection reports it skipped as a duplicate.
7. Forge marks UUID A synchronized and returns `already_exists` to the Pi.

A duplicate outcome is therefore a successful synchronization result, not an error.

Once Forge's ledger says the UUID is synchronized, subsequent retries/manual Sync presses return `already_exists` without another Wavelog write.

## Pi synchronization behavior

`ContactSyncService` retains the existing restart-safe retry metadata and bounded exponential backoff. Checkpoint #190 adds a single-flight lock so a periodic retry and a manual request cannot overlap.

Synchronization is opportunistic rather than dependent on a daily timer:

- a successful local contact commit requests background synchronization immediately;
- existing unsynchronized contacts detected at application startup request synchronization;
- a newly observed pending contact requests synchronization;
- periodic synchronization remains a secondary retry mechanism;
- Context Button #1 on the LOG panel requests synchronization immediately;
- failed contacts retain restart-safe retry metadata and retry only when due.

If a synchronization run is already in progress, another manual/periodic request does not create another overlapping worker.

## LOG panel

LOG is a normal dashboard context and participates in the existing context-navigation cycle. It does not redefine the global meaning of navigation, Back, encoder movement, Context Button #2, or unrelated controls.

The panel displays only the newest ten locally stored Rolling Thunder contacts, newest first. Each row includes:

- UTC date/time;
- callsign;
- band;
- conservative offline country abbreviation or `—`;
- synchronization state using both a symbol/text label and color.

Status labels are:

- `✓ SYNC` — synchronized;
- `○ WAIT` — pending/unsynchronized;
- `! FAIL` — a failed attempt awaiting retry/operator visibility.

The header includes:

```text
UNSYNCED <count> / TOTAL <count>
```

`UNSYNCED` counts every locally stored contact whose synchronization state is not `synchronized`, including failed contacts.

Context Button #1 is `Sync Unsynced / Sync Now`. It submits work to a single-worker executor and returns immediately. Tk refresh reads only the controller's immutable snapshot.

## Local retention

The local Rolling Thunder log is bounded without sacrificing unsynchronized data:

1. Up to 5,000 contacts are retained normally.
2. Only after total stored contacts exceeds 5,000 does retention run.
3. The repository opens one immediate transaction and selects the oldest, at most 1,000 rows whose state is exactly `synchronized`.
4. It deletes only those selected synchronized UUIDs and commits atomically.
5. Pending, failed, or otherwise uncertain contacts are never deleted for retention.
6. If fewer than 1,000 synchronized rows are available, only those provably synchronized rows are removed.

It is valid for the local database to remain over 5,000 rows when preservation of unsynchronized/failed contacts requires it.

The latest-ten panel query remains newest-first after retention.

## Backup and recovery semantics

The Pi SQLite database remains the local operational record. The Forge ledger is a separate remote-idempotency record and should be included in Forge backup coverage.

Important recovery behavior:

- restoring an older Pi backup can reintroduce a contact whose local state says pending even though Wavelog already has it;
- Forge's durable UUID ledger prevents another Wavelog write when that UUID was previously recorded synchronized;
- if the Forge ledger was also rolled back or lost, Wavelog duplicate detection is the secondary defense for the same deterministic QSO;
- restoring an older Forge ledger must never be interpreted as proof that Wavelog lacks a QSO;
- retention never deletes contacts whose remote state is uncertain, so pruning cannot turn an unresolved synchronization problem into data loss.

Do not delete or recreate the Forge ledger as a routine troubleshooting step. Preserve and back it up like application state.

## Forge deployment

Install the package and configuration using the same protected `/opt/rolling-thunder-forge` deployment model described in `FORGE_DEPLOYMENT.md`.

Files introduced for this service:

```text
deploy/systemd/rolling-thunder-forge-contact-sync.service
config/forge-contact-sync.example.yaml
```

Recommended production paths:

```text
/etc/rolling-thunder/forge-contact-sync.yaml
/etc/rolling-thunder/forge-contact-sync.env
/var/lib/rolling-thunder/forge-contact-sync.db
```

The environment file should be readable only by root/service administration and contain:

```text
ROLLING_THUNDER_WAVELOG_V2_TOKEN=<token>
```

The example systemd unit uses `StateDirectory=rolling-thunder`, `ProtectSystem=strict`, and permits state writes only below `/var/lib/rolling-thunder`.

After installing or changing the unit/configuration:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now rolling-thunder-forge-contact-sync.service
sudo systemctl status --no-pager rolling-thunder-forge-contact-sync.service
```

Do not publish port 8767 to the Internet. Firewall it consistently with the existing private RadioLAN/CarLAN policy.

## Pi configuration

On `anvilmobile`, enable the existing Home Platform client and point it to Forge contact synchronization, not directly to Wavelog:

```yaml
home_platform:
  enabled: true
  base_url: "http://192.168.9.170:8767"
  request_timeout_s: 5.0
  sync_interval_s: 30.0
  sync_batch_size: 25
  retry_initial_delay_s: 5.0
  retry_max_delay_s: 300.0
```

There is intentionally no Wavelog token or Wavelog URL in Pi configuration.

## Health and failure interpretation

`GET /health` verifies that Forge can authenticate to Wavelog and resolve exactly one `Mobile` station location. Health failure does not make local logging fail.

Common failure classes:

- **Forge unreachable / WireGuard down:** Pi records failed sync state/retry metadata; local QSO remains.
- **Wavelog unreachable / timeout:** Forge leaves its ledger pending; Pi retries later.
- **401/403:** wrong/expired token or missing scope; local QSO remains unsynchronized.
- **missing or duplicate `Mobile`:** Forge refuses to choose another location.
- **malformed Wavelog response:** synchronization fails safely; local QSO remains.
- **timeout after possible Wavelog success:** retry is safe through deterministic payload + Wavelog duplicate checking.
- **Forge restart:** durable ledger survives and prevents replay of known synchronized UUIDs.
- **Pi restart:** pending/failed contact and retry metadata survive in SQLite.
- **repeated manual Sync:** single-flight worker and Forge UUID ledger prevent overlapping/replayed writes.
- **database error:** report failure; never pretend synchronization succeeded.

## Real acceptance gate

Mocks and CI are necessary but not sufficient. Before merge, acceptance must use:

1. the actual `anvilmobile` installation;
2. the production Forge host;
3. the real Wavelog instance at `http://192.168.9.170:8086`;
4. a controlled test QSO with an unmistakable timestamp/callsign or note;
5. Wavelog verification that the QSO is under Station Location `Mobile` and appears in Station Logbook `KI5VNB Main`;
6. LOG panel verification that the local row changes from unsynchronized to synchronized;
7. one deliberate safe offline/retry case;
8. a repeated Sync/retry proving there is still exactly one Wavelog QSO.

The PR remains draft until this installed acceptance is complete.
