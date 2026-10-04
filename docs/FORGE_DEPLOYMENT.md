# Forge Service Production Deployment

## Purpose

This document defines the supported production deployment for the Rolling Thunder Forge service established by checkpoint 8 of GitHub issue #148 and extended by checkpoints #160, #161, and #162.

Forge remains one independent backend process on the existing private listener. It aggregates and retains POTA/DX spot state, accepts one bounded latest-mobile-location write, and can now retain provider-neutral weather derived from that latest accepted mobile location. It has no radio, CAT, receive-tuning, PTT, MOX, keying, tuner, power, contact logging, or Tkinter authority.

Detailed API contracts are documented in:

- `docs/FORGE_MOBILE_LOCATION_API.md`
- `docs/PI_FORGE_LOCATION_PUBLISHER.md`
- `docs/FORGE_WEATHER_API.md`

## Production host and listener

The supported host is `forge` on the RadioLAN address `192.168.9.170`.

The production REST listener is:

```text
192.168.9.170:8766
```

Port `8765` is not used by the production Forge service. The service must not bind to `0.0.0.0`.

Checkpoint #162 does not add another listener or daemon. Weather uses the same process, systemd unit, listener, and SQLite file as the existing Forge service.

## Production layout

| Purpose | Path |
| --- | --- |
| Application checkout | `/opt/rolling-thunder-forge` |
| Python virtual environment | `/opt/rolling-thunder-forge/.venv` |
| Production YAML | `/etc/rolling-thunder/forge-spots.yaml` |
| Optional environment secrets | `/etc/rolling-thunder/forge-spots.env` |
| Persistent SQLite database | `/var/lib/rolling-thunder/forge-spots.db` |
| systemd unit | `/etc/systemd/system/rolling-thunder-forge-spots.service` |
| journal | `journalctl -u rolling-thunder-forge-spots.service` |

The application checkout must be installed from a known Git commit. Production deployment must never be performed from an uncommitted working tree.

## Service account

The service runs as the dedicated system account `rollingthunder` with home `/nonexistent` and shell `/usr/sbin/nologin`.

The systemd unit uses:

```text
User=rollingthunder
Group=rollingthunder
```

The service must not run as `root` or the interactive `geoff` account.

The application tree is owned by `root:rollingthunder`; the service account has read/execute access but does not own the source tree. Persistent state is owned by `rollingthunder:rollingthunder` so the service can update SQLite without write access to application source or configuration.

## Configuration

The tracked production template is:

```text
config/forge-spots.production.example.yaml
```

The deployed configuration is:

```text
/etc/rolling-thunder/forge-spots.yaml
```

The production database path is:

```text
/var/lib/rolling-thunder/forge-spots.db
```

The accepted base deployment enables POTA and DXSpider, uses a 60-second spot aggregation refresh interval with refresh-on-start enabled, and leaves QRZ enrichment disabled until credentials are intentionally provisioned.

### Weather configuration

Weather is deliberately disabled by the model default so an old Forge YAML file does not begin new outbound provider traffic merely because the package was upgraded. Checkpoint #162 production adoption explicitly enables weather in the deployed YAML.

Supported production shape:

```yaml
weather:
  enabled: true
  endpoint: https://api.open-meteo.com/v1/forecast
  request_timeout_s: 5.0
  check_interval_s: 60.0
  max_forecast_age_s: 1800.0
  movement_refresh_km: 10.0
  refresh_on_start: true
```

`check_interval_s` controls how frequently the background weather worker evaluates whether refresh is required; it does not force a provider call every interval. A provider refresh occurs when no complete forecast exists, the retained forecast reaches the configured maximum age, or the latest retained mobile location moves at least the configured distance from the forecast coordinates.

Weather adds no second database path. Spot snapshots, retained mobile location, and retained weather use independent schema/table families inside the same configured Forge SQLite file.

DXSpider login uses the licensed operator callsign configured in production YAML.

## Open-Meteo provider and attribution

Checkpoint #162 uses Open-Meteo only behind the typed Forge weather-provider boundary. Provider-specific weather codes are normalized into Rolling Thunder-owned condition/icon tokens before persistence and API publication.

Open-Meteo API data require attribution under CC BY 4.0. Forge therefore includes provider name, attribution text/link, and license metadata inside every retained weather snapshot. Downstream UI work must display attribution when Open-Meteo-derived data are shown.

See `docs/FORGE_WEATHER_API.md` for the normalized fields and attribution metadata.

No Open-Meteo API credential is stored in Forge YAML for the initial integration.

## QRZ credentials

QRZ credentials must never be committed to Git or stored in Forge YAML.

If QRZ enrichment is enabled, credentials are provided only through `/etc/rolling-thunder/forge-spots.env` using:

```text
ROLLING_THUNDER_QRZ_USERNAME
ROLLING_THUNDER_QRZ_PASSWORD
```

Recommended ownership and mode for the environment file are `root:rollingthunder` and `0640`. When QRZ is disabled the file may remain empty.

The retained mobile-location endpoint still does not use an application-layer credential; the routed private network remains the authorization boundary described below.

## systemd service

The tracked unit source is:

```text
deploy/systemd/rolling-thunder-forge-spots.service
```

The installed unit is:

```text
/etc/systemd/system/rolling-thunder-forge-spots.service
```

The unit uses `Restart=on-failure`, a five-second restart delay, `NoNewPrivileges=true`, an empty capability bounding set, private temporary storage, read-only system protection, restricted kernel/control-group access, and `StateDirectory=rolling-thunder`.

### Lifecycle commands

```bash
systemctl status rolling-thunder-forge-spots.service
sudo systemctl start rolling-thunder-forge-spots.service
sudo systemctl stop rolling-thunder-forge-spots.service
sudo systemctl restart rolling-thunder-forge-spots.service
sudo systemctl enable rolling-thunder-forge-spots.service
sudo systemctl disable rolling-thunder-forge-spots.service
```

The supported production state is both `active` and `enabled`.

## Logs and diagnostics

Recent journal:

```bash
sudo journalctl -u rolling-thunder-forge-spots.service -n 50 --no-pager
```

Follow logs:

```bash
sudo journalctl -u rolling-thunder-forge-spots.service -f
```

Listener check:

```bash
ss -lntp | grep '192.168.9.170:8766'
```

Health check:

```bash
curl -fsS http://192.168.9.170:8766/api/v1/health
```

Spot snapshot:

```bash
curl -fsS http://192.168.9.170:8766/api/v1/spots
```

Retained weather:

```bash
curl -fsS http://192.168.9.170:8766/api/v1/weather
```

Mobile location write endpoint:

```text
PUT http://192.168.9.170:8766/api/v1/mobile-location
```

A normal accepted #162 deployment reports the core POTA/DX service healthy and weather healthy after a retained mobile location is available and a provider refresh has succeeded. Weather failure can intentionally report `degraded` or `unavailable` without changing the existing core spot-service status.

Mobile-location write validation and all weather GET handlers perform no provider refresh work.

## Persistence and restart behavior

Forge SQLite state is independent of the Pi contact database.

The service loads the last durable Forge spot snapshot during startup so the HTTP API can serve retained spot state before the first live provider refresh. It also loads the last durable mobile-location row and the last complete retained weather snapshot from independent table families.

Current Forge table families include:

```text
forge_schema_metadata
forge_snapshot_metadata
forge_provider_slices
forge_spots

forge_mobile_location_schema_metadata
forge_mobile_location

forge_weather_schema_metadata
forge_weather_snapshot
```

Weather stores the complete normalized snapshot transactionally as one singleton retained snapshot with a monotonically increasing revision. A replacement is committed before new weather is published in memory.

Provider, transport, validation, or weather-persistence failure does not erase the previously accepted complete forecast. When a prior snapshot exists, the API continues serving it with truthful health/staleness metadata.

A weather-specific initialization/storage failure is isolated from core Forge startup. Forge may continue serving spots and mobile-location behavior while weather reports unavailable.

A restored or migrated database must pass:

```sql
PRAGMA integrity_check;
```

A live SQLite database must be copied with SQLite backup semantics rather than with an uncoordinated file copy.

## Background lifecycle boundaries

Spot aggregation and weather refresh use separate lifecycle-managed background paths.

Weather provider work:

- never executes in an HTTP request handler
- never executes on a Pi UI thread
- permits only one in-flight weather refresh
- uses explicit HTTP timeouts and bounded response size
- checks for staleness/movement before provider retrieval
- leaves prior retained weather available after failed refresh attempts

Weather does not trigger POTA/DX/QRZ provider refreshes, and a mobile-location write does not synchronously trigger weather retrieval.

## Network trust boundary

The Forge REST API provides neither TLS nor application-layer authentication. This remains an explicit private-network trust-boundary decision and is acceptable only inside the trusted private Rolling Thunder routed network.

The production listener is restricted to `192.168.9.170:8766` rather than every Forge interface.

The expected mobile path is:

```text
anvilmobile / CarLAN
    -> WireGuard
    -> RadioLAN
    -> forge:8766
```

The Pi may use hostname `forge` when approved local name resolution or its host mapping resolves that name to `192.168.9.170`.

The deployment assumes:

- no public Internet port forwarding to TCP 8766
- no UPnP exposure
- private WireGuard access for the mobile client
- OPNsense remains the routed network security boundary
- only intended private networks are allowed to reach the Forge RadioLAN API
- untrusted Wi-Fi, guest networks, and arbitrary LAN segments cannot reach TCP 8766

The Forge host does not rely on UFW for this service boundary. Security therefore depends on the specific bind address plus routed OPNsense/WireGuard policy.

Anyone who can reach TCP 8766 can read health/spots/weather and can submit a candidate retained mobile location. A malicious accepted location could poison location-dependent weather intelligence. It still cannot directly key, tune, power, or otherwise control a radio.

This network-only authorization decision is supported only for the existing trusted routed deployment. If the API is exposed outside that boundary, or untrusted clients can reach TCP 8766, TLS and application authentication must be added before that exposure is supported.

### Outbound weather traffic

When weather is explicitly enabled, Forge makes bounded HTTPS GET requests to the configured Open-Meteo endpoint. This is outbound provider traffic only; it does not expose an inbound public service and does not change the private-listener trust boundary.

## Pi failure behavior

Forge availability is not required for local Rolling Thunder operation.

Checkpoint #161 publishes valid Pi GPS fixes to Forge on a bounded background cadence, but Forge/network failure does not stop local GPS acquisition or local application operation.

If Forge, WireGuard, cellular service, weather provider, DXSpider, POTA, or the public Internet is unavailable:

- local Pi SQLite contact logging remains authoritative and available
- GPS polling continues independently
- controls and radio polling continue independently
- the Pi retains its most recent valid shared-spot snapshot
- stale/error age remains visible through Pi-side Forge state
- malformed/incomplete Forge responses do not replace durable Pi cache
- no alternate public POTA polling authority is activated when Forge mode is enabled
- weather failure does not become a prerequisite for local core functions

Pi-side consumption/rendering of the new retained weather API belongs to checkpoints #164 and #165, not #162.

## Deployment update procedure

A production update must use a known Git commit and preserve the currently working service until the new build is validated.

Recommended checkpoint #162 sequence:

1. complete and push the feature commit
2. require Ruff, strict MyPy, and full pytest on that exact head
3. create an exact Git bundle/staging artifact for Forge
4. create an SQLite-safe backup of `/var/lib/rolling-thunder/forge-spots.db`
5. stage the exact candidate under a separate application directory
6. install the candidate into a staging virtual environment
7. create a separate SQLite copy for side-by-side smoke testing
8. use a separate temporary loopback listener; never share the production SQLite file between processes
9. configure weather enabled in the side-by-side candidate
10. verify the copied database contains the retained mobile location used for weather
11. start the candidate and require existing POTA/DX health plus a real Open-Meteo weather refresh
12. verify `/api/v1/weather` contains current, at least three hourly points, solar timestamps, normalized tokens, and attribution metadata
13. verify the candidate weather snapshot survives candidate restart
14. verify copied-database `PRAGMA integrity_check` is `ok`
15. stop the side-by-side candidate
16. preserve a full rollback checkout and take a final SQLite-safe production backup
17. deliberately add/enable the production `weather:` configuration block
18. cut over the existing systemd service on the same production listener
19. require existing health/spots/mobile-location behavior to remain healthy
20. require a live production weather refresh and positive retained weather revision
21. restart the production service and verify retained weather persists
22. verify service account, working directory, exact commit, listener, same SQLite path, and integrity
23. retain rollback artifacts until checkpoint acceptance is complete

Two Forge processes must never write the same SQLite database concurrently.

## Rollback

If a newly deployed systemd service fails before acceptance:

1. stop the new service
2. confirm TCP 8766 is no longer owned by the failed/new process
3. restore the last known-good application/config/database combination
4. restart the last known-good service
5. require successful `/api/v1/health` and `/api/v1/spots` responses before declaring rollback complete

Weather tables are additive, but rollback artifacts must still be preserved because checkpoint acceptance requires a reversible complete deployment.

Never launch a rollback process while another process still owns TCP 8766.

Retained SQLite state may be used during provider outages, but a database with failed integrity validation must never be placed into service.

## Historical deployment acceptance

### Checkpoint 8

The first checkpoint-8 production deployment was accepted on Forge using application commit:

```text
9300cbc3cd8aa4335ca6071d6d8cfa80d267b8c0
```

Acceptance demonstrated dedicated service identity, production listener/storage, live POTA/DX provider refreshes, healthy REST behavior, systemd restart policy, and real Pi requests through the private routed path.

### Checkpoint #160 — retained mobile-location API

Checkpoint #160 was accepted and merged after production demonstrated:

- the same `rollingthunder` service account
- only the existing `192.168.9.170:8766` listener
- healthy existing `/api/v1/health` and `/api/v1/spots`
- one current valid `PUT /api/v1/mobile-location` accepted with a retained revision
- an identical/stale write rejected with HTTP 409 without replacing the accepted row
- retained location surviving service restart
- SQLite integrity remaining `ok`
- no new daemon, port, database, or radio authority

### Checkpoint #161 — Pi GPS publisher

Checkpoint #161 was accepted on `anvilmobile` after a real trusted GPS 3D fix was successfully published to production Forge and acknowledged as retained mobile-location revision 3. This was a Pi-side change and did not require a new Forge listener or server deployment.

## Checkpoint #162 acceptance gate

Checkpoint #162 is not production-accepted until the exact Ready-for-review head has been staged and deployed through the procedure above and demonstrates:

- existing systemd service identity and listener unchanged
- weather enabled deliberately in production configuration
- latest retained mobile location drives a real Open-Meteo refresh
- `/api/v1/weather` returns API schema version 1, positive revision, complete current/hourly/solar data, normalized condition/icon tokens, and attribution metadata
- provider work occurs outside request handlers
- existing health/spots/mobile-location behavior remains healthy
- retained weather survives Forge restart
- weather failure semantics preserve prior valid forecast
- SQLite integrity remains `ok`
- no second daemon, listener, database file, Pi authority, or radio authority

## Radio safety boundary

Deployment does not change radio authority. The Forge service has no code path for CAT, frequency or mode changes, PTT/MOX, keying, tuner control, power control, or transmit control.

All operator-confirmed receive tuning remains on the Pi and must route through `ReceiveTuningService`.


## v4.2 callsign-information service

The callsign-information overlay uses a separate on-demand Forge process so the
retained spot API continues to serve already-published state without live QRZ,
Wavelog, or weather provider work in its handlers.

Tracked deployment assets:

```text
config/forge-callsign-info.example.yaml
deploy/systemd/rolling-thunder-forge-callsign-info.service
deploy/systemd/forge-callsign-info.env.example
```

Recommended production installation:

```text
application: /opt/rolling-thunder-forge-callsign-info
config:      /etc/rolling-thunder/forge-callsign-info.yaml
secrets:     /etc/rolling-thunder/forge-callsign-info.env
listener:    192.168.9.170:8788
```

The environment file contains QRZ username/password and the Wavelog v2 bearer
token. The token must permit QSO reads as well as whatever permissions are used
by the independent contact-sync service. Secrets remain outside YAML and Git.

The Pi calls only the compact private endpoint:

```text
GET /api/v1/contact-intelligence/{callsign}
```

and may append POTA park latitude/longitude for the current activation. Forge
uses those coordinates for target weather while QRZ remains the identity source.

Health and listener checks:

```bash
curl -fsS http://192.168.9.170:8788/health
ss -lntp | grep '192.168.9.170:8788'
sudo systemctl status rolling-thunder-forge-callsign-info.service
```

The same private RadioLAN/CarLAN-over-WireGuard trust boundary applies. TCP 8788
must not be publicly forwarded or exposed through UPnP.

Failure of this independent service never blocks local logging, radio polling,
mapping, or contact Commit. A QRZ or Wavelog lookup failure returns service
unavailability so the Pi shows no callsign overlay. An empty successful Wavelog
history result is different and is presented as FIRST CONTACT. Weather is
optional enrichment: its failure does not suppress otherwise valid identity and
history data.

Open-Meteo attribution remains required. The compact response carries the
provider attribution text and the overlay displays it in muted small text.


## Known/friend directory adoption

The callsign-info unit gains its own StateDirectory for optional directory
SQLite storage. No other Forge service changes. See `KNOWN_CALLSIGNS.md` for
exact service/config/state locations, backup/rollback, private-network admin
access, and mandatory service-venv installed-package/import-path verification.
