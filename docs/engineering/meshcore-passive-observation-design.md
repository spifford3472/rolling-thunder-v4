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

## Owner hardware photograph — physical board identification

The owner supplied an enclosure-open photo after disconnecting the device. The white Heltec PCB is visibly silk-screened `HTIT-WB32LAF` and bears a Heltec logo. Its pin labels include GPIO38–42 and a separate blue GNSS breakout is wired nearby, consistent with the Heltec WiFi LoRa 32 V4 family. Official Heltec WiFi LoRa 32 V4.2 data sheet: https://resource.heltec.cn/download/WiFi_LoRa_32_V4/datasheet/WiFi_LoRa_32_V4.2.0.pdf . The data sheet identifies the HTIT-WB32LAF 868–928 MHz high-band model, ESP32-S3R2, SX1262 and a nominal 28 ± 1 dBm maximum TX capability. These are **family specifications**, not confirmation of installed RF settings or firmware role; PCB revision is not proven from the shown side alone. The blue board resembles a GY-GPS6MV2 / u-blox NEO-6M-family GPS breakout; exact GNSS identity remains provisional. Per design, Rolling Thunder must never use it as a parallel GPS source.

The live candidate device at physical USB path `1-1.1.1` enumerated as a CP2102 USB-UART adapter; this is consistent with a serial bridge but **does not prove** that the USB adapter is electrically connected to the photographed board. The duplicate USB serial-ID collision remains unresolved.

Additional safety review: inspect the enclosed wiring and module power/antenna connection before attempting unattended operation. The firmware variant/version, RX notification availability, automatic RF advertisements, and any startup/companion command requirements are still unverified. Continue to forbid opening serial or transmitting until these are established.
