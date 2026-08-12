# Two-Press Six-Meter Repeater Configuration

Checkpoint #169 integrates the repeater panel with the typed FT-891 capability proven and bench-accepted by checkpoint #168. It changes only the operator/application workflow around that capability; it does not add raw CAT commands or any transmit authority.

## Operator control contract

The repeater context uses the existing physical-control path:

- **encoder rotation:** move the stable repeater selection;
- **first encoder short press:** stage the exact selected repeater and all action-critical radio values;
- **second encoder short press:** if that exact stage is still valid, submit one background radio configuration;
- **Back:** cancel a pending radio stage before clearing selection;
- **Context Button #1:** switch Active-only / All;
- **Context Button #2:** toggle only the selected repeater's local Active state.

Context Button #2 cannot invoke repeater radio configuration. Active persistence and radio staging are deliberately separate application concerns.

## First press: zero radio work

`StagedRepeaterRadioAction` is an immutable application value containing the exact `RepeaterRecord` plus the typed `FmRepeaterConfigurationRequest` derived from it. The stage captures:

- selected stable identity;
- RX frequency;
- derived shift direction;
- absolute offset;
- RX CTCSS value;
- TX CTCSS value.

Creating this stage performs no CAT, serial, radio, filesystem, SQLite, or network operation.

## Second press: one background configuration

A second encoder short press is accepted only while the same still-valid stage remains present and the radio state is usable. The UI/control callback submits the immutable action to `RepeaterConfigurationController` and returns immediately. A daemon worker calls `RepeaterConfigurationService`, which can reach the radio only through the typed `FmRepeaterConfigurableRadio` capability from #168.

The accepted second press consumes the confirmation immediately. While the worker is configuring, additional encoder presses cannot create or replay another repeater stage. This provides exactly-once submission at the operator-command boundary and prevents a rapid third press from reconfiguring the radio again.

The background service exposes immutable status only:

- `configuring`;
- `configured`;
- `manual_handoff`;
- `failed`.

Tk reads that status during normal refresh; the worker never calls Tk.

## Stage invalidation

A pending radio stage is discarded rather than silently retargeted when any confirmation-critical condition changes:

- encoder selection changes;
- the repeater context changes;
- Active-only / All filter changes;
- the selected source record changes in any action-critical field;
- the selected record disappears or becomes filtered out;
- GPS/nearby state becomes unavailable or stale;
- Context Button #2 changes local Active state;
- Back/Cancel is pressed;
- radio state becomes disconnected, incomplete, or transmitting;
- a confirmed execution is accepted.

Reconnect does not reconstruct a previous stage. The operator must explicitly stage again. Stable identity never falls sideways to a neighboring repeater.

## Unsupported configurations

Checkpoint #169 does not weaken the #168 representability rules. In particular, the installed FT-891 exposes one CTCSS tone register, not independent RX and TX tone registers.

If a repeater requires a configuration that #168 cannot represent exactly, the typed radio capability returns `unsupported_manual_handoff`. The background controller exposes that outcome unchanged, and the repeater panel presents the manual-handoff message instead of claiming success.

## Successful configuration is not transmit authorization

A successful second press means only that the #168 receive/configuration sequence completed and read back correctly. The panel explicitly tells the operator to verify antenna/tuning before transmitting.

This workflow adds no:

- PTT or MOX;
- voice/CW/digital keying;
- tuner activation;
- RF power control;
- automatic or unattended transmission;
- Standard COM ownership;
- raw CAT in Tk, physical-control adapters, or repeater panel code.

The FT-891 CAT details remain encapsulated in the #168 adapter/capability layer.

## Validation boundary

Automated acceptance covers:

- first press performs zero radio execution;
- second identical press submits exactly the staged repeater once;
- a third press while execution is active cannot restage or replay;
- rotation, filter, context, Back, source mutation, Active change, and radio loss invalidate staging;
- reconnect does not restore stale staging;
- Context Button #2 remains Active-only;
- unsupported outcomes remain truthful manual handoffs;
- background execution never requires Tk-thread CAT access.

Real checkpoint acceptance must additionally exercise the installed physical controls on `anvilmobile` with the installed FT-891, using the already bench-accepted #168 radio capability. The acceptance must confirm same-band staging/execution, cancellation/invalidation behavior, Context Button #2 isolation, and truthful unsupported/manual-handoff presentation without adding any transmit authority.
