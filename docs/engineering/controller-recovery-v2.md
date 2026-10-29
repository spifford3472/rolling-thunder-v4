# USB controller recovery candidate (RTCTRL/2)

## Delivery status

This implements the next issue343 source slice after the pure policy foundation.
The worker and v2 session parser are wired behind explicit `physical_controls.transport: serial_v2`. Existing `serial` and `mock` behavior is unchanged; no automatic protocol upgrade occurs. No installed Pi behavior has changed during development. Default firmware target remains
legacy esp32dev. Only explicit esp32dev-recovery builds the new health exchange;
no firmware upload, serial device open, reset, service restart or RF test occurred.
An actual parked commissioning step and explicit rollout remain required.

## Ownership and consumers

| Component | Responsibility | Consumers |
| --- | --- | --- |
| control_transport_health.py | Pure monotonic backoff/health policy | Recovery worker; pure tests |
| control_protocol_v2.py | Bounded strict wire value decoding | Session/worker candidate; firmware contract tests |
| control_session_v2.py | Fresh nonce, boot identity, sequence watermark, age bounds | Recovery worker only |
| recovering_control_source.py | One serial-owner thread and bounded expiring mailbox | Explicit serial_v2 factory; tests |
| firmware recovery_session.h/main.cpp | Physical input sensing and health-only session exchange | Explicit recovery firmware target |

ControlSource -> ControlDispatcher -> OperatorCommandController remains the
application authority. This transport emits only typed physical input and health;
it owns no CAT, PTT, contact persistence, voice audio or application policy. Voice
activation still requires a fresh physical voice-button event; no always-on audio
or additional speech system is introduced. All existing mappings remain unchanged.

## Wire contract

ASCII lines include required LF (optional single preceding CR), at most256bytes.
Fields are separated by exactly one space. Nonce is32lowercasehex; boot identity
16lowercasehex. Integers are canonical unsigned64-bit decimal. Other tokens use
1..64ASCII letters/digits/dot/underscore/colon/hyphen with alphanumeric first.

| Direction/type | Exact fields after RTCTRL/2 |
| --- | --- |
| Host HELLO | HELLO nonce |
| Firmware READY | READY nonce boot firmware sequence uptime_ms |
| Host PING | PING nonce request_id |
| Firmware PONG | PONG nonce boot request_id sequence uptime_ms |
| Firmware input | EVENT nonce boot sequence uptime_ms input_id |

Firmware candidate version2.0.0 uses fresh64-bit boot randomness, per-session
64-bit event sequences and esp_timer monotonic64-bit milliseconds. A host connection
uses a fresh128-bit cryptographic nonce. HELLO resets firmware session sequence to0,
captures button states and clears partial encoder detents before READY. A button
held at boot/reconnection must be released before a new press can create an event;
releasing an old short/long press creates no action. Duplicate HELLO for the active
nonce does not reset its sequence. Firmware stops emitting input if no valid host
challenge arrives for750ms. Invalid/repeated/overflowed PING identifiers are ignored.
Firmware input buffers and per-loop work are bounded; the v2 UART TX buffer is512bytes and writes require available capacity; NUL, nonASCII and oversized
request lines are discarded through LF. Health replies never create input events.

## Freshness and bounded memory

After bounded driver open and a cancellable1s worker-only settling wait, the host flushes pending receive bytes and starts a fresh nonce challenge. The0.5s response deadline begins at that challenge, not before driver open/firmware boot. Overall synchronization still has the separate3s policy limit. A fresh nonce response must arrive within0.5s. PING is scheduled every0.25s with at
most one outstanding request, also requiring reply within0.5s. A serial open is not
health. The pure policy retains3s health expiry as a separate final guard, while the
worker's shorter challenge deadline normally detects loss sooner.

The host records challenge SEND time, not just receive time. Matching firmware
uptime then defines a conservative lower bound for each input's host occurrence.
An input whose upper age bound reaches0.5s is rejected; a timestamp more than10ms
ahead of the bound is inconsistent and closes the connection. This accounts for
round-trip uncertainty without equating buffered receipt to creation time. Declared
clock progression is a trusted firmware contract, not a hostile-device security
boundary. Never substitute an unsolicited heartbeat or open fd for this proof.

Only strictly increasing event sequence is accepted. Duplicate/older sequence is
ignored, unknown input is dropped, boot change/regressing health/unsupported
firmware/conflicting challenge forces disconnect. PONG watermarks account for
already emitted inputs; missed inputs are never replayed. The session retains no
per-event ID set. A20,000-event/duplicate test checks constant field/container state;
this is not a claim of a real90day soak.

Mailbox capacity defaults32(max1024). Each entry expires at the earlier of its
conservative age deadline or250ms after receipt. Tk-facing drain does no serial
I/O or join and returns only current healthy-generation input before expiry.
Overflow discards the batch and disconnects. Failure, stale health, cancellation
and shutdown clear all pending bytes/events. Oversized serial lines are discarded
through the delimiter, so a valid-looking suffix cannot become an action.

## Worker lifecycle and reset limitations

Exactly one worker owns open/read/write/reset-buffer/close. Caller open starts
only a thread. Caller close cancels publication/clears input immediately; worker
closes its own port. A stopped-but-still-running worker cannot be replaced by a
second owner. Late open success after stop closes without publishing or dispatch.
Generation IDs persist across restarts. An explicit non-UI wait_closed accepts
only a finite0..5s join. Clock errors fail closed; failed descriptor close stops
recovery and prevents reopening that source until manual recovery. Status exposes
worker_running separately from the requested STOPPED state.

Default pyserial read and write timeouts are0. Partial writes fail the session.
Open/close still depend on OS/driver behavior: these cannot be forcibly cancelled
safely by Tk. Published synchronization becomes stale during a blocked open, and
close remains nonblocking to the caller, but actual descriptor cleanup is a parked
hardware acceptance gate. DTR/RTS are requested deasserted BEFORE opening; the
actual CP2102/ESP32 board and driver can still glitch these lines. No automatic
reset pulse is issued. Measure actual reset behavior before live reconnect rollout.

Explicit serial_v2 composition uses RecoveryControlEventGate: it checks the currently published healthy nonce, one sequence watermark and bounded known-input repeat times. It never adds IDs to the legacy all-ID set. Disconnection invalidates the published nonce, including after a drain but before dispatch. Legacy ControlEventGate behavior remains unchanged. The routine bottom ticker displays Controls: READY/CONNECTING/RECONNECTING/UNAVAILABLE/OFFLINE only in v2 mode; existing higher-priority alerts retain precedence.

## Firmware build and watchdog

Recovery target pins espressif32@7.0.1. Verified local toolchain: Arduino framework
3.20017.241212+sha.dcc1105b, Xtensa8.4.0+2021r2-patch5, esptool4.11.0. Both legacy
and recovery targets compile with Wall/Wextra/Werror using PlatformIO6.1.19.
Recovery registers a task watchdog configured2s, reset by the input/health loop;
registration failure prevents READY/input emission. Compilation/native tests do
not prove actual watchdog/reset timing. The validated build uses the pinned
Arduino2/IDF4 toolchain; any other toolchain requires fresh review/build evidence.

Build only (no upload):

    ~/.platformio/penv/bin/platformio run -d firmware/esp32-controls -e esp32dev -e esp32dev-recovery

Native tests compile actual main.cpp against GPIO/serial/watchdog stubs, test held
keys, session replacement, partial detents, lease expiry, malformed requests,
watchdog registration failure and uptime beyond2**32milliseconds. They feed actual
firmware output through the Python parser. Hardware wiring, real resets, RF and
analog USB behavior are not simulated proof.

## October16 archive evidence

Verified original archive SHA256
8b9bfc49c0458a2d75ecc4704495b489fbfa53151cca4d1ec5111e0ac61dd0fa.
Its recorded kernel times show controller branch1-1.1 disconnect at03:40:24,
re-enumeration at03:43:39 as ttyUSB2, another disconnect12:30:20 and return12:30:25
as ttyUSB2. The by-id controller link points to ttyUSB2; captured process fds show
only ttyUSB0 and ttyUSB4, with no descriptor to ttyUSB2. ttyUSB0 after renumbering
belongs to a different bridge, so do not attribute every ttyUSB0 error to the
controller. Effective October16 configuration and exact app read/open error remain
unverified. This establishes historical USB churn/renumbering, consistent with the
confirmed no-reopen code gap, not the physical cable/power cause or firmware stall.
No archive/private log/config was uploaded to GitHub.

## Commissioning and rollback gates

Before activation: validate DTR/RTS and driver cleanup on the actual parked board;
record the current known-working firmware/readback provenance and exact source,
config and backup identities. Do not flash an unidentified device or stop the
radio dashboard while driving. Activation selects serial_v2 only after matching firmware health is verified; the existing command boundary remains authoritative. Software can first roll out with the current serial setting unchanged. No generic serial scan or fallback to another tty is allowed.

Separate parked acceptance must exercise unplug/replug, firmware reset/watchdog,
held controls, reconnect during a press, a stale/flooded stream, every mapping,
no phantom/duplicate actions, UI/FT8/GPS/logging isolation and long soak. No RF
transmission is required for controller acceptance. Bluetooth remains a separate
value/security gate. Microphone USB absence is a distinct hardware investigation.

This source slice needs no production rollback. A future rollout must preserve
known-good firmware, exact Pi source/config and existing contact history. On failed
acceptance disable only the new transport, restore reviewed legacy firmware/source
through approved paths, and retain newer durable data. Do not use database restore
or whole-system restart as controller recovery policy.

## Change provenance

Owner authorized moving forward. Qwen isolated run
20261028T234716892414Z-issue343-v2-parser produced an incorrect parser rejecting all
three valid frame types; its bounded pass was stopped after independent review.
The coordinator corrected the wire piece and implemented/reviewed the worker,
firmware and regression tests. Rejected Qwen workspace is retained. No coding
worker remains. Owner subsequently explicitly authorized merge and deployment after validation; actual installed and firmware acceptance status must be recorded separately.

Validation checkpoint:3577passed7skipped across the full Python suite; Ruff and strict MyPy348sourcefiles pass. Both esp32dev and pinned esp32dev-recovery builds pass. Owner merge/deploy authorization is current. Hardware/firmware acceptance and actual installed identities must be recorded after cutover.
