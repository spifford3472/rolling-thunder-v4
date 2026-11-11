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
