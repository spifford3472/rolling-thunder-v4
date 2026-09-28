# Real Yaesu FT-891 Integration

## Scope

This document covers the installed Yaesu FT-891 integration and the safe
receive-only control path used by Rolling Thunder.

The implementation establishes and validates:

- stable USB device identity
- read-only CAT connection and background polling
- current VFO-A frequency and receive mode
- disconnect detection and automatic recovery
- independent typed band-context, frequency, and mode operations
- guarded cross-band receive tuning
- exact frequency and receive-mode read-back verification
- shared POTA/DX two-press receive tuning through `ReceiveTuningService`
- explicit manual band/ATAS-120 operator handoff after a cross-band receive tune

This work adds no PTT, MOX, CW keying, voice keying, tuner control, power control,
automatic transmission, or unattended transmit authority.

## Verified USB Interfaces

Live observation on `anvilmobile` identified the FT-891 USB bridge as a Silicon
Labs CP2105 dual UART with serial number `011F42E9`.

The two interfaces have different safety roles:

| Interface | Stable path suffix | Checkpoint-8 observed tty | Purpose |
| --- | --- | --- | --- |
| Enhanced Com Port | `if00-port0` | `/dev/ttyUSB2` | CAT state and approved receive control |
| Standard Com Port | `if01-port0` | `/dev/ttyUSB3` | PTT, CW keying, and digital TX control |

Rolling Thunder must use only the Enhanced Com Port:

```text
/dev/serial/by-id/usb-Silicon_Labs_CP2105_Dual_USB_to_UART_Bridge_Controller_011F42E9-if00-port0
```

The Standard Com Port must not be configured as `hardware.radio_device` and must
remain unopened.

The transient `/dev/ttyUSB*` numbers are diagnostic observations only. They may
change after reconnects or other USB enumeration changes; configuration must use
the stable `/dev/serial/by-id` path.

## Verified Serial Settings

The installed radio responded successfully with:

- 38,400 baud
- 8 data bits
- no parity
- 2 stop bits
- semicolon-terminated CAT commands and replies

The verified read commands include:

```text
FA;
MD0;
```

Read-only hardware tests confirmed current frequency and mode,
disconnect/reconnect recovery, and `transmitting=False`.

## Band Context, Frequency, and Mode Separation

Band context, exact frequency setting, and mode setting remain independent typed
operations:

```text
select_band(band)
set_frequency(frequency)
set_mode(mode)
```

The installed FT-891 does not provide a physically reliable CAT mechanism that
Rolling Thunder can treat as authoritative automatic operator-visible band
selection.

Checkpoint-8 bench testing established the final contract:

- exact receive frequency and mode changes are supported and verified
- same-band tuning does not recall a memory
- cross-band tuning may use an operator-programmed regular memory as
  **best-effort band context**
- successful memory recall does not prove that the radio's operator-visible band
  context changed correctly
- Rolling Thunder therefore never claims that a cross-band tune automatically
  selected the required band
- the operator remains responsible for manually setting/confirming the band and
  tuning the ATAS-120 before transmitting

The unresolved FT-891 CAT/front-panel band-context behavior is intentionally
parked in GitHub issue #149 and does not block checkpoint 8.

## Operator-Programmed Band Memories

The accepted regular-memory map is:

| Memory | Band |
| --- | --- |
| `001` | 160 m |
| `002` | 80 m |
| `003` | 40 m |
| `004` | 30 m |
| `005` | 20 m |
| `006` | 17 m |
| `007` | 15 m |
| `008` | 12 m |
| `009` | 10 m |
| `010` | 6 m |

The approved memory-context CAT operations are:

```text
MCxxx;    select regular memory xxx
MC;       read selected regular memory
MA;       copy selected memory to VFO-A
FA;       read VFO-A frequency
MD0;      read main receive mode
```

Rolling Thunder does not write these memories. `MW` and `MT` are outside the
approved path.

Raw physical testing verified, for example:

```text
MC010;
MC;      -> MC010;
MA;
FA;      -> 50.100 MHz
MD0;     -> USB

MC005;
MC;      -> MC005;
MA;
FA;      -> 14.150 MHz
MD0;     -> USB
```

The memory-to-VFO operation is therefore physically real, but it is retained as
best-effort context only because the radio's complete band-state behavior was
not reliable enough to claim authoritative automatic band selection.

The older `BSxx` encoder remains in the CAT module for compatibility with code
that may reference it, but checkpoint-8 shared spot tuning does not rely on
`BSxx` as its authoritative band-state mechanism.

## Required Receive-Tuning Order

`ReceiveTuningService` remains the sole approved receive-only tuning authority.

For a same-band target:

```text
read current radio state
set exact target frequency
read and verify exact target frequency
set receive mode when needed
read and verify receive mode
```

For a cross-band target:

```text
read current radio state

best-effort band context:
    select mapped regular memory with MCxxx;
    verify selected memory with MC;
    copy memory to VFO-A with MA;
    read FA; / MD0;
    require recalled frequency to belong to the target amateur band

set exact target frequency with FA#########;
read FA;
verify exact target frequency

set MD0x; when requested mode differs
read MD0;
verify requested receive mode

return a cross-band result
publish the manual operator handoff:
    SET BAND TO <BAND> METERS — TUNE ATAS-120
```

A direct cross-band `set_frequency()` call remains guarded and raises
`BandChangeRequiredError` before an unapproved raw frequency jump is sent.

A failed best-effort memory recall prevents the remainder of that ordered
receive-tune attempt. A successful recall, however, is not interpreted as proof
of authoritative FT-891 front-panel band selection.

Same-band tuning bypasses memory recall and still verifies frequency and mode.

`ReceiveTuningService` also refuses ordered receive tuning while the current
radio state reports `transmitting=True`.

## Shared POTA/DX Single-Press Path

Checkpoint 8 routes POTA and DX through the same operator-command and tuning
path:

```text
encoder / keyboard activation
    -> SharedSpotActivePanelCommandController
    -> SharedSpotTuneController
    -> ReceiveTuningService
    -> Ft891Radio
```

The current operator contract is one press:

```text
encoder / keyboard activation
    -> snapshot the exact currently selected identity/callsign/frequency/mode
    -> submit the action immediately to the background tune controller
    -> ReceiveTuningService
```

There is no persistent receive-confirmation/staging step.

Before submission, the active-panel command controller requires the latest radio
state to be connected, to have known frequency and mode, and not to report
transmitting. Otherwise the action fails closed. A busy tune worker rejects a
rapid duplicate activation rather than starting overlapping CAT work.

Selection remains identity-stable across refreshes. If the selected identity
disappears it is cleared rather than allowing a neighboring row to inherit the
operator action.

## Background Tuning Boundary

The single activation does not perform blocking CAT work in Tkinter.

`SharedSpotTuneController` owns background submission of the exact
`StagedSpotAction`. It publishes immutable tuning state for UI presentation:

- idle
- tuning
- succeeded
- failed

A busy background tuning boundary rejects a second concurrent submission rather
than creating overlapping receive-tune operations.

FT-891 CAT operations are serialized by the adapter's operation lock so polling
and receive tuning do not interleave command/response transactions.

## Configuration

The installed radio configuration uses the Enhanced CAT stable device path:

```yaml
hardware:
  radio_mode: real
  radio_device: /dev/serial/by-id/usb-Silicon_Labs_CP2105_Dual_USB_to_UART_Bridge_Controller_011F42E9-if00-port0
```

Use the stable `/dev/serial/by-id` path rather than a transient `/dev/ttyUSB*`
number.

The configured user must have serial-device access. User `geoff` is a member of
`dialout` on the verified Pi.

## Runtime Behavior

Radio polling owns initial connection and recovery outside Tkinter.

At startup:

- the application connects to the configured Enhanced CAT port
- successful connection publishes current frequency and mode
- failed connection publishes visible radio error state
- local services and GPS continue running
- polling remains scheduled and retries the stable device path

After a CAT failure or physical radio power-off:

- the adapter closes or marks the failed transport/state appropriately
- staged shared-spot actions are invalidated when radio state becomes unusable
- polling continues
- reconnection refreshes current hardware state without restarting the app
- an old staged target is not resurrected or automatically executed after
  recovery

Shared receive-tuning operations use the ordered application service after explicit
operator activation. Blocking CAT work must not run directly from a Tkinter widget
callback.

## ATAS-120 Manual Band / Tune Warning

A cross-band receive frequency change does not imply that the FT-891 is in the
correct operator-visible band context, and it never implies that the ATAS-120
is tuned or safe to transmit.

After a successful shared receive tune whose starting band differs from the
target band, the shared tune status controller publishes this amber message:

```text
SET BAND TO <BAND> METERS — TUNE ATAS-120
```

Current checkpoint-8 behavior is:

- same-band receive tuning publishes no band/ATAS warning
- successful cross-band receive tuning publishes the target-band manual handoff
- the warning has higher status priority than the normal tune-result message
- the warning expires automatically after 10 seconds
- success status is shown for 5 seconds
- failure status is shown for 8 seconds
- the warning does not claim that CAT changed the radio's authoritative band
  state
- the warning does not claim that the ATAS-120 is tuned

Back is not the ATAS acknowledgement mechanism. Within the shared POTA/DX panel,
Back clears selection. The band/ATAS reminder is a timed `StatusMessageService`
message.

The operator must manually set/confirm the FT-891 band and tune the ATAS-120
before transmitting.

## Safety Boundary

The typed radio and receive-tuning boundaries expose no command for:

- PTT or MOX
- CW keying
- voice keying
- digital-mode TX control
- tuner control
- radio power control
- unattended transmit
- voice-originated receive tuning

The Standard Com Port must remain unopened.

The shared spot controller, physical-control parser/mapper, Forge client, Forge
service, and Tkinter do not issue raw CAT commands.

`ReceiveTuningService` is the sole approved receive-tuning authority.

## Automated Coverage

Automated tests use fakes, mock radios, fake CAT transports, fake tuning
boundaries, and deterministic schedulers. Coverage includes:

- regular-memory `MCxxx` mapping for the configured 160 m through 6 m memories
- `MC;` selected-memory verification
- `MA;` memory-to-VFO-A recall
- no `MW` or `MT` memory-write command
- shared frequency-to-band resolution
- same-band tuning bypassing memory recall
- prohibited direct cross-band frequency changes
- recalled-frequency target-band verification
- exact frequency and receive-mode read-back verification
- failures stopping subsequent ordered operations
- ordered receive-tuning call sequence
- receive-tuning rejection while transmitting
- serialized FT-891 CAT operations
- single shared activation submitting the exact selected action
- rapid duplicate activation rejected while the background worker is busy
- POTA and DX sharing the same execution boundary
- stale/action-mutated staging rejection
- selection, filter, context, Back, and radio-state invalidation
- background tune success and failure state
- exact timed `SET BAND TO <BAND> METERS — TUNE ATAS-120` warning
- no band/ATAS warning for same-band tuning
- absence of PTT, MOX, keying, tuner, power, and Standard-Com-Port authority

Automated tests never open a physical serial device.

## Physical Checkpoint-8 Acceptance

Checkpoint-8 physical acceptance was completed on the installed `anvilmobile`
Raspberry Pi with the real FT-891 and installed physical controller while
parked.

Accepted results include:

- POTA first press tunes the selected receive frequency as expected
- DX first press tunes the exact selected DX frequency
- same-band operation produces no false `SET BAND ... TUNE ATAS-120` warning
- cross-band POTA exact receive frequency/mode tuning succeeds with the manual
  band/ATAS handoff
- cross-band DX exact receive frequency/mode tuning succeeds with the manual
  band/ATAS handoff
- selection identity remains stable across refreshes and clears if the target disappears
- band/mode filter changes cannot make a neighboring row inherit an activation
- Back clears selection without tuning
- radio power loss blocks activation
- reconnection does not auto-execute any prior selection
- Enhanced CAT remains the only FT-891 interface owned by Rolling Thunder
- the Standard TX-capable USB interface remains closed
- no PTT, MOX, keying, tuner, power, or transmit operation occurs
- retained POTA/DX data remains usable during a controlled Forge interruption
- local SQLite logging remains functional while Forge is unavailable
- the isolated offline-log acceptance test leaves the production contact count
  unchanged
- Forge hostname resolution and API access recover after the controlled outage
- all temporary outage/logging test artifacts are removed afterward

Automatic FT-891 band-state behavior is deliberately not claimed as accepted.
That future investigation remains tracked in issue #149.


## Checkpoint 2: Isolated ATAS CAT Bench Probe

Checkpoint 2 adds a diagnostic-only executable:

```text
rolling-thunder-ft891-atas-probe
```

It is intentionally not wired into the normal `Radio` protocol,
`ReceiveTuningService`, application runtime, Tkinter UI, physical controls, or
voice controls. Normal Rolling Thunder therefore retains its no-PTT/no-unattended-
transmit safety boundary.

The probe exists only to answer the narrow hardware question of whether FT-891
CAT can reproduce the manual ATAS procedure documented by Yaesu: transmit while
operating microphone UP or DOWN, then inspect the SWR meter.

The probe exposes only typed, fixed CAT operations:

```text
TX;       read TX state
TX1;      CAT PTT on
RX;       bench-verified force receive
TX0;      documented CAT PTT off
UP;       microphone UP
DN;       microphone DOWN
RM6;      SWR meter, raw 0-255
RM5;      power meter, raw 0-255
```

It does not accept arbitrary raw CAT strings.

Safety requirements are fail-closed:

- the normal dashboard and every other CAT client must be stopped first
- only the configured Enhanced CAT interface ending in `-if00-port0` is allowed
- the Standard Com Port remains unopened
- the radio must read `TX0` before the probe starts
- the operator must explicitly acknowledge that RF will be transmitted
- the operator must confirm an ATAS RF path and a radio power setting of 1-10 W
- inter-command delay is bounded to 0-500 ms
- pre-key countdown is bounded to 0-60 seconds
- keyed RF duration is bounded to 0.5-3.0 seconds
- any unexpected TX state or malformed response aborts the experiment
- both `RX;` and `TX0;` are attempted in a `finally` path before close

Two ordering experiments are supported:

```text
ptt-first:
    TX1;
    bounded delay
    UP; or DN;
    hold CAT PTT for a bounded 0.5-3.0 seconds
    TX; / RM6; / RM5;
    RX; / TX0;

control-first:
    UP; or DN;
    bounded delay
    TX1;
    bounded settle
    TX; / RM6; / RM5;
    RX; / TX0;
```

A CAT acknowledgement is not evidence that the ATAS moved. Physical motion and
the raw SWR trend must be observed on the installed hardware before any automated
ATAS tuning service is designed.

This checkpoint is research only. It does not authorize a production tuning
algorithm or unattended transmit.


### First installed-hardware observation

The first `ptt-first` test on the installed FT-891 at 5 W successfully keyed the
radio and returned `TX1` while keyed. `RM6;` and `RM5;` were also readable
during transmit, returning raw values of 142/255 and 34/255 respectively at
51.666 MHz FM. A single `UP;` command did not produce visible ATAS movement.

The next diagnostic step repeats the same typed UP or DOWN command at a bounded
interval of 100-500 ms during the keyed window, defaulting to 150 ms, to test
whether repeated CAT button events can approximate the manual held-button
behavior. This remains a research probe only; repeated CAT acknowledgements do
not prove motor motion.
