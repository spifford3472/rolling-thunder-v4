# MeshCore Intelligence — public message classification (foundation)

## Status

The initial classification module is **not yet wired to a receiver, database,
UI, or RF transmitter**. It is a pure function tested using synthetic public
messages. The independent collector introduced in PR #388 remains unchanged.

## Safety and data ownership

The independent MeshCore service is the only approved owner of USB serial
input and observation persistence. Its present inbound observer handles
advertisements/path notifications and signal-only metrics. It **does not expose
verified public channel messages or preserve their text**. No caller may treat
a raw 0x88 frame, an advertised contact, or a signal sample as a public traffic
message. Raw packet capture or private-message storage is not authorized.

`meshcore_incident_classification.py` requires an already verified
`PublicMessage`, plus a policy containing **actual configured channel IDs**.
The textual labels `#traffic` and `#skywarn` are not sufficient identifiers.
There are no default channel IDs. The module performs no network, geocoding,
SQLite, serial, UI, CAT, or RF operations. It returns no geocoded location or
route relevance. It rejects overlong, empty, malformed, or unsupported input.

The accepted categories are deterministic keyword matches, not trustworthy
incident confirmations. `rule_match` is an extraction status, not a probability
of truth. An unclassified message is not a hazard. Never announce an alert solely
because this parser returned a category.

## Future intake contract (separately reviewed)

Before live classification can be enabled:

1. Verify the specific installed firmware and pushed event protocol can expose
   individual **public channel messages** without triggering a transmission.
2. Identify configured channel IDs and prove their membership and provenance.
   Channel strings must not be treated as proof of public provenance.
3. Explicitly exclude direct messages, private/encrypted content and raw packet
   storage. Bound payloads and store only approved fields under documented
   retention/backup rules.
4. Provide a bounded asynchronous intake to this pure function and a separate
   incident repository with source references, deduplication, expiration and
   independent corroboration rules.
5. Establish geographic matching using only existing published GPS, appropriately
   cached geocoding, and conservative route-confidence labels.
6. Obtain separate explicit operator permission before **any** host-generated
   MeshCore transmission, including command replies or accident reports.

The existing read-only Unix socket health/nodes/signals API is unchanged.
There is no new port, systemd job, feature flag, migration, or deployment action
for this initial module.

## Tests

`tests/test_meshcore_incident_classification.py` covers traffic/SKYWARN
categories, explicit unknowns, public channel allowlisting, untrusted input,
bounded text, timezone validation, and road/direction extraction without a
fabricated geographic location.

This foundation is not field acceptance; actual driving/RF testing remains
pending after a separately validated integration.

## Geographic relevance foundation

`meshcore_geographic_relevance.py` is a pure geographic utility, not a second GPS acquisition pipeline. A caller may offer timestamped points from the established Rolling Thunder GPS publisher no more frequently than 1 Hz. A maximum six-element, five-second in-memory history derives a heading only when displacement exceeds GPS jitter and implies plausible speed. Verified course over ground takes precedence when reported speed confirms movement; stationary, stale, invalid, or implausible fixes fail closed.

A geographic incident candidate requires an independently trusted geocode; the classifier does not create one. Distances/bearings are informational, **not road or route matching**. An incident only becomes `ahead_confirmed_route` when a future, independent map-matching service positively verifies the road/travel direction and supplies `route_confirmed=True`. Otherwise proximity may mean `possibly_ahead`, `behind`, `nearby_route_unknown`, `not_relevant`, or `insufficient_information`. A future system must confirm freshness and accuracy of incident location, and must not infer truth from a public report.

This domain module is deliberately not composed into the UI, database, or collector yet. Unit tests do not establish field GPS or dashboard acceptance.

## Observation analytics foundation

`meshcore_network_analytics.py` provides bounded read-only aggregate queries over the existing isolated MeshCore schema-2 SQLite history. It does not create a new database, alter tables, migrate contact storage, or open serial/GPS devices. Requests use an explicit UTC interval (maximum 31 days), constrained receiver-location cell count (maximum 200), query-only SQLite access, and fail closed if the database is missing or uses an unsupported schema.

Counters distinguish distinct observed identities, identities currently carrying a verified repeater type, first-seen identities, observation event counts, and independent unattributed RSSI/SNR sample counts. A currently advertised repeater role cannot prove it performed a relay, and these counts cannot establish uptime, full coverage, or total regional node populations.

Coarse coordinate cells represent **receiver locations where observations or signal samples were recorded**, not coordinates of the MeshCore nodes. Unsampled routes and periods with no activity are not evidence of no coverage. No raw private RF packet content is queried. A future bounded service API and dashboard will be needed to render the summaries; this module is not yet composed into production.

## Read-only private service API

The independent collector's existing permission-restricted Unix-socket HTTP service now exposes `GET /v1/activity` as an additional **read-only** endpoint. It requires no TCP listener, extra process, new filesystem path, token, or schema migration. The response schema is `meshcore/activity/v1`; it reports a rolling 24-hour UTC interval, observed node/repeater-role/new-identity/event/signal counters and at most 25 coarse **receiver** reception cells. The query is performed by the local HTTP worker, not the Tkinter thread; it fails with HTTP 503 if collector history is unavailable or incompatible. Unknown paths are 404; mutation requests remain 405.

The endpoint does not expose raw RF payloads, channel secrets, private messages, or any controls. It does not claim repeater availability or node physical distance. A future dashboard/SCOUT client must respect the existing protected socket authorization and bind this schema to an immutable state adapter rather than reading SQLite directly.

## Issue #395: exact firmware audit and offline channel intake gate (2026-11-11)

The installed Heltec V4.3 companion build reports v1.16.0-07a3ca9. The upstream `companion-v1.16.0` tag resolves to immutable commit `07a3ca9e05b0ab23b878200b2c44b04e08131972`. Source reviewed: `examples/companion_radio/MyMesh.cpp` from that commit, specifically `CMD_SYNC_NEXT_MESSAGE` around line 1354, `getFromOfflineQueue` around line 243, `CMD_GET_CHANNEL` around line 1683, and `onChannelMessageRecv` around line 541. Firmware header `src/helpers/TxtDataHelpers.h` defines `TXT_TYPE_PLAIN=0`. Source: https://github.com/meshcore-dev/MeshCore/tree/07a3ca9e05b0ab23b878200b2c44b04e08131972.

**Finding 1 — local-only dequeue is not an RF transmission:** `CMD_SYNC_NEXT_MESSAGE` (serial payload `0A`) reads the first saved frame and emits a serial reply `0x08` or `0x11` for channel text, `0x07`/`0x10` for private contact messages, or `0x0A` when empty. This handler contains no application-requested MeshCore radio send. It still cannot be used by the present receive-only collector without a separate explicit transport design/change.

**Finding 2 — dequeue is destructive across *all* message types:** `getFromOfflineQueue` removes the oldest queued frame **before** the host can inspect its channel or privacy. It does not support a channel-filtered read or peek, and the same queue contains contact messages. A host that discards private replies would irrevocably consume other applications' unread DMs. This is a **BLOCKER** to automatically enabling the command until the owner explicitly establishes a privacy-preserving dedicated-device policy or another tested no-loss handoff. Do not describe “RF receive-only” as equivalent to “host non-mutating.”

**Finding 3 — channel info contains the secret:** `CMD_GET_CHANNEL` (0x1F followed by slot) returns `0x12`, index, 32-byte name, **16-byte secret**. Logs, database, UI and diagnostics must never contain that secret. A channel called `#traffic` is not intrinsically a verified public feed. The operator must explicitly approve a known-public index/name, with an externally calculated SHA-256 key fingerprint. The dynamic firmware reply must match all three before any content is accepted. Shared/private-key channels may exist under public-sounding labels; they must be excluded unless independently confirmed suitable for public intake.

**Implemented foundation:** `meshcore_public_intake_protocol.py` verifies an exact firmware channel-info response against an operator-approved slot/name/key fingerprint using constant-time comparison of the fingerprint, then decodes only version 1 and V3 plain text response frames from that exact verified slot. Legacy 0x08 and V3 0x11 text offsets are distinct; V3 SNR is signed quarter-dB, sender-supplied timestamps are untrusted, 0xFF on receive is a direct packet (not an outbound route), and sender identity is **not authenticated** by these frames. Private/contact 0x07/0x10 and binary data 0x1B never become public text. The parser keeps neither raw keys nor raw frame data, performs no serial or persistence operations and is **not connected to the production service**. No explicit operator approval configuration or command scheduler has yet been installed. Existing collector and API continue to function unchanged.

**Required next implementation gate:** design a bounded, privacy-respecting drain policy that cannot silently lose private messages, confirm actual public-channel metadata from the installed hardware without logging secrets, audit serial framing/reconnect/ACK behavior, add disabled-by-default protected configuration and deterministic serial fakes, then stage parked operator acceptance. A secure MeshCore C2 design must account for any shared offline queue consumers. No new RF messages or transmission authority are authorized. A classification alert also requires a trustworthy sender attribution policy and incident deduplication; firmware “sender text” cannot be treated as verified identity.

## Issue #395 — message broker supersedes prior no-dequeue plan

The owner accepted the narrow firmware dequeue-to-SQLite-commit power-loss window. The adopted design **preserves** dequeued private/contact replies in a protected personal stream rather than discarding them; verified public-channel text and unverified/binary frames have distinct public and quarantine streams. Every consumer has an independent durable acknowledgement cursor. The optional single USB owner may issue only audited *local* GET_CHANNEL (0x1F) and SYNC_NEXT_MESSAGE (0x0A) commands; there is no new radio/RF transmit authority. Activation remains disabled by default until a protected configuration with real channel identities and parked acceptance exists. See `meshcore-message-broker.md` for current source, limits and rollback; this supersedes the earlier firmware-fork recommendation.

## Traffic GPS and geographic relevance — source-only analysis (2026-11-11)

This additive, pure-code slice is not composed into the live traffic worker,
collector, Tkinter, or SCOUT. It never changes broker cursors, QSO storage,
radio settings, navigation, or RF behavior.

- meshcore_traffic_georeferences.py extracts bounded canonical route, exit,
  mile-marker and travel direction from verified public-channel classified
  incidents. Unknown, conflicting and underspecified text fails closed.
- meshcore_traffic_gps_samples.py reads only the existing published GPS
  snapshot using the existing bridge, at most 1 Hz, with no new receiver.
  The published snapshot currently has no speed or course, so validated
  displacement over 2–5 seconds must provide any derived heading.
- meshcore_traffic_geocoding.py is an injected, **disabled-by-default**
  provider-neutral adapter. No HTTP code or default provider exists.
  It enforces a maximum number of attempted queries, >=2-second spacing,
  and positive/negative cached results. Only exact site-specific,
  matching road/exit evidence may be accepted; road centroids are rejected.
- meshcore_traffic_relevance.py conservatively combines qualified traffic,
  independently supplied site evidence and fresh GPS (accuracy <=30 m).
  It rejects reports older than ten minutes for *analysis*, not historical
  retention. Multiple existing samples are required even if external
  course/speed were available. Result states include approaching on
  independently verified route, possibly approaching, behind, nearby
  route unknown, not relevant, and insufficient information. It never
  asserts that an incident actually happened.
- meshcore_traffic_analysis.py joins the above boundaries. An unclassified,
  expired, ambiguous or poor-GPS report triggers no provider lookup.
  Driver alerts are unconditionally forbidden by this source milestone.

Provider policy: the OSMF public Nominatim service limits lookup rates,
expects meaningful User-Agent, caching, attribution and discourages
periodic/background bulk lookups. This source does not issue any such calls.
Policy: https://operations.osmfoundation.org/policies/nominatim/
An approved, separately reviewed Forge/provider implementation or licensed
local geographic dataset must supply trustworthy point/road evidence. A
roadway name or arbitrary highway center is not a crash location.

This is **NOT a fully field-accepted geographic alert pipeline**.
Still gated: approved geographic provider, source-specific road alignment,
read-only durable candidate projection, inspected persistence, controlled
service composition, actual verified #traffic reception, representative
driving GPS/FT8/UI performance and operator notification authority.
No production deployment of this source is required for existing worker.
