# Rolling Thunder v4.3 Experimental FT8 Architecture

Status: Checkpoint 1 architecture/research baseline  
Date: 2026-09-29  
Implementation state: design only; no FT8 runtime, audio capture, transmit audio, or software PTT is introduced by this document.

## Purpose

Rolling Thunder v4.3 explores an optional native FT8 workflow for the installed
Yaesu FT-891 + DigiRig DR-891 mobile station.

The intended operator experience is:

```text
receive/decode
    -> show stations calling CQ
    -> operator selects exactly one station
    -> bounded automated exchange with only that station
    -> successful QSO enters the existing local-first logging path
    -> return to the CQ browser
```

The operator's explicit station selection is the authorization event for that
single QSO. Rolling Thunder must never automatically select another station,
continue to another QSO, hop bands autonomously, or create an unattended
operating mode.

This work is experimental. The protected recovery point remains:

```text
tag:    v4.2.0
commit: 3f5a9c22bc600883b1eb8d868d92e2f58658cc24
```

The v4.3 FT8 feature must remain disabled by default and removable without loss
of v4.2 contact data or normal Rolling Thunder behavior.

## Existing architecture that must remain intact

The current generic `Radio` protocol is deliberately receive-side. It exposes
connection/state, receive frequency/mode, and band-context operations but no
PTT, MOX, keying, or general transmit command.

That remains the contract.

The existing FT-891 receive path is:

```text
Application
    -> Radio
    -> Ft891Radio
    -> CatTransport
    -> PySerialCatTransport
    -> FT-891 Enhanced CAT
```

`Ft891Radio` serializes operations with its adapter lock, and normal radio
polling shares that adapter. FT8 must not create a second unsynchronized owner
of the Enhanced CAT port.

The existing UI architecture also remains unchanged in principle: Tkinter may
render immutable FT8 snapshots and submit typed operator commands, but it must
not own serial, audio, timing, decoder, network, SQLite, or transmit work.

## Installed FT-891 + DigiRig DR-891 hardware boundary

### Enhanced CAT

The existing working FT-891 CAT path is:

```text
/dev/serial/by-id/usb-Silicon_Labs_CP2105_Dual_USB_to_UART_Bridge_Controller_011F42E9-if00-port0
```

This is CP2105 interface 00 and has been observed as `/dev/ttyUSB2`. The
`/dev/ttyUSB*` number is diagnostic only and must never be treated as stable
configuration.

Enhanced CAT remains owned by the existing FT-891 adapter/arbitration path.

### Standard Com Port

CP2105 interface 01 has been observed as `/dev/ttyUSB3` and is presently
unused by Rolling Thunder.

Existing documentation associates this interface with PTT/CW/digital-transmit
control, but v4.3 Checkpoint 1 does not authorize opening it. Whether future FT8
PTT should use this interface, an Enhanced-CAT command, or another mechanism is
an experimental question that must be answered with a later parked hardware
test before transmit implementation.

No design may assume RTS, DTR, or another Standard-port line is PTT without
physical verification.

### DigiRig C-Media audio

The DR-891 exposes:

```text
0d8c:0012 C-Media Electronics, Inc. USB Audio Device
```

Observed ALSA identity:

```text
CARD=Device,DEV=0
```

Observed capture capability includes 16-bit little-endian mono at 44.1 or
48 kHz.

The FT8 subsystem should configure the C-Media PCM by stable ALSA card/device
name, for example:

```text
plughw:CARD=Device,DEV=0
```

rather than a numeric ALSA card index. This follows the existing speech-audio
practice, where a stable card name is preferred because USB card numbers can
move between boots or reconnects.

The C-Media HID interface is not evidence of a PTT API. It remains unauthorized
until separately identified and verified.

The DR-891 digital-mode audio path must remain separate from the speech/ReSpeaker
path:

```text
speech: plughw:CARD=Array,DEV=0
FT8:    DigiRig C-Media CARD=Device,DEV=0
```

## Component boundaries

The proposed logical architecture is:

```text
Tk FT8 presentation
        |
        v
FT8 operator controller
        |
        +---------------------> CQ activity snapshot
        |
        v
FT8 QSO controller/state machine
        |
        +------> FT8 clock/timing engine
        |
        +------> FT8 encoder
        |
        +------> DigitalTransmitSession
        |            |
        |            +----> narrow PTT backend
        |            +----> transmit-audio output
        |
        +------> completed-QSO logging adapter
                     |
                     v
             ContactLoggingService

FT8 receive worker
        |
        +------> FT8AudioInput
        |
        +------> FT8Decoder
        |
        v
CQ activity manager
```

Decoder-specific structures, subprocess output, FFI types, FFT buffers, ALSA
handles, CAT commands, and UI widget state must not enter the FT8 domain model.

## Proposed project-owned models

Names are provisional and should follow repository conventions when
implemented.

### `FT8Period`

Represents one UTC-aligned 15-second FT8 period:

- UTC start
- sequence number or equivalent stable period identity
- even/odd parity

Period identity comes from UTC alignment, not from a decoder backend's private
counter.

### `FT8Decode`

Normalized immutable decode:

- period
- SNR in dB
- DT/time offset
- audio frequency/offset
- raw message
- normalized message kind
- source callsign when present
- destination callsign when present
- grid when present
- report when present
- even/odd period
- optional backend diagnostics that are explicitly non-domain metadata

### `FT8CQActivity`

A browser-oriented immutable record derived from decodes:

- callsign
- grid when present
- most recent period
- SNR
- DT
- audio frequency
- CQ qualifier when present
- age/staleness

CQ activity is presentation/discovery state only. It has no transmit authority.

### `FT8QsoContext`

Created once when the operator authorizes one QSO. It freezes:

- local operator callsign
- remote callsign
- target audio frequency
- radio frequency/band/mode context
- local Maidenhead grid
- location metadata needed by logging
- selected TX period parity
- authorization timestamp/period

GPS movement after creation must not change the transmitted grid during that
QSO.

### `FT8QsoState`

The implementation should use explicit states rather than free-form flags.
A suitable first state set is:

```text
IDLE
AUTHORIZED
WAIT_TX_CALL
TX_CALL
WAIT_REPORT
TX_REPORT
WAIT_R_REPORT
TX_R_REPORT
WAIT_73
TX_73
COMPLETED
ABORTED
RETRY_EXHAUSTED
ERROR
```

Exact message naming may be refined after reference-vector testing, but every
transition must be explicit and testable.

Terminal states must always revoke transmit authority and return control to the
CQ browser. They must never cause automatic selection of a different station.

### Retry contract

The default policy is six transmission attempts per unchanged QSO
state/message.

Example:

```text
TX_CALL attempt 1..6
    response advances state -> reset retry counter for the new state
    no valid advance after attempt 6 -> RETRY_EXHAUSTED
```

This is not six transmissions for the entire QSO.

Duplicate decodes or irrelevant traffic do not reset the retry counter.

## Receive audio boundary

A small `FT8AudioInput` protocol should own receive PCM acquisition. It should
publish timestamped blocks or complete period buffers in a project-owned format.

Responsibilities:

- open the configured stable PCM selector
- validate the device and expected format
- capture outside Tkinter
- convert/resample to the decoder's required rate
- define overflow/underrun behavior
- stop cleanly and release the device
- surface explicit unavailable/error state

It must not:

- select stations
- parse FT8 messages
- decide QSO state
- key the radio
- write contacts

The first physical receive implementation should prefer ALSA/PipeWire behavior
that can be tested from the command line without changing global production
audio routing.

No production PipeWire rule, ALSA default, or persistent audio configuration
should be changed merely to make FT8 discovery easier.

## Decoder boundary

Use an `FT8Decoder` interface that accepts project-owned audio/period input
and emits `FT8Decode` values.

A backend may be:

- an in-process native library behind a small FFI wrapper;
- a bounded subprocess whose stdout is normalized by an adapter; or
- a temporary WSJT-X-assisted receive prototype.

The rest of Rolling Thunder must not know which implementation is active.

Similarly, encoding should be exposed through a project-owned `FT8Encoder`
boundary. Decoder and encoder may use the same underlying library but should not
be conflated in application code.

## Decoder/encoder research

Research was refreshed on 2026-09-29.

### WSJT-X

Current official WSJT-X development has moved to
`https://github.com/WSJTX/wsjtx`. WSJT-X 3.0.x was released in 2026 and the
project remains actively developed.

Strengths:

- authoritative behavioral/reference implementation
- complete modern 77-bit FT8 protocol behavior
- mature multi-signal decoding
- complete encode/QSO behavior
- strongest reference for interoperability and test vectors

Constraints:

- GPLv3 code
- large application/dependency surface
- unsuitable as a hidden second owner of the FT-891 CAT/PTT/audio devices
- direct linking or source derivation would have licensing implications for
  Rolling Thunder

Decision: use WSJT-X as the interoperability/reference oracle and, if useful, as
a temporary isolated receive comparison tool. Do not make core Rolling Thunder
types or radio ownership depend on WSJT-X.

References:

- https://github.com/WSJTX/wsjtx
- https://wsjtx.github.io/wsjtx/
- https://wsjt.sourceforge.io/FT4_FT8_QEX.pdf

### kgoba/ft8_lib

Repository: `https://github.com/kgoba/ft8_lib`

License: MIT.

Observed repository state during Checkpoint 1:

- C implementation
- builds a reusable `libft8.a`
- includes `gen_ft8` and `decode_ft8` examples
- supports 77-bit FT8 encode/decode paths
- can decode recorded WAV input
- example live capture can use PortAudio
- repository is not archived
- issue activity continued in 2026
- last repository push observed by GitHub metadata: 2025-08-24

Strengths:

- permissive license
- compact C integration surface
- both encoding and decoding
- demonstrated embedded/lightweight orientation
- attractive for Raspberry Pi integration
- easy to isolate behind FFI or a subprocess

Constraints:

- its README lists contest modes and some compound/special callsign work as low
  priority
- example decoder is not itself a full live multi-signal application framework
- decode performance must be compared with WSJT-X on the actual Pi/audio chain
- Python binding/integration must be owned by Rolling Thunder

Decision: primary implementation candidate and mandatory benchmark candidate.

### rtmrtmrtmrtm/ft8mon

Repository: `https://github.com/rtmrtmrtmrtm/ft8mon`

License: MIT.

Observed repository state during Checkpoint 1:

- C++ receiver
- FFTW-based
- PortAudio/live sound-card support
- WAV-file support
- multi-threaded and multi-pass decoder implementation
- receiver only; not a matching transmit encoder
- repository is not archived
- last repository push observed by GitHub metadata: 2021-11-19

Strengths:

- receive-oriented design
- stronger decoding techniques than a minimal single-pass decoder
- explicit C-callable entry point exists in its headers
- useful benchmark against a lightweight decoder

Constraints:

- no matching encode path
- additional FFTW/native integration
- substantially older maintenance activity than current WSJT-X
- would require combining it with another encoder
- CPU cost on the Raspberry Pi must be measured

Decision: benchmark candidate for receive quality, not the preferred single
backend for the whole FT8 stack.

### Old pure-Python `basicft8`

Do not use as a production candidate. Its own documentation describes limited
decode performance, and published FT8 notes identify it as predating the modern
2018 protocol changes.

### Checkpoint 3 benchmark decision

Checkpoint 3 should benchmark at least two receive backends on `anvilmobile`:

1. `ft8_lib`
2. `ft8mon`

Both should be compared against current WSJT-X results on the same recorded
audio corpus.

Selection criteria:

- number of valid decodes versus the WSJT-X reference
- false-decode behavior
- period completion latency
- CPU utilization
- peak RSS
- ability to finish before the next actionable timing deadline
- build/install burden
- resilience to malformed/noisy input
- support for the message classes Rolling Thunder needs

The first production backend should not be selected solely from desktop
benchmarks.

## CQ activity manager

The CQ activity manager consumes normalized `FT8Decode` values and publishes
immutable browser snapshots.

Responsibilities:

- accept only CQ-like activity appropriate to the browser
- normalize callsigns/message kinds
- deduplicate repeated CQ messages
- refresh SNR/DT/frequency from newer decodes
- expire stale entries after a bounded number of periods
- preserve stable selection by callsign/activity identity where practical
- never select a station itself

A decode from a station other than the currently authorized QSO may still
appear in the browser's next snapshot, but it must never redirect the active
QSO state machine.

## Timing architecture

FT8 timing requires separate wall-clock and monotonic responsibilities.

Introduce an injectable `FT8Clock` abstraction capable of:

- returning UTC
- returning monotonic time
- mapping current UTC to the active/next 15-second period
- being replaced by a deterministic simulated clock in tests

Rules:

- UTC determines FT8 period boundaries.
- monotonic time measures local deadlines and elapsed durations.
- system clock jumps must be detected rather than silently treated as normal
  elapsed time.
- a transmit operation must not begin when the implementation has missed its
  bounded start window.
- timing uncertainty beyond the accepted threshold must fail closed to receive.
- decoder work that completes too late for the intended response period must not
  cause a late transmission.

No FT8 test suite should depend on real sleeping when a simulated clock can
advance deterministically.

## Narrow transmit authority

FT8 must not add `ptt_on()`, `ptt_off()`, raw CAT access, or generic transmit
methods to `Radio`.

Use a separate capability such as:

```text
DigitalTransmitSession
    begin_authorized_slot(request)
    abort()
    close()
```

with a backend such as:

```text
FT8TransmitBackend
```

The concrete API can change, but the authority rules cannot.

The transmit request must be immutable and bounded:

- one already-authorized remote callsign
- one encoded FT8 message
- one audio frequency
- one UTC period/slot
- one maximum duration
- one local QSO context/token

The backend must not choose callsigns, construct the next QSO state, select a
new station, hop bands, or keep PTT asserted beyond the requested slot.

The QSO controller owns policy. The backend owns only execution of one bounded
authorized transmission.

## CAT and PTT ownership

The current FT-891 Enhanced CAT serial connection already has one logical owner
through `Ft891Radio` and its operation lock.

Future FT8 transmit work must therefore choose one of these architectural
patterns after hardware verification:

1. add a narrow internal CAT arbitration capability behind the existing FT-891
   adapter/composition so both receive-state operations and an FT8-specific
   bounded command can be serialized by the same owner; or
2. use a separately verified Standard-port hardware PTT mechanism while keeping
   Enhanced CAT ownership unchanged.

Opening a second unsynchronized Enhanced-CAT serial connection is prohibited.

Before any transmit checkpoint, hardware experiments must determine:

- which physical/software mechanism keys PTT with the DR-891
- whether it is fail-safe on process/device loss
- whether PTT is level- or edge-controlled
- whether RTS/DTR state changes during port open/close can key unexpectedly
- whether the DigiRig HID interface has any relevant function
- whether transmit audio alone can trigger any radio behavior
- what explicit operation returns the radio to receive

Until those facts are observed, the architecture must represent PTT as an
unimplemented backend.

## Transmit audio boundary

Future transmit audio should use a dedicated `FT8AudioOutput` capability.

It owns:

- stable DigiRig playback-device selection
- exact PCM formatting/rate conversion
- bounded playback of one encoded waveform
- drain/cancel semantics
- explicit close

It receives an already-generated waveform. It does not choose messages or own
PTT policy.

Transmit sequencing must eventually be centrally defined so the order is
deterministic, for example:

```text
validate authorized slot
prepare waveform completely
verify timing window
arm/start audio path
key PTT using verified backend
play bounded waveform
stop waveform
unkey PTT
verify/return to receive
publish terminal result
```

The exact key/audio lead and tail timings are deferred until hardware
verification. No values should be invented in Checkpoint 1.

## Shutdown, crash, and watchdog behavior

Future transmit support must fail toward receive.

### Controlled abort/shutdown

ABORT must be:

- visible throughout an active QSO
- idempotent
- safe to invoke repeatedly
- higher priority than normal QSO progression

A controlled abort must:

1. prevent future state-machine transmissions;
2. cancel pending audio;
3. request PTT release through the active transmit session;
4. close/release FT8 transmit resources;
5. publish an aborted/error state;
6. return the application to the CQ browser.

Runtime shutdown must stop FT8 producers/controllers before closing shared radio
or audio adapters.

### Exceptions/device loss

Any exception from:

- encoder
- decoder
- audio input
- audio output
- timing
- CAT/PTT backend
- radio disconnect

must revoke the active session and attempt the same receive-safe cleanup.

### Hard crash limitation

Software cannot honestly guarantee execution of cleanup code after power loss,
kernel failure, or an uncatchable process termination. Therefore the selected
future PTT mechanism must itself be tested for safe behavior when:

- the process exits
- the serial/USB device closes
- the USB cable disappears
- the Pi loses power

If hardware can remain keyed after loss of software control, that mechanism is
not acceptable without an independent hardware watchdog/fail-safe.

## Feature flag/configuration proposal

Checkpoint 1 does not add configuration code. The proposed future shape is:

```yaml
ft8:
  enabled: false

  decoder:
    backend: ft8_lib

  audio:
    input_device: plughw:CARD=Device,DEV=0
    output_device: plughw:CARD=Device,DEV=0
    capture_rate: 48000
    channels: 1

  timing:
    max_clock_error_ms: 500
    max_tx_start_lateness_ms: 250

  qso:
    attempts_per_state: 6
```

The exact timing defaults above are illustrative schema placeholders, not
approved operating values. They must be validated before implementation.

The critical semantic requirement is:

```text
ft8.enabled == false
```

means:

- no decoder construction
- no FT8 audio input
- no FT8 audio output
- no FT8 timing worker
- no FT8 QSO worker
- no PTT/transmit backend construction
- no Standard-port opening
- no FT8-specific CAT command
- no FT8 UI context that can authorize transmission

Normal behavior must remain effectively v4.2-like.

## Location/grid snapshot

The current application already publishes an immutable current station grid
derived from valid GPS state.

When the operator authorizes a QSO, the FT8 controller should create
`FT8QsoContext` and copy the then-current local grid/location information into
it.

That frozen value is used for:

- transmitted grid messages during that QSO
- final logging metadata where applicable

Later GPS updates update the normal station state but cannot mutate the active
QSO context.

If no valid grid exists at authorization time, the QSO policy must explicitly
decide whether to use the configured home grid or refuse a grid-bearing
transmission. That choice should be made in a later implementation checkpoint
with tests rather than implicitly falling back inside an encoder.

## Logging integration

Rolling Thunder's existing `ContactLoggingService` remains the durable local
logging authority.

FT8 must not create a second QSO database.

The FT8 state machine may call a thin completed-QSO logging adapter only from
the successful terminal path. The adapter maps the frozen QSO context and
exchange results into the existing contact logging service.

It must supply FT8 reports explicitly.

The current generic contact logger has SSB-oriented default reports of `59`.
The FT8 adapter must never rely on those defaults.

No successful contact record may be created for:

- an unanswered CQ call
- a partially completed exchange
- manual ABORT
- retry exhaustion
- timing failure
- decoder failure
- audio failure
- CAT/PTT failure
- process shutdown before protocol completion

The existing local-first sequence remains:

```text
completed FT8 state
    -> existing local ContactLoggingService
    -> durable SQLite write
    -> existing asynchronous Forge/Wavelog synchronization
```

## Proposed module layout

Do not create these modules until the implementation checkpoint that needs
them. The intended ownership is:

```text
src/rolling_thunder/ft8/
    __init__.py
    domain.py
    decoder.py
    encoder.py
    audio.py
    timing.py
    activity.py
    qso.py
    transmit.py
    logging.py
```

If early implementation contains only two or three small files, prefer that
smaller layout rather than creating empty architectural scaffolding.

Concrete adapters may live alongside existing hardware adapter conventions
rather than inside the domain package.

No decoder-specific object may escape its adapter.

## Test strategy by checkpoint

### Checkpoint 2 - domain/config scaffolding

No hardware.

Test:

- `ft8.enabled=false` composition
- immutable decode/QSO models
- message normalization
- state definitions
- retry counters
- simulated clock/period math
- grid snapshot immutability
- no transmit backend constructed while disabled

### Checkpoint 3 - decoder benchmark

No RF transmission.

Use recorded WAV fixtures and identical periods.

Measure:

- valid decodes
- false decodes
- CPU
- memory
- completion latency
- backend failure/restart behavior

Compare `ft8_lib` and `ft8mon` against current WSJT-X output.

### Checkpoint 4 - receive audio

No RF transmission.

First use explicit command-line validation of the DigiRig C-Media capture
endpoint, then integrate the chosen `FT8AudioInput`.

Test unplug/replug, unavailable device, overflow behavior, cancellation, and
runtime shutdown.

### Checkpoint 5 - offline encoder and waveform

No RF transmission.

Checkpoint 2 already implemented most of the hardware-independent QSO simulation
originally planned here. Checkpoint 5 therefore adds the project-owned offline
message/encoder/waveform boundary and reconciles the CQ-answer exchange against
the standard FT8 sequence before encoding it.

For the current MVP, an operator-authorized answer to a decoded CQ follows:

```text
remote local GRID4
remote local R+report
remote local 73
```

with received remote report and final RRR/RR73/73 controlling advancement.
The outbound report is frozen in `FT8QsoContext` at authorization time and is
restricted to the standard -50 through +49 dB range.

The selected encoder remains pinned `kgoba/ft8_lib` at
`9fec6ca39886edbf96f4f5e71edc76da5074e871`. Rolling Thunder's adapter
invokes only its offline `gen_ft8` executable, validates its packed payload
and 79-tone output, reads the generated temporary WAV back into immutable mono
S16_LE PCM, and removes the temporary file before returning.

Verified protocol/waveform constants from the pinned implementation are:

- 79 FT8 channel symbols;
- 0.160 second symbol duration;
- 6.25 Hz tone spacing;
- 12.64 seconds occupied modulation;
- 12 kHz sample rate;
- mono signed-16-bit little-endian PCM;
- 180,000 samples / 360,000 PCM bytes for the padded 15-second slot.

Checkpoint 5 does not compose the encoder into `ApplicationRuntime`, does not
create an audio output, and cannot open CAT/PTT or transmit RF.

The CQ browser/UI remains a later checkpoint. Existing Checkpoint 2 fake-driven
QSO tests continue to cover operator authorization, retry bounds, stale traffic,
ABORT, errors, and terminal behavior.

### Checkpoint 6 - PTT mechanism experiment

This is the first checkpoint that may perform tightly controlled physical
keying experiments, only after explicit owner approval.

Before testing:

- dummy load or otherwise approved RF-safe test setup
- transmit power and frequency explicitly controlled by operator
- no autonomous QSO logic connected to the test
- one copy/paste hardware command block at a time
- documented recovery/unkey procedure

The goal is only to establish the correct DR-891/FT-891 PTT mechanism and
fail-safe behavior.

### Later transmit checkpoint

Only after Checkpoint 6 proves the hardware boundary:

- implement bounded `DigitalTransmitSession`
- implement FT8 audio output
- integrate state-machine-driven encoded audio
- prove PTT release on every controlled error path
- retain manual ABORT
- keep automatic next-station selection prohibited

## Rollback/dependency policy

Checkpoint 1 introduces documentation only.

It does not change:

- Python dependencies
- native packages
- production YAML
- SQLite schema
- systemd
- udev
- groups/permissions
- serial configuration
- ALSA/PipeWire configuration
- FT-891 behavior

Before a later checkpoint changes any such resource,
`docs/V4.3_ROLLBACK.md` must record the exact addition and reversal procedure.

Decoder benchmarking should preferably happen in an experimental checkout or
worktree. The production `rolling-thunder.service` must continue to point to:

```text
/home/geoff/projects/rolling-thunder-v4
```

and must never be repointed to an experimental FT8 worktree.

## Checkpoint 1 decisions

1. Keep the generic `Radio` protocol receive-side.
2. Add future FT8 transmit authority through a separate narrow capability.
3. Keep UI free of serial/audio/timing/transmit ownership.
4. Use stable DigiRig ALSA card/device naming, not numeric ALSA card indexes.
5. Treat the Standard Com Port and C-Media HID PTT behavior as unverified.
6. Do not create a second Enhanced-CAT owner.
7. Use project-owned decode/QSO models so decoder backends remain replaceable.
8. Use WSJT-X as the reference oracle, not the embedded architectural core.
9. Benchmark both `ft8_lib` and `ft8mon` on the Pi before choosing receive
   backend.
10. Prefer `ft8_lib` as the initial all-stack candidate because it is
    permissively licensed and supplies both encode and decode capabilities.
11. Freeze local grid/location at QSO authorization.
12. Reuse the existing local-first contact logging path.
13. Keep six attempts per unchanged QSO state.
14. Make ABORT idempotent and available for the entire authorized QSO.
15. Keep FT8 disabled by default and compose no transmit authority while
    disabled.
16. Never automatically select or call another station after any terminal
    outcome.

## Checkpoint 2 entry recommendation

Checkpoint 2 should remain completely hardware-independent.

Begin by adding only:

- typed FT8 configuration with `enabled: false`
- project-owned domain models
- simulated UTC/monotonic clock
- CQ activity normalization
- QSO state machine driven entirely by fakes
- tests proving per-state retry, ABORT, frozen QSO grid, terminal cleanup, and
  disabled composition

Do not open DigiRig audio, install a decoder, open the Standard Com Port, add
PTT commands, or create a running FT8 worker in Checkpoint 2.


## Checkpoint 2 implemented foundation

Checkpoint 2 implements the hardware-independent portion of this architecture
under `src/rolling_thunder/ft8/`. It deliberately does not compose an FT8
runtime into the production application.

### Implemented modules

```text
src/rolling_thunder/ft8/
    __init__.py
    domain.py
    timing.py
    activity.py
    qso.py
    transmit.py
```

There are no placeholder decoder, encoder, audio, or logging modules.

### Configuration

The implemented typed configuration is:

```yaml
ft8:
  enabled: false
  qso:
    attempts_per_state: 6
```

The section is optional so older configuration files remain valid. FT8 remains
disabled by default. Checkpoint 2 adds no runtime FT8 composition, so parsing
`enabled: true` does not open hardware or start workers.

### Period and timing model

`FT8Period` uses a stable UTC-aligned 15-second index:

```text
period_index = floor(unix_utc_seconds / 15)
```

UTC determines protocol-slot identity and even/odd parity. Elapsed/deadline
behavior uses a separate monotonic source. `SystemFT8Clock` observes system
time without changing it, while `FakeFT8Clock` advances UTC and monotonic time
deterministically for tests without real sleeps.

### Normalized decode and CQ activity

`FT8Decode` is immutable and decoder-independent. It owns normalized period,
SNR, DT, audio frequency, raw message, message kind, callsigns, optional grid,
optional report, optional CQ qualifier, and read-only backend metadata.

`FT8CQActivityManager` accepts only normalized decodes. CQ entries are keyed by
normalized callsign, repeated CQs refresh the latest signal details, older
decodes cannot replace newer activity, and non-CQ traffic never becomes a
browser entry. The default expiry is four FT8 periods (60 seconds). Snapshots
are immutable and carry no station-selection or transmit authority.

### Frozen QSO authorization context

`FT8QsoContext` is created for exactly one operator-selected station and freezes
the local/remote callsigns, target audio frequency, radio frequency/band/mode,
local grid, optional location metadata, selected TX parity, and authorization
UTC/period. Later GPS/location changes cannot mutate an active context.

### QSO state machine

`FT8QsoController` implements explicit states:

```text
IDLE
AUTHORIZED
WAIT_TX_CALL
TX_CALL
WAIT_REPORT
TX_REPORT
WAIT_R_REPORT
TX_R_REPORT
WAIT_73
TX_73
COMPLETED
ABORTED
RETRY_EXHAUSTED
ERROR
```

The controller accepts an explicit authorization, starts slot-driven operation,
and advances only on fresh expected normalized decodes from the authorized
remote callsign. Traffic from another station, stale periods, duplicate periods,
wrong receive parity, or unexpected message kinds cannot redirect or advance
the QSO.

The six-attempt rule applies independently to each unchanged outbound
state/message. A valid response resets the counter for the newly advanced
state. After six unanswered attempts, the next eligible transmission
opportunity enters `RETRY_EXHAUSTED` rather than creating a seventh request.

ABORT is idempotent, terminal outcomes generate no additional requests, and an
explicit reset is required to discard the old authorization and return to
`IDLE`. Completion never begins another QSO automatically.

### Fake-only transmit boundary

`DigitalTransmitSession` is a narrow logical protocol. It accepts only an
immutable `FT8TransmitRequest` containing the already-frozen QSO context,
logical message kind, exact authorized FT8 period, and per-state attempt number.

Checkpoint 2 provides only `RecordingDigitalTransmitSession`, a test fake. It
contains no serial port, CAT command, PTT, audio device, waveform, or RF
implementation.

### Checkpoint 2 safety guarantee

Checkpoint 2 opens no FT8 audio device, installs no decoder, opens no FT-891
Standard Com Port, adds no PTT capability, adds no transmit-audio capability,
performs no database migration, and cannot transmit RF.


## Checkpoint 3 implementation boundary

Checkpoint 3 introduces the first receive decoder module but still does not
compose FT8 into production runtime behavior.

The decoder-facing input is project-owned `FT8PcmPeriod`: an explicit
`FT8Period`, sample rate, and immutable mono signed-16-bit little-endian PCM bytes. Saved WAV files
are a benchmark/test source only; backend-specific filenames and process/native
types are not the application decoder API.

The initial adapters are `Ft8LibDecoder` for `kgoba/ft8_lib` and
`Ft8monDecoder` for `rtmrtmrtmrtm/ft8mon`. Both normalize exclusively into
the existing `FT8Decode`; the Checkpoint 2 requirements for SNR, DT, and
positive audio frequency remain intact.

The exact candidate revisions and benchmark ledger live in
`docs/FT8_DECODER_BAKEOFF.md`.

Checkpoint 3 remains saved/reference-WAV receive-only: no DigiRig capture,
production worker, QSO execution, logging, PTT, CAT transmit command, transmit
audio, waveform generation, or RF transmission is added.


### Checkpoint 3 PCM representation

The decoder boundary stores one period as immutable signed-16-bit little-endian
PCM bytes rather than a Python tuple of integer sample objects. At 12 kHz, a
15-second mono FT8 period is therefore approximately 360 kB of payload rather
than several megabytes of Python integer/object overhead. WAV loading and
temporary saved-WAV adapters preserve those bytes directly.

This representation is backend-independent and is intended to remain suitable
for the later live-audio checkpoint without making the application layer depend
on WAV filenames, subprocess objects, or backend-native buffers.


### Checkpoint 3 selected receive backend

Checkpoint 3 selects `kgoba/ft8_lib` as the **initial** Rolling Thunder FT8
receive backend for the next integration checkpoint. The decision is based on
the documented Pi bake-off in `docs/FT8_DECODER_BAKEOFF.md`.

The selection prioritizes bounded decode latency and resource use required by a
future slot-driven mobile application while explicitly accepting lower measured
recall than `ft8mon` on the small saved-WAV oracle corpus. `ft8mon` remains
a higher-sensitivity comparison/fallback candidate; WSJT-X 3.0.2 remains an
oracle only.

The backend selection does not compose a decoder into the production runtime.
Live DigiRig audio remains a Checkpoint 4 concern.

## Checkpoint 4 live receive pipeline

Checkpoint 4 composes the first live FT8 receive-only path. It remains disabled
by default and adds no transmit authority.

The installed DigiRig DR-891 C-Media device was physically validated on
`anvilmobile` as native mono S16_LE at 44.1/48 kHz. ALSA
`plughw:CARD=Device,DEV=0` was then validated to provide mono S16_LE at
12 kHz directly, so Rolling Thunder does not add an application-side resampling
library or machine-wide ALSA/PipeWire configuration.

Initial capture testing found the USB codec at +23 dB capture gain with AGC on,
which heavily clipped the receive waveform. Receive-only test settings of AGC
off and 0 dB capture gain produced a clean test capture with approximately
-18.8 dBFS peak, -29.2 dBFS RMS, and no full-scale samples.

A live 15-second 12 kHz capture decoded successfully with the selected
`kgoba/ft8_lib` backend: the decoder exited successfully and produced 11
real on-air messages in the validation period.

The application boundary is `FT8AudioInput`. The concrete
`AlsaArecordFT8AudioInput` owns a persistent receive-only `arecord` process,
waits for a clean UTC 15-second boundary before opening the stream, reads exact
360,000-byte mono S16_LE periods, and releases the process/device on shutdown.

`FT8ReceiveService` owns separate capture and decode threads. Capture never
runs on Tkinter. A queue of at most one complete period separates capture from
decode; if decoding falls behind, stale queued work is discarded rather than
allowing an unbounded backlog. Decodes are normalized through the existing
`FT8Decoder` contract and CQ messages are published through the existing
`FT8CQActivityManager`.

When `ft8.enabled` is false, `ApplicationRuntime` does not construct an FT8
audio input, decoder, or receive worker. When enabled, the decoder executable
must be configured with an absolute path. The receive configuration owns the
ALSA selector, decoder timeout, and reconnect delay.

Checkpoint 4 remains strictly receive-only: no playback device, PTT, MOX, CAT
transmit command, transmit waveform, automatic QSO, station selection, or QSO
logging is added.


### Checkpoint 4 live application acceptance

The application-composed receive pipeline was physically exercised on
`anvilmobile` using the real DigiRig capture path and selected
`kgoba/ft8_lib` decoder while radio and GPS adapters remained mocked.

Observed acceptance result:

- two consecutive complete FT8 periods captured
- zero dropped periods
- 19 normalized decodes published
- four CQ activities retained by `FT8CQActivityManager`
- no receive-pipeline error
- clean transition from STARTING to RUNNING to STOPPED
- DigiRig capture device released on shutdown
- no orphaned `arecord` process after shutdown

This validates the live receive composition without enabling CAT, PTT,
playback, transmit audio, waveform generation, or RF authority.


### Checkpoint 4 unavailable-device recovery acceptance

The receive service was also started with the DigiRig intentionally absent.
The live application entered `DEGRADED` with the ALSA device-open failure,
without crashing or touching transmit hardware. After the C-Media DigiRig was
physically reconnected, the configured `plughw:CARD=Device,DEV=0` selector
resolved again automatically, the service returned to `RUNNING`, captured a
complete FT8 period, and decoded four on-air messages.

Shutdown after recovery released the DigiRig capture device and left no orphaned
`arecord` process. This validates startup-unavailable and reconnect recovery
without a machine-wide audio reconfiguration.


### Checkpoint 4 disabled-state acceptance

The application was physically exercised with `ft8.enabled: false`. In that
configuration `ApplicationRuntime` composed no `FT8ReceiveService`,
reported no FT8 receive state, started and stopped normally, opened no
`arecord` process, and left the DigiRig capture device unused.

This confirms the Checkpoint 4 feature gate prevents FT8 audio, decoder, and
receive-worker resource acquisition when disabled.
