# FT8-RX-02 — FT-891 receive-state observation and supervised recovery

**Status (2026-11-15): SOURCE-ONLY READBACK CODEC / NO AUTOMATIC UNLOCK.**
No radio hardware accessed, no new CAT transactions at runtime, no port/USB
changes, no privileged component installation or RF testing. The existing
merged #474 live PTT alarm remains fail-closed.

## Original vendor evidence

Yaesu's *FT-891 CAT Operation Reference Book*, version **1909-C**,
CAT Command Reference pp. 16 and 18, available from the official FT-891
product support page:

https://www.yaesu.com/Files/4CB893D7-1018-01AF-FA97E9E9AD48B50C/FT-891_CAT_OM_ENG_1909-C.pdf

- `TX;` is a **read** returning exactly `TX0;` (RADIO TX OFF, CAT TX OFF),
  `TX1;` (RADIO TX OFF, CAT TX ON) or `TX2;` (RADIO TX ON, CAT TX OFF).
- `RIA;` returns `RIA0;` / `RIA1;` for the radio's **TX LED** off/on.
- `RIB;` returns `RIB0;` / `RIB1;` for the radio's **RX LED** off/on.
- `RS;` reports normal/menu mode and does **not** report TX/RX RF status.
  `TX0;` as a set operation is different from the read `TX;` and cannot
  independently prove physical RF de-keying.

All three reads are status **from the same transceiver/CAT firmware**. Their
agreement can improve diagnosis, but they are **not independent physical
RF-power or PTT-line sensors**. A wedged device, stale serial response, wrong
radio, transient reconnection, or firmware fault may make all reported
status wrong or unavailable. No claim is made that an FT-891 reports all
three fields reliably during the actual failure that prompted this work.

## This source-only implementation

`ft891_cat.py` now contains *pure, non-I/O* encoding/parsing for the three
read commands, strict exact-length/value validation and typed three-state
`Ft891TxReadback`. It preserves `TX1` and `TX2` as distinct positive/uncertain
TX conditions; it does not conflate either with radio RX. Unknown, wrong
selector, duplicated, non-byte or partial replies raise errors rather than
turning into receive. Read commands are **not scheduled, issued or invoked**
by the running dashboard, the FT8 unlock, or the radio polling service.

`tests/test_ft891_cat.py` verifies all documented responses, corrupt/crossed
answers, read-command-only transport recording, and zero ability to unlock
`FT8PttAlarm` from nominal triple readback. There is no new radio capability,
CAT lock owner, UI HTTP/serial call, feature gate or persistent database.

## Architecture decision — two distinct levels of evidence

1. **CAT advisory only (optional future stage):** A background task on the
   existing `Ft891Radio` operation lock may query `TX;`, `RIA;`, `RIB;` in
   fixed bounded order with strict timeouts, identity correlation, maximum
   sample age, monotonic timestamps and no request made on Tk. Publish an
   immutable telemetry result such as `consistent_rx`, `tx_reported`,
   `conflicting`, `stale`, `timeout`, `disconnected` or `unsupported`.
   This may explain an incident, but **none of those states authorizes
   unlocking**, not even `consistent_rx`. If the shared CAT lock is stuck,
   do not create a second CAT port or force-close an in-flight command.
2. **Independent receive proof (future design review, not built):** To
   automatically restore transmission after a real uncertain PTT event,
   require an independent and validated physical signal (e.g. isolated RF
   forward-power detection or a hardware PTT/TX-status interface with its
   trust limitations understood) *plus* explicit operator supervision and a
   separate authenticated recovery approval. Design for conflicting,
   missing, unplugged, stuck-high/low, stale and power-cycle sensor states;
   bound a stable receive observation window; gate on source identity,
   absence of any active QSO and a new transmit authorization. An external
   TX-state line can still misreport RF power; select sensor architecture
   after an electrical/installation review, not from this CAT manual alone.

Human visual confirmation of a non-red TX lamp and a safe powered-off rig
is appropriate for *operator emergency recovery*, but it is not an in-band
machine-verifiable sensor measurement. It cannot be encoded as
`radio_confirmed_receive=True` merely because the 1-3-1 gesture occurred.
Do not re-enable the real unlock in #474 as part of introducing telemetry.

## Important unresolved restart/latch semantics

The current `FT8PttAlarm` is an in-memory object created at dashboard
startup. The corrected lockout is effective **during that process**;
a process restart can construct a fresh alarm that has not observed the
prior uncertain-PTT event. This is a significant remaining safety boundary:
**do not promise cross-restart containment from the current source.** A
separately reviewed design must consider crash/reboot persistence, fail-closed
startup on an unresolved PTT incident, and safe recovery after manual
radio power-off. Persistence must not be implemented casually through the
contact/QSO database, nor should it create a new unsafe hardware-control
path. Any owner-authorized recovery should leave a durable audited receipt.

## Offline acceptance criteria for future stages

- Same serial/CAT operation lock and typed interface; never issue queries
  from Tk or while another CAT command is blocked or in a sensitive FT8
  transmit period; strict bounded reads and an independent executor.
- Fake CAT transports cover `TX0/TX1/TX2`, `RIA0/1`, `RIB0/1`, contradictory
  or out-of-order response, reconnect/identity change, stale sample,
  blocked query, cancel/shutdown overlap and no unauthorised TX1.
- Published states never infer RX from missing/non-response or from the
  existing `RadioState.transmitting=False` field; source-only advisory data
  cannot clear a real FT8 inhibit, even when three firmware reports agree.
- A future separate supervised sensor prototype must prove real physical
  semantics with an operator-present parked radio. Require distinct approvals
  for powered CAT polling and especially any live RF transmission.
- Runtime restart/crash tests verify an unresolved PTT incident cannot
  silently regain transmit authority by replacing an in-memory object.
- Full Ruff/MyPy/pytest, security review, documentation, verified running
  exact SHA, rollback/data protection and separately approved parked
  hardware acceptance precede deployment.

## Change/rollback

2026-11-15: Added strictly pure FT-891 readback codec and synthetic tests,
with no installed integration or unlock-authority expansion. Roll back by
reverting this PR. A revert does not alter the deployed radio or repair
an unresolved stuck-transmit incident. None of the defined QTH networks or
OPNsense configuration is modified.
