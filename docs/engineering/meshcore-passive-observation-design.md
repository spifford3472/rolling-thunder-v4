# MeshCore passive observation collector — architecture gate (2026-11-10)

**Current status (2026-11-11): source implementation merged in PR #385 at `bfe8a5877fa136fd28b865ef37fe629ccaa3a168`; production is NOT deployed or activated.** The collector is opt-in OFF by default, with a dedicated MeshCore-only SQLite database, shared immutable GPS, no host MeshCore command writer, and a validated physical USB-by-path serial adapter. GitHub CI #3582 passed (3,751 tests; 7 skipped). Physical activation remains **BLOCKED** by unstable USB enumeration and unverified GPS/controller recovery. Normal firmware-managed mesh RF is owner-permitted; host-initiated discovery, adverts, messages and configuration transmissions are not. Earlier sections below preserve the chronological investigation and may describe superseded proposals; this header and the latest engineering guides describe current implementation.

## Historical research record (superseded by implementation where noted)

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

## Exact upstream v1.17.1 firmware source audit and isolated offline parser

Verified upstream **`companion-v1.17.1` tag**, commit `d929643`, published 2026-08-14 (https://github.com/meshcore-dev/MeshCore/releases/tag/companion-v1.17.1). Source inspected with the GitHub connector:
- https://github.com/meshcore-dev/MeshCore/blob/companion-v1.17.1/examples/companion_radio/MyMesh.cpp
- https://github.com/meshcore-dev/MeshCore/blob/companion-v1.17.1/examples/companion_radio/main.cpp

In `MyMesh::handleCmdFrame`, `CMD_DEVICE_QUERY (22)` sets protocol version and replies with local firmware info; `CMD_APP_START (1)` replies with self info and resets a local contacts iterator; `CMD_GET_CONTACTS (4)` begins a locally stored contacts iterator. No direct RF send was visible in these three case bodies, **but this is not a full call-graph or installed-binary proof** and does not authorize using these commands. `CMD_SEND_SELF_ADVERT (7)` and general send commands must remain denied. The normal main loop starts radio, serial and sensor lifecycles, so firmware-autonomous transmissions, replay/ACK behavior, any saved repeat settings, and the exact flashed image/configuration remain unverified. Device OLED string alone does not tie installed binary to the official release artifact.

In `MyMesh::onDiscoveredContact`, existing contact advertisement notification `0x80` contains code + the *full 32-byte public key*, while `onContactPathUpdated` pushes `0x81` with the same full-key layout. Newly discovered contacts can instead send **`PUSH_CODE_NEW_ADVERT (0x8A)`** with the richer contact record. Thus a parser limited to `0x80` and `0x81` **will not capture all discovered nodes**, and must be explicitly described as an incomplete research study until `0x8A` is safely parsed. The richer record includes 32-byte public key, type, flags, path length, 64 path bytes, name and timestamps/advertised coordinates, but cannot be treated as receiver GPS, and out_path is stored contact routing metadata rather than automatically a *passively observed route*. No RSSI/SNR is directly present in 0x80/0x81.

A tiny **offline-only research prototype**, `research/meshcore_passive/passive_notifications.py`, has no USB or serial imports and handles only the two exact 33-byte push frames; other frames and malformed lengths are discarded. `research/meshcore_passive/test_passive_notifications.py` provides synthetic cases for 0x80/0x81, collision-safe full keys, unknown/payload exclusions, truncation/extension and absence of serial imports. Six tests passed using `python -m pytest -q` in a separate sandbox on 2026-11-10. This is **not** production code, not a fully validated v1.17.1 receiver, and not evidence of hardware acceptance. Ruff and MyPy were not available in that test sandbox; full repository gates and CI remain pending. No production source modules, configuration, SQLite schema, radio devices or services were modified.

**Gate status remains BLOCKED**: actual flashed image/role/USB-BLE variant, autonomous RF behavior, and v1.17.1 upstream serial *framing* and configuration-dependent broadcasts still require deeper verification. Before expanding prototype into production, inspect exact framing, `0x8A` payload and receive-only notification availability, and decide whether host UART port can be opened without causing firmware transmissions or USB hub disruptions.

## Critical RF audit finding — upstream firmware can transmit in response to reception

Inspected upstream `meshcore-dev/MeshCore` tag `companion-v1.17.1` source in `src/Mesh.cpp` and `examples/companion_radio/MyMesh.cpp`:

- `Mesh::routeDirectRecvAcks` constructs and schedules `createAck` packets with `sendPacket`, potentially also multiple extra ACKs through `getExtraAckTransmitCount`. This is **firmware-originated RF** that does not depend on a USB host sending a command.
- `Mesh::onRecvPacket` supports retransmission of direct trace/forwarded packets when `allowPacketForward` is enabled. `MyMesh::allowPacketForward` delegates to persisted `_prefs.isRepeatEn()`; constructor defaults are not evidence of the installed saved setting.
- A successfully received encrypted flood PATH can generate a reciprocal `createPathReturn` / `sendDirect` if the higher-level `onPeerPathRecv` permits it; the implementation may also override this callback. Exact conditional behavior and transport setup need deeper audit.
- `MyMesh::logRxRaw` can publish `0x88` raw RX records including SNR quantized in quarter-dB and RSSI in signed integer dBm, but also includes the raw RF payload. Do **not** persist that payload; signal values are not automatically attributable to a stable node identity.
- Therefore **receive-only on the host is not equivalent to receive-only on-air**. A safe USB event parser alone cannot satisfy the owner's strict passive RF boundary. Exact installed firmware image and settings are still unverified. No live serial device access is justified yet.

Official source evidence:
- https://github.com/meshcore-dev/MeshCore/blob/companion-v1.17.1/src/Mesh.cpp
- https://github.com/meshcore-dev/MeshCore/blob/companion-v1.17.1/examples/companion_radio/MyMesh.cpp

**Next architectural decision:** For strictly passive RF operation, investigate a dedicated TX-inhibited firmware build or receive-only radio mode that removes every transmit path, test with RF observation, and obtain separate owner authorization before flashing/reconfiguring. A stock Companion build may not qualify. If the owner approves ordinary firmware RF behavior but only forbids *application-initiated* messages, that changes the original safety requirement and must be a separate explicit scope decision. Do not silently take that interpretation.

## Owner-approved RF scope refinement (2026-11-11)

The owner explicitly clarified that ordinary MeshCore firmware-managed RF transmission is acceptable where required; the antenna is installed away from general access. **This supersedes the earlier absolute no-RF-transmission condition for firmware-originated acknowledgments/normal mesh operation only.** The Rolling Thunder collector remains an **application-passive observer** and must never initiate discovery requests, trace requests, adverts, messages, automatic configuration, broadcasts or unrelated RF transmissions. Reading pushed events and narrowly audited local-only read commands may be allowed after static audit and parked checks.

The operator's description of antenna inaccessibility does not independently establish RF-exposure compliance. Evaluate installed transmit power, frequency, duty cycle and separation as appropriate before enabling unattended operation. Normal firmware RF behavior is not evidence that the collector may initiate messages or other host-originated RF.

Revised next gate: prove stable device selection despite duplicate USB serial ID, verify framing and startup sequence from matching firmware source, verify no host-triggered RF in the exact allowlist, and check existing GPS/controller health after hub resets. Keep device adapter opt-in OFF until those tests and local backup/migration validation pass.

## Live USB stability gate — 2026-11-11 parked, read-only recheck

Anvilmobile's sysfs and USB inventory now show the MeshCore candidate at physical path `1-1.1.1` with `10c4:ea60` and generic CP2102 serial `0001`, **but no active USB configuration** (`bConfigurationValue` empty) and **no `/dev/serial/by-path` symlink for the candidate**. The connected GPS CP2102N at `1-1.1.4` likewise appears in sysfs without an active configuration or tty path. Current stable serial paths include `1-1.1.2` (original CP2102) and both interfaces of CP2105 at `1-1.2.1`, but the full pre-attachment serial inventory has not recovered.

Kernel events around 2026-11-10 23:12 EST included extensive USB `-71` protocol errors, repeated hub resets and detach/attach cycles. At 23:14, `1-1.1.1` disconnected and re-enumerated; the candidate still has no usable tty as of recheck. The Rolling Thunder systemd process is active, but this does **not** establish GPS/controller functionality. Do **not** assume a serial path is available or authorize a live read until hub power/cabling/device enumeration and existing radio/GPS/control health recover. No system services, USB state or physical connections were changed in the audit.

Next parked action requires owner-assisted USB/power troubleshooting with no unattended resets: isolate candidate hardware or upstream hub/charger, check stable re-enumeration, then verify all original GPS/controller paths and runtime states before binding a unique `/dev/serial/by-path` path. Consider a separate powered hub/port if supported; do not infer that the MeshCore alone caused the original bus faults.

## Current merged implementation and activation policy

- Application config: `meshcore_passive.enabled` defaults to false; device requires an exact verified `/dev/serial/by-path` selector; `/dev/ttyUSBN` and duplicate `by-id` names rejected.
- Composition and lifecycle: `application_runtime.py` starts a background reader only when explicitly enabled. The UART reader uses an exclusive port and parses incoming `>` + little-endian-length companion frames; **no outgoing app commands** are implemented.
- Data: `meshcore_passive.py`, `meshcore_passive_worker.py` and `meshcore_observation_repository.py` decode 0x80, 0x81 and 0x8A; store full peer identity, optional type/name and receive timestamps in **dedicated version-1 MeshCore SQLite** beside the untouched schema-22 QSO database. Existing GPS snapshots are taken at receipt. Stale/no-fix/low-quality data is represented explicitly rather than fabricating coordinates.
- Tests: full CI #3582 passed; host-side regression/fixtures are green, but no physical USB capture or parked functionality test has passed. RSSI/SNR are not present on these supported push frames; they remain null, and no routing path is synthesized.
- **Current blocking hardware gate:** restore a configured MeshCore tty and existing GPS tty, audit hub power/cable stability and confirm FT-891/controller/GPS functionality. Before activation, verify firmware role, ordinary RF behavior/exposure, log storage retention and backup, and complete parked receive capture.
- No automatic discovery, advertisement, messaging, trace, CAT/PTT or radio configuration is permitted from Rolling Thunder's MeshCore collector. The owner permits native firmware-managed ACK/forwarding traffic; a physically inaccessible antenna is not by itself an RF exposure assessment.
