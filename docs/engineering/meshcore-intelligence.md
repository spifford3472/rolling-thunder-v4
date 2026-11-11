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
