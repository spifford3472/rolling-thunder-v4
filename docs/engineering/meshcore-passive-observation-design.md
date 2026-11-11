# MeshCore passive observation collector — architecture gate (2026-11-10)

Status: **BLOCKED pending physical receiver identity and transmit-behavior verification.** This is a design note, not an implementation or authorization to open a serial port, change radio configuration, merge, or deploy.

## Sources and observed baseline

- Root and nested `AGENTS.md` require scoped development, shared-service ownership, tests, separate merge/deployment authorization, and an explicit live-RF safety gate.
- The current shared GPS boundary is `GPSPollingService.latest_state`, surfaced as `ApplicationRuntime.latest_gps_state` (`gps_polling.py`, `application_runtime.py`). `GPSState` is immutable and carries connection state, optional `GPSPosition`, state update UTC, and GPS UTC trust metadata (`gps.py`, `domain.py`). A position includes fix state, latitude/longitude, accuracy and update UTC.
- Local durable SQLite schema migrations are centralized in `storage.py`; inspected main currently declares `CURRENT_SCHEMA_VERSION = 22`. Any implementation must recheck current main, assess growth/write contention and tests, and use additive transactional migrations.
- Read-only live inspection of `anvilmobile` on 2026-11-10 saw `/dev/ttyUSB0` (CP2105 interface 00), `/dev/ttyUSB1` (same CP2105 interface 01), `/dev/ttyUSB2` (CP2102), and `/dev/ttyUSB3` (CP2102N). The Rolling Thunder process held USB0, USB2, and USB3; USB1 was unclaimed at that instant. None is proved to be MeshCore. USB1 is **not** safe to assume available because it shares a physical USB CP2105 device with USB0. Stable `/dev/serial/by-id` paths exist; never use numeric tty enumeration for identity.
- Repository text/source search discovered only an aspirational MeshCore mention in `docs/STATUS_MESSAGES.md`, not an existing implementation.
- External protocol references: https://docs.meshcore.io/companion_protocol/ and https://github.com/meshcore-dev/meshcore_py . The official companion documentation describes push adverts and a standard initialization involving app-start, device query, time set, contacts and message synchronization; this example sequence is **not approved** for this project. Documentation itself warns it may be inaccurate. The official Python library supports serial, but its create/connect behavior and firmware role must be audited before use.

## Required safety gate

1. Identify receiver physical make/model, chipset/USB serial/interface, firmware role, version and protocol by nontransmitting evidence. Map every USB interface to its existing owner before opening anything.
2. Inspect exact firmware and library source for autonomous advertisements/relaying and any RF caused by connect, app-start, query, cache/contacts access, reconnect or event subscription. Build a deny-by-default command table and demonstrate receive-only behavior on a parked device with approved nontransmitting instrumentation.
3. Distinguish passively pushed advert/packet observations from cached contacts and active discovery. A cached contact alone is not a newly received RF observation. Do not send advert, send-message, ping, discovery, path trace, route request, administration, frequency/power, persistent settings, or firmware-flash commands.
4. If the installed firmware cannot satisfy receive-only, stop; propose a separately approved receiver-only firmware/device alternative. **No code or radio activation before this gate clears.**

## Proposed architecture after the gate clears

- A device-specific, exclusive serial adapter behind a typed `PassiveMeshcoreReceiver` interface; require a stable USB ID and feature flag OFF by default. Adapter emits whitelisted metadata events only. No general `commands` interface is exposed to application controllers.
- A bounded background ingestion worker consumes events; separate pure parser/validator and SQLite writer. UI consumes immutable counters/status only. No blocking work on Tk, no Forge dependency, no network listener and no FT-891/CAT/PTT access.
- Use the already-published `GPSState` snapshot at local receive time. Candidate freshness policy: connected, 2D/3D valid fix, finite coordinates, position UTC not future-dated and age no more than 10 seconds. Otherwise record the RF observation with null *receiver* coordinates and a typed GPS-rejection reason. Threshold is **proposed**, not yet approved; apply existing project freshness standards if a different authoritative policy is found.
- Capture local UTC receive time independent of radio payload timestamps; store peer timestamp separately only if verified. Keep actual RSSI/SNR nullable; never fabricate zero or units. Full verified public identity when present; otherwise preserve ambiguous observations without merging by short prefix. Role unknown unless explicitly transmitted. Never infer a repeater from display name.
- Store actual route bytes/identities only if contained in a passive received event. Hop count/path length is *not* a route. No active route lookup.
- No message bodies, channel keys, private keys, credentials or arbitrary payloads are retained; only limited identity, optional advertised name, type, signal metrics, position and explicitly exposed path metadata.
- Proposed SQLite tables: `meshcore_observed_nodes` (full stable identity, first/last seen, last metrics, last receiver GPS and counters), `meshcore_observations` (append-only event, receive UTC, optional stable node reference, signal metadata, receiver location and fix time, optional actual route), and a minimal diagnostics/retention metadata record. Keep ambiguous identities distinct and observations append-only. Assess common-db versus isolated DB from measured writes, backup and recovery before choosing.
- Define bounded event queue, dropped counters, batching, backoff, disconnect/replug status, idempotent stop/close, explicit corruption/unknown-frame handling, opt-in retention with storage-growth estimate, and backup/rollback. Proposed status surface: disabled, connected/degraded, last observation age, observed node count, error/dropped count. No audible announcements or distracting map.
- Test with fake serial and synthetic/recorded packets: zero RF-capable commands, parse/identity collisions, no route synthesis, GPS stale/missing/future/accuracy cases, SQLite migrations/idempotency/integrity/rollback, bounded memory, unplug/replug and shutdown, feature disabled performs zero opens/writes; run Ruff, MyPy, pytest and diff-check before PR.

## Decisions/blockers and release

- **Blocking:** identify which (if any) observed USB interface is MeshCore; obtain actual firmware role/version and source-level receive-only proof.
- **Blocking:** determine exactly which packet notifications and metrics this firmware exposes without active discovery; no claim is made that every nearby node or full route can be observed.
- **Pending:** confirm GPS freshness threshold, data retention policy, DB choice after performance/backup review.
- No source changes, migration, RF command, hardware configuration, merge or deployment authorized by this note. Follow the owner-approved implementation prompt and request separate merge and deployment approvals after testing.

## Connected-device evidence — 2026-11-10 at 22:59 EST

After the owner connected the candidate MeshCore device, read-only USB enumeration showed one additional `10c4:ea60` CP2102 USB UART at physical USB path `1-1.1.1`, currently `/dev/ttyUSB0`. No serial port was opened and no bytes were sent.

**Critical identity collision:** The new CP2102 advertises `ID_SERIAL_SHORT=0001`, which is *identical* to a pre-existing CP2102 now at physical path `1-1.1.2` (`/dev/ttyUSB3`). The standard `/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0` resolves to **ttyUSB3**, not the new candidate device. Thus a by-id rule would select the wrong radio; use validated device physical topology and/or provision a unique identifier only after explicit authorization. Do not open either during the identification gate.

Connecting the hardware caused a wider USB disconnect/re-enumeration around 22:59:29; the prior tty numbers changed (CP2105 interfaces now ttyUSB1/ttyUSB2, original CP2102 now ttyUSB3, CP2102N GPS now ttyUSB4). A kernel log included a CP210x USB -71 protocol error during this reset. The Rolling Thunder service remained active with PID 18258 and 0 restarts; current process holds ttyUSB1, ttyUSB3 and ttyUSB4. This alone does not establish full GPS/controller functional recovery. Verify published GPS/controller state non-invasively before accepting hardware.

Only chipset and connection topology have been established, **not** the device manufacturer/model, MeshCore firmware role/version, command semantics, current RF state or receive event content. USB enumeration cannot prove absence of firmware-autonomous RF transmissions. Firmware/protocol identification remains blocked until source-specific evidence or owner-provided model details can be matched safely.

**Architecture consequence:** enforce collision-resistant hardware binding; do not match CP2102 VID/PID/serial `0001` alone. Include a simulated duplicate-USB-serial test and a hot-plug/re-enumeration regression test. Account for shared hub reset and existing rolling-thunder consumer recovery.

## Owner hardware photographs — corrected identification (2026-11-10)

**Correction to the preceding working hypothesis:** The second photograph clearly shows **`V3` silk-screened on the OLED-facing side**. This is a **Heltec WiFi LoRa 32 V3** board, **not V4**. Do not use the earlier V4 identification, V4 firmware, ESP32-S3R2/PSRAM or 28 dBm specification for this device. The photographed rear board marking and separate blue GNSS module do not override the explicit V3 revision marking.

Manufacturer documentation: https://heltec.org/project/wifi-lora-32-v3/ and https://wiki.heltec.org/docs/devices/open-source-hardware/esp32-series/lora-32/wifi-lora-32-v4/ (V3/V4 comparison). V3 uses **ESP32-S3FN8**, **SX1262** and **CP2102 USB-UART**, with documented **21 ± 1 dBm maximum TX capability**. Its USB-C port and CP2102 are consistent with the newly enumerated device at physical path `1-1.1.1`, but **USB enumeration alone is not firmware identification or proof of wiring identity**.

The separate blue GNSS breakout resembles a u-blox NEO-6M-family module, but no legible exact model is confirmed from the photographs. Rolling Thunder's own published GPS snapshots remain the only permitted receiver-location source; no new GPS acquisition.

**Still blocked:** exact installed MeshCore firmware role/version, passive event notification capabilities, startup/reconnect command requirements, and firmware-autonomous RF transmit behavior remain unknown. Do not open serial, send commands or flash firmware until the read-only/reception-only evidence gate is satisfied. USB `ID_SERIAL_SHORT=0001` collides with an existing CP2102, so pinning by serial ID without an additional unambiguous identifier is unsafe. The physical USB path identifies the new device for this connection only and may change with replugging.

## Boot display evidence — version identified (2026-11-10)

Owner-provided boot OLED photograph displays `MESHCORE`, `https://meshcore.io`, **`v1.17.1`**, and **`14 Aug 2026`**. This confirms displayed firmware name, version and build date, but **does not identify firmware role** (Companion USB/BLE, repeater, room server, KISS modem, etc.) or prove transmit behavior. MeshCore's official flasher lists distinct Heltec V3 role/build variants including companion USB, repeater, room server and KISS. Reference: https://github.com/meshcore-dev/flasher.meshcore.io/blob/main/config.json .

The companion protocol documentation lists `PUSH_CODE_ADVERT=0x80` for received advertisements (full public key) and `PUSH_CODE_PATH_UPDATED=0x81` for path update notifications; implementation must test exact v1.17.1 firmware behavior and whether fields such as RSSI/SNR are exposed. Protocol: https://docs.meshcore.io/companion_protocol/ . The usual app startup sends `CMD_APP_START` and other requests, but no commands are authorized merely because the protocol defines them. Neither the presence of the MeshCore splash screen nor official protocol support establish a receive-only guarantee.

**Next nontransmitting evidence:** photograph any subsequent OLED role/status screen if present, or identify original image/installation records. Do not run a generic MeshCore client library or serial probing workflow until firmware role and autonomous TX behavior are established.

## OLED operational screen — companion-like behavior (2026-11-10)

The owner provided another photograph showing `RollingThunder`, `MSG: 0`, a battery icon, and `< Connected >`. This is consistent with a MeshCore **companion-style** status screen and an operator-configured node name, not the typical repeater telemetry screen; **exact firmware role is still a hypothesis until its firmware/image provenance or safely read device identity is verified**. `MSG: 0` is an apparent message count, **not** a passive packet counter or proof that no nodes are reachable. `Connected` indicates a connected-state presentation but cannot alone identify whether USB, Bluetooth or another app transport is connected, nor demonstrate RF reception.

Relevant background: official MeshCore companion protocol documentation at https://docs.meshcore.io/companion_protocol/ and companion radio firmware overview at https://github.com/meshcore-dev/MeshCore/wiki/Companion-Radio-Protocol . Routine companion applications may synchronize contacts/messages or send initialization commands; no standard client connection is approved for the receive-only design until exact v1.17.1 commands and autonomous TX are reviewed. Only safe read-only external examination has occurred. No serial commands or software RF transmissions have been initiated.

## Protocol investigation refinement (after OLED identification)

Official upstream companion protocol references (https://docs.meshcore.io/companion_protocol/ and https://github.com/meshcore-dev/MeshCore/wiki/Companion-Radio-Protocol) document:
- `PUSH_CODE_ADVERT (0x80)`: asynchronously received advertisement, including a 32-byte node public key. It does **not** itself promise complete signal metrics or rich name/role detail; companion applications usually fetch fuller contact metadata separately.
- `PUSH_CODE_PATH_UPDATED (0x81)`: public key notification when the saved path for a contact changes. The event alone is not evidence of a complete path.
- `CMD_GET_CONTACTS (4)`: locally requests stored contact metadata according to docs; its precise v1.17.1 behavior must be source-audited before allowlisting, including whether it can induce RF indirectly.
- `CMD_APP_START (1)`, `CMD_DEVICE_QUERY (22)`: documented host-side initialization/identity requests; still blocked until the exact build's source is reviewed for RF or persistent side effects.
- `CMD_SEND_SELF_ADVERT (7)`, send/login/status/trace and related operations intentionally trigger RF and remain forbidden.

The generic companion docs include broader synchronization and device-time-setting examples which are inappropriate to assume safe for this receive-only project. Avoid invoking generic `meshcore_py` connect/bootstrap flows without a verified operation allowlist. A pure inbound framing/parsing implementation and fixture-based tests are possible without hardware, but live serial opening remains gated on role and autonomous-TX evidence.

Even a proven receive-only **application** cannot silence firmware-originated autonomous beacons, advertisements, ACKs, or repeater traffic; firmware configuration and local RF measurements are separate prerequisites for an absolute passive guarantee. Do not infer this guarantee from the companion-like OLED `Connected` state.
