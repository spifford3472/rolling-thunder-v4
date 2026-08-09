# Forge Mobile Location Write API

## Purpose

Checkpoint #160 extends the existing Forge process and private listener with one bounded write endpoint for the latest vehicle location. It does not create another daemon, listener, database file, weather refresh path, Pi publisher, or radio-control authority.

The endpoint is:

```text
PUT /api/v1/mobile-location
```

Production remains on the existing private listener:

```text
192.168.9.170:8766
```

## Request schema

Requests must use `Content-Type: application/json`, a declared `Content-Length`, and a body no larger than 4096 bytes.

Version 1 uses:

```json
{
  "api_schema_version": "1",
  "location": {
    "latitude": 39.529,
    "longitude": -84.064,
    "fix_at": "2026-08-08T23:30:00Z",
    "received_at": "2026-08-08T23:30:01Z",
    "speed_m_s": 18.5,
    "heading_degrees": 90.0
  }
}
```

`speed_m_s` and `heading_degrees` are optional. All other fields are required.

Validation rules are intentionally bounded:

- latitude: -90 through +90 degrees
- longitude: -180 through +180 degrees
- timestamps must be timezone-aware and are normalized to UTC
- `fix_at` must not be later than `received_at`
- `fix_at` may be at most 30 seconds older than `received_at`
- `received_at` may be at most 120 seconds old relative to Forge UTC
- `received_at` may be at most 30 seconds ahead of Forge UTC to tolerate modest clock skew
- speed, when present: 0 through 100 m/s
- heading, when present: 0 inclusive through 360 exclusive degrees
- a newly retained record must strictly advance both `fix_at` and `received_at`
- unknown fields are rejected
- unsupported API schema versions are rejected

The timestamps describe the mobile observation received by the Pi, not a Forge weather-provider timestamp.

## Success response

A successful write is acknowledged only after SQLite commit:

```json
{
  "api_schema_version": "1",
  "revision": 7,
  "location": {
    "latitude": 39.529,
    "longitude": -84.064,
    "fix_at": "2026-08-08T23:30:00Z",
    "received_at": "2026-08-08T23:30:01Z",
    "speed_m_s": 18.5,
    "heading_degrees": 90.0
  }
}
```

The in-memory retained state is never advanced before persistence succeeds.

## Rejection behavior

The write path rejects malformed or unsupported requests without replacing the last accepted location.

Important status codes include:

- `400` malformed JSON, invalid JSON root, invalid content length, or unsupported schema version
- `405` method not allowed; only `PUT` is supported for this path
- `409` stale or implausibly timed location
- `411` missing request length/body
- `413` payload larger than 4096 bytes
- `415` media type other than JSON
- `422` invalid location fields or impossible coordinates/motion values
- `503` retained-location persistence unavailable

A rejected request does not trigger POTA, DXSpider, QRZ, weather, or any other provider refresh.

## Persistence

The retained location is stored in the same configured Forge SQLite file as spot state, but in independent mobile-location tables:

```text
forge_mobile_location_schema_metadata
forge_mobile_location
```

The location table is a singleton row with a monotonically increasing revision. Replacement uses `BEGIN IMMEDIATE`, compares the candidate against the currently retained timestamps inside the transaction, and commits before the new state is published in memory.

This keeps stale concurrent writes from overwriting a newer accepted location.

The existing spot snapshot schema and `/api/v1/spots` storage behavior are unchanged.

## Private-network security decision

Checkpoint #160 deliberately does **not** add TLS or an application bearer token. The existing routed private network remains the authorization boundary for the whole Forge API.

The supported mobile path remains:

```text
anvilmobile / CarLAN
    -> WireGuard
    -> RadioLAN
    -> 192.168.9.170:8766
```

This decision is acceptable only while all of the following remain true:

- Forge binds specifically to `192.168.9.170`, never `0.0.0.0`
- TCP 8766 has no public Internet port forward
- UPnP does not expose the listener
- OPNsense/WireGuard policy limits which routed private networks can reach the listener
- the listener is not made reachable from untrusted Wi-Fi, guest networks, or arbitrary LAN segments

The risk changes materially from the previous read-only API: **any host able to reach TCP 8766 can now submit a candidate mobile location**. A successful malicious write could poison location-dependent map/weather intelligence in later checkpoints even though it cannot directly control a radio.

Therefore wider exposure is unsupported. Before this endpoint is exposed outside the existing trusted routed network, application authentication and transport protection must be designed and deployed. Network-only trust must not silently become Internet-facing trust.

No credential is placed in YAML or committed to Git for checkpoint #160 because no application credential exists in this checkpoint.

## Radio safety boundary

The mobile-location endpoint stores location only. Forge still has no CAT, frequency/mode, PTT/MOX, keying, tuner, power, or transmit authority.

## Production smoke test

After deploying an accepted commit to the existing Forge service, preserve the current systemd process and listener. Do not launch a second process against the production SQLite database.

First confirm existing reads remain healthy:

```bash
curl -fsS http://192.168.9.170:8766/api/v1/health
curl -fsS http://192.168.9.170:8766/api/v1/spots >/dev/null
```

Then submit one current, known-safe location sample with timestamps generated immediately before the request. Example shell shape:

```bash
NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

curl -i \
  -X PUT \
  -H 'Content-Type: application/json' \
  --data "{\"api_schema_version\":\"1\",\"location\":{\"latitude\":39.529,\"longitude\":-84.064,\"fix_at\":\"$NOW\",\"received_at\":\"$NOW\"}}" \
  http://192.168.9.170:8766/api/v1/mobile-location
```

Acceptance requires HTTP 200 with revision 1 or greater, the submitted location returned in the acknowledgement, existing health/spots endpoints still working, the production process remaining under the `rollingthunder` account, and no new listener or daemon.

A deliberately stale second request should return HTTP 409 while the database retains the previously accepted row.

## Scope

Checkpoint #160 does not implement the Pi publisher. That is checkpoint #161. It also does not fetch weather, render map/weather UI, add repeater data, or change CAT behavior.
