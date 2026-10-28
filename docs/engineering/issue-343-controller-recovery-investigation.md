# Issue 343 controller transport investigation

Status: read-only evidence and proposed design, October 28, 2026. No runtime,
firmware, configuration, pairing, USB reset, deployment or RF change.

## Evidence and limits

Current main is 838089878d91433e5c5f050d812784c6a9c6e298. Pi production is
be9b3cb117a2d127718ba6d207a00839e6e89cbc, clean. Relevant serial source,
protocol, lifecycle, physical event gate and firmware have no differences between
these revisions. Dashboard active since October 27 10:19:34 EDT, PID 107398.

At October 28 16:42 EDT the controller CP2102 was ttyUSB0, dashboard fd31 open,
root:dialout mode0660. Config physical_controls uses the stable by-id path
/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0,
115200 baud, 256-byte line, 4096-byte read, 32 events/drain, 0.25s repeat
suppression. Its USB branch is 1-1.1. Serial 0001 is generic: avoid claiming
universal device uniqueness if another identical bridge is added.

No retained controller disconnect/read-error evidence explains the earlier
incident. Kernel attachment is logged July23 during early boot; wall time at boot
is not proof of actual uptime. A current open fd proves an open transport, not
firmware liveness. No active event/firmware query or device read was performed.
Installed firmware version remains unknown. Bluetooth service active and hci0
present do not prove pairing, SPP capability or useful redundancy.

## Confirmed source failure boundary

SerialControlSource.open is called once by ui_main startup. An open failure is
printed but the disconnected source stays composed. A read/in_waiting exception
closes the port, clears partial bytes, saves last_error and returns no events.
Subsequent drains return empty indefinitely: there is no reopen scheduler.
Control dispatch runs on Tk refresh; last_error has no live operator health
projection. This is a verified recovery defect, not a proven explanation of the
historical controller incident or issue359 UI/FT8 delays.

RTCTRL/1 accepts EVENT only, with random32-bit boot/event sequence identifier
and ESP32 millis-derived seconds. Firmware emits no heartbeat/version or
application watchdog. Idle and stalled firmware are indistinguishable.
ControlEventGate retains every event ID indefinitely. Firmware millis wraps in
about49.7days; future health/freshness code must account for wrap or use explicit
64-bit monotonic uptime. Existing Pi suppression uses host monotonic time.

## Separate microphone finding, added by owner

Speech config uses plughw:CARD=Array,DEV=0, enabled,16000Hz,two channels,five-second
button-triggered capture. Read-only ALSA enumeration and the production
AlsaCaptureProbe return UNAVAILABLE: ALSA card Array is not present.
The Seeed reSpeaker XVF3800 4-Mic Array was on USB1-1.4.2; kernel records its
USB disconnect October23 03:27:59 EDT. It is absent from current sysfs product
inventory and ALSA cards/PCM. No reconnection appears in the retained filtered
kernel log. October28 02:30-09:00 journal filters found no matching USB/audio
errors; absence of matching logs is not proof of uninterrupted health.

The only currently enumerated capture device is a separate C-Media USB Audio
Device, already RUNNING under an existing arecord process. Do not redirect voice
to it or interrupt it. The configured reSpeaker is missing at OS enumeration,
not just rejected by speech recognition. Cable/power/hub/device causes remain
unresolved. Its branch differs from controller1-1.1, so this evidence does not
establish one shared failure. When parked, inspect/reseat the microphone USB
connection and verify its return under the same Array name before button-only
callsign acceptance. Do not trigger recording remotely or add always-on capture.

## Proposed recovery design (not implemented)

Keep USB primary. A single transport owner worker performs serial open/read/close
and publishes immutable health plus a bounded event mailbox. Tk drain consumes
snapshots without serial I/O, sleep, join or reconnect. States: stopped,
disconnected/backoff, synchronizing, healthy, stale. All scheduling uses injected
host monotonic time. Proposed retry delays0.5,1,2,4,8seconds capped with bounded
jitter; a stable healthy interval resets backoff. Stop invalidates the generation,
wakes the worker and prevents late opens/events from being published. Partial
lines and pending actions are discarded on disconnect, generation/session change,
stale transition and shutdown. A late operation from an old generation cannot
publish into a new connection. Enforce bounded bytes, messages, events, errors
and health transition logs; retain diagnostics after recovery.

Opening a serial port may toggle DTR/RTS on ESP32 boards. Confirm actual board
wiring and pyserial behavior before approving repeated reopen. Do not add forced
resets, baud scanning or device-path fallback. Worker open time and shutdown
bounds require actual adapter validation; timeout=0 only bounds reads.

A health-only versioned protocol should carry firmware version, boot session,
64-bit sequence and uptime, periodic heartbeat and session validity. Health frames
never become ControlAction. Preserve ControlSource -> ControlDispatcher ->
OperatorCommandController authority, physical mappings, voice button semantics
and existing bounded FT8 authorization.

Legacy RTCTRL/1 cannot prove that an event buffered during disconnection is fresh.
A host flush and unsolicited heartbeat alone do not prove freshness: queued device
or hub data can survive. Do not promise safe automatic action rearming from those
alone. Preferred review candidate is a minimal host nonce/firmware response health
handshake, then per-connection session-bound events; firmware discards pre-session
inputs and requires release before accepting a held button. This changes the
current one-way protocol and needs explicit design approval. Responses confer no
radio/application authority. Until approved, retain legacy behavior and expose
its recovery limitation; do not silently auto-replay/rearm actions.

For v2 session-aware deduplication use an active boot/connection generation and
monotonic sequence watermark; reject old sessions and non-increasing sequences.
If redundant transports are later introduced, firmware must publish identical
identities; stale copy rejection must survive bounded-cache eviction. A size-only
LRU of event IDs is insufficient. Preserve existing per-input suppression;
sequence gaps are counted, never replayed. Proposed heartbeat1s/stale3s and
freshness limits are candidates requiring measured acceptance, not installed facts.

Publish transport state, last valid health age, session/firmware identity,
reconnect attempts, rejected/stale/duplicate counts and bounded last error.
Healthy means validated liveness, not just an open fd. Optional controller loss
cannot stop touchscreen, GPS, local logging, FT8 or Forge-independent operation.

## USB versus Bluetooth decision

USB recovery addresses the confirmed no-reopen path with fewer dependencies.
Bluetooth cannot yet be justified by a demonstrated residual failure. Cold standby
adds transition delay and can lose the initiating press. Dual-active adds pairing,
coexistence, session identity, ordering and deduplication complexity. Neither fixes
stalled firmware without independent liveness/recovery. Keep Bluetooth disabled
as a new feature until USB-only soak identifies a residual problem; existing
Bluetooth service was not changed or paired during this investigation.

## Focused implementation and acceptance slices

1. Approve health/freshness protocol and DTR/RTS behavior; preserve v1 compatibility
   without claiming freshness or firmware health. Add parsers/value snapshots and
   deterministic malformed/oversized/unknown-version/session tests.
2. Add one off-Tk serial worker, bounded backoff/mailbox and lifecycle tests under
   an initially disabled recovery gate. Prove open-failure/device-appearance,
   read-error/reopen, stop-during-open, partial-line discard, stale queue discard,
   no concurrent owners, no blocking Tk and no late generation publication.
3. Implement reviewed firmware health handshake/watchdog separately. Build it;
   validate watchdog against actual Arduino/ESP-IDF version, held-at-boot/reset
   buttons, uptime wrap and session rollover. No automatic firmware upload.
4. Integrate truthful operator health and approved session-aware deduplication.
   Cross-feature tests include voice/commit/discard, context navigation and every
   active-panel consumer; no transport acquires direct CAT/PTT or logging authority.
5. Separately authorized parked, non-RF hardware acceptance: inspect wiring,
   repeated unplug/replug/reset, initial device absent, firmware stall, malformed
   flood, connection churn, held buttons and each physical action. Record latency
   distributions and memory/queue bounds over a simulated90day workload plus real
   soak; verify FT8/touch/GPS/logging unaffected. Bluetooth only after value gate.

## Validation, rollback and disposition

Existing six targeted protocol/serial/lifecycle/factory/gate/dispatcher test files:
74passed with PYTHONPATH pointing at this checkout. Initial invocation ran outside
the checkout and found no tests; next invocation imported the older editable
installation and produced two dispatcher signature failures. Explicit source
selection resolved both; neither failure establishes a current-source defect.
No new runtime behavior is delivered, so full suite/hardware acceptance is not
claimed. Documentation-only diff check is required before commit.

Gate A historical incident: unresolved evidence gap. Gate B: USB-first design
proposed, handshake/reset and live soak unproven. Gate C: Bluetooth not justified.
Gate D: bounded slices above ready for review. Implementation/merge/deployment
remain separate decisions under issue343 and AGENTS.md.

No production rollback is required because no installed state changed. A later
rollout must preserve exact Pi source, config and flashed firmware provenance,
use approved deployment helpers, and restore the reviewed prior source/config/
firmware without overwriting newer contact data. No sudoers, systemd, udev,
BlueZ, network, audio or OPNsense setting changed.

Change history: October28 initial current-source and live read-only investigation;
owner-added microphone incident classified as absent reSpeaker USB/ALSA device;
source recovery gap confirmed; historical controller cause left unresolved.
