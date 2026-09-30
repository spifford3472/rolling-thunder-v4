# Real Yaesu FT-891 Integration

## Scope

This document covers the installed Yaesu FT-891 integration. The normal
Rolling Thunder radio path remains receive-only. Rolling Thunder v4.3
Checkpoint 6 separately permits a disabled-by-default, owner-initiated,
physically supervised FT8 hardware-test capability while that boundary is
being validated.

The implementation establishes and validates:

- stable USB device identity
- read-only CAT connection and background polling
- current VFO-A frequency and receive mode
- disconnect detection and automatic recovery
- independent typed band-context, frequency, and mode operations
- guarded cross-band receive tuning
- exact frequency and receive-mode read-back verification
- shared POTA/DX single-press receive tuning through `ReceiveTuningService`
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

The normal Rolling Thunder `hardware.radio_device` path must use only the Enhanced Com Port:

```text
/dev/serial/by-id/usb-Silicon_Labs_CP2105_Dual_USB_to_UART_Bridge_Controller_011F42E9-if00-port0
```

The Standard Com Port must not be configured as `hardware.radio_device`.
Checkpoint 6 may inspect it non-destructively and may use it only if a later
owner-approved physical test proves that it is the single safest FT8 PTT
mechanism. No RTS/DTR line may be manipulated speculatively.

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

The current operator contract is one activation on the currently selected,
still-valid target:

```text
single press
    -> validate current radio state and selected identity
    -> snapshot exact callsign/frequency/mode
    -> submit the exact action
    -> background receive tuning
    -> ReceiveTuningService
```

There is no persistent receive-confirmation stage.

Before tuning, the active-panel command controller requires the latest radio
state to be connected, to have known frequency and mode, and not to report
transmitting. Otherwise the activation fails closed.

The submitted action is an exact snapshot of the selected identity, callsign,
frequency, and mode. Selection/filter/context changes after submission cannot
redirect that in-flight action to a neighboring row.

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

Shared receive-tuning operations use the ordered application service only after
explicit operator activation. Blocking CAT work must not run directly from a
Tkinter widget callback.

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

Back is not the ATAS acknowledgement mechanism. Within the current shared
POTA/DX panel, Back clears the selected row. The band/ATAS reminder is a timed
`StatusMessageService` message.

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
- POTA and DX sharing the same execution boundary
- exact selected-action snapshot behavior
- selection, filter, context, Back, and radio-state rejection/cancellation behavior
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

- POTA single press tunes the selected receive frequency as expected
- DX single press tunes the exact selected DX frequency
- same-band operation produces no false `SET BAND ... TUNE ATAS-120` warning
- cross-band POTA exact receive frequency/mode tuning succeeds with the manual
  band/ATAS handoff
- cross-band DX exact receive frequency/mode tuning succeeds with the manual
  band/ATAS handoff
- selection, band-filter, and mode-filter changes do not execute a stale target
- Back clears selection without tuning
- radio power loss prevents activation
- reconnection does not resurrect or execute an old target
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


## POTA/DX Callsign Preload

The current single-press POTA/DX activation also preloads the exact selected
spot callsign into the existing pending callsign field after the background tune
request is accepted.

Operator behavior:

- encoder rotation/highlighting alone does not change the pending callsign
- pressing the encoder on a valid selected POTA/DX spot starts the existing
  receive-tune path and preloads that spot callsign
- the preloaded value is immediately Commit-ready
- a later Voice command can replace it through the normal speech-capture path
- rejected tuning does not alter the pending callsign

This intentionally handles stale spot data: if another operator takes over the
frequency before the provider refreshes, the operator can use Voice to replace
the automatically preloaded callsign before Commit.


## v4.3 Checkpoint 6 experimental FT8 transmit boundary

The generic `Radio` interface and ordinary receive-tuning path remain
receive-only. Checkpoint 6 does not add PTT or generic transmit methods to
`Radio`.

Physical FT8 testing must use a separate explicit owner-test executor that:

- cannot be injected as the `DigitalTransmitSession` consumed by
  `FT8QsoController`;
- serializes any Enhanced-CAT PTT command through the existing `Ft891Radio`
  ownership/locking path if CAT PTT is selected;
- uses exactly one verified PTT mechanism;
- accepts only completely prepared bounded PCM;
- guarantees release in normal, cancel, timeout, exception, and close paths;
- remains disabled and uncomposed in the production runtime during Checkpoint 6.

The selected PTT mechanism and measured lead/tail/watchdog timings must be added
here after physical acceptance.

### Checkpoint 6B CAT PTT hardware validation — 2026-09-29

Physical owner-supervised testing on `anvilmobile` validated the narrow CAT PTT path against the FT-891 with a dummy load connected.

- Enhanced CAT interface 00 remained the only PTT control path.
- Stable device: `/dev/serial/by-id/usb-Silicon_Labs_CP2105_Dual_USB_to_UART_Bridge_Controller_011F42E9-if00-port0`.
- CAT rate: 38400 bps.
- `TX1;` visibly placed the FT-891 control head into transmit.
- The bounded test then sent `TX0;` and completed without leaving the radio keyed.
- No DigiRig audio was played.
- Standard interface 01, RTS, and DTR were not used.
- Production Rolling Thunder was stopped only long enough to release the CAT device and was restarted after the test.

This validates CAT PTT as the selected Checkpoint 6 physical keying mechanism. It does not authorize automated QSO transmission. DigiRig playback and combined audio/PTT remain separate later validation phases.

### Checkpoint 6C DigiRig playback validation — 2026-09-29

The initial playback-only test exposed an important DR-891 behavior: mono playback through `plughw:CARD=Device,DEV=0` caused the radio to enter transmit because payload audio reached the DR-891 right-channel VOX/PTT path.

The playback adapter was then changed to explicit stereo S16_LE with FT8 payload on the left channel and digital silence on the right channel. The owner-supervised retest passed:

- FT8 payload: left channel only.
- Right channel: all-zero PCM.
- No CAT PTT command was sent.
- No Standard-port, RTS, or DTR control was used.
- The FT-891 TX indicator remained off for the entire finite playback.
- No RF transmission occurred.
- The `aplay` process exited normally.
- The DigiRig playback PCM device was released after playback.

This validates left-only stereo playback as the Checkpoint 6 audio mechanism. Combined CAT PTT plus playback remains a separate Phase 6D validation and is not yet authorized for automated QSO operation.

### Checkpoint 6D DATA-mode CAT PTT + meter isolation — 2026-09-29

Owner-supervised dummy-load isolation test passed the transmit-control and CAT-meter portions before FT8 audio was added:

- Radio verified at 14.074 MHz and temporarily changed from USB to DATA.
- CAT PTT asserted and the FT-891 visibly entered transmit for about three seconds.
- No DigiRig audio was played.
- Repeated CAT meter reads succeeded while keyed.
- After the initial transition sample, ALC stabilized at raw 002, POWER at raw 001, and SWR at raw 000.
- The first ALC read immediately after keying returned raw 252 and is treated as a transition sample, not a steady-state reading.
- CAT PTT release returned the radio to receive.
- An immediate attempt to restore USB reported DATA on verification. This is consistent with a post-PTT command/readback timing race and must be handled with a short receive-settle delay before mode restoration in the owner test harness.
- Production service was restarted successfully.

This test validates that CAT PTT and RM4/RM5/RM6 sampling can coexist on the serialized Enhanced CAT path. FT8 audio was not involved in this isolation test.

### Checkpoint 6D harness refinements — 2026-09-29

For subsequent combined RF tests, the owner-side harness must:
- wait 0.5 seconds after CAT PTT release before restoring the pre-test mode, to avoid the observed immediate post-TX mode readback race;
- retain all raw meter samples in the log, but exclude the first two samples after key-up from steady-state ALC/power/SWR summaries;
- continue to treat every CAT meter value as the FT-891 documented raw 0-255 scale rather than watts, SWR ratio, or calibrated ALC units;
- keep the 17-second software key-down bound and unconditional CAT TX-off cleanup.

### Checkpoint 6D full combined FT8 dummy-load test — 2026-09-29

The first full owner-supervised combined test passed the transmit-control path at 14.074000 MHz in DATA mode with the FT-891 power menu set to 5 W:

- CAT PTT asserted and the radio visibly transmitted.
- The validated left-only FT8 waveform played through the DigiRig.
- Right-channel digital silence did not trigger the DR-891 VOX/PTT path independently.
- The executor completed the full slot and returned the radio to receive automatically.
- No aplay process remained and the DigiRig playback device was released.
- Production service restarted successfully.
- 30 CAT meter samples were captured during the slot. Sustained raw POWER was about 31-35, sustained raw ALC about 115-128, and raw SWR reported 255 during the modulated portion, returning to 0 when RF fell away.
- The owner identified the test load as a homemade dummy load with known high SWR; the normal antenna does not exhibit that high SWR. The raw SWR=255 result therefore reflects the test load and is not treated as a transmit-path fault.

Interpretation notes:
- Yaesu CAT meter outputs are raw relative values rather than calibrated engineering units.
- The sustained ALC raw level is significantly above the no-audio baseline and should be investigated before antenna transmission; DATA DATA GAIN and/or playback amplitude may need reduction.

### Checkpoint 6D ALC optimization — DATA DATA GAIN 25

With FT-891 menu 16-14 DATA DATA GAIN reduced from 50 to 25, the owner-supervised 5 W dummy-load FT8 test completed successfully.

Observed modulation-period raw CAT meter values:
- ALC: approximately 24-35 raw during sustained FT8 modulation (versus roughly 115-128 at gain 50).
- POWER: approximately 29-35 raw during sustained modulation, essentially unchanged from the gain-50 test.
- SWR: 255 raw on the known high-SWR homemade dummy load, returning to 0 when modulation ended.

This shows that reducing DATA DATA GAIN substantially lowers ALC without materially reducing output power at the configured 5 W level. Menu 16-14 was manually changed to 25 for this test and remains a reversible radio-side setting.

### Checkpoint 6D ALC optimization — DATA DATA GAIN 20

With FT-891 menu 16-14 DATA DATA GAIN reduced to 20, the owner-supervised 5 W dummy-load FT8 test completed successfully.

Observed modulation-period raw CAT meter values:
- ALC: approximately 2-9 raw during sustained FT8 modulation.
- POWER: approximately 29-35 raw during sustained modulation, essentially unchanged from the gain-25 and gain-50 tests.
- SWR: 255 raw on the known high-SWR homemade dummy load, returning to 0 when modulation ended.

This is the best observed ALC result so far: compared with gain 50 (roughly 115-128 raw) and gain 25 (roughly 24-35 raw), gain 20 minimizes ALC while preserving the configured 5 W output behavior. Menu 16-14 is currently set to 20 and remains a reversible radio-side setting.

