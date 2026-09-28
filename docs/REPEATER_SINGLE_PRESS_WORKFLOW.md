# Single-Press Six-Meter Repeater Configuration

Checkpoint #169 integrates the repeater panel with the typed FT-891 capability proven and bench-accepted by checkpoint #168. It changes only the operator/application workflow around that capability; it does not add raw CAT commands or any transmit authority.

## Operator control contract

The repeater context uses the existing physical-control path:

- **encoder rotation:** move the stable repeater selection;
- **single encoder short press:** snapshot the exact currently selected repeater and immediately submit one background radio configuration;
- **Back:** clear the current repeater selection;
- **Context Button #1:** switch Active-only / All;
- **Context Button #2:** toggle only the selected repeater's local Active state.

Context Button #2 cannot invoke repeater radio configuration. Active persistence and radio configuration remain deliberately separate application concerns.

## Single press: typed background configuration

`StagedRepeaterRadioAction` remains the immutable compatibility value passed to
the typed background configuration boundary, but it is no longer stored as a
first-press confirmation. The single encoder press derives the exact
`RepeaterRecord` plus `FmRepeaterConfigurationRequest` from the currently
selected visible row and offers it immediately to
`RepeaterConfigurationController`.

The UI/control callback returns immediately. A daemon worker calls
`RepeaterConfigurationService`, which can reach the radio only through the
typed `FmRepeaterConfigurableRadio` capability from #168.

While the worker is configuring, additional encoder presses are rejected. This
preserves duplicate rapid-event protection without requiring an operator
confirmation stage.

The background service exposes immutable status only:

- `configuring`;
- `configured`;
- `manual_handoff`;
- `failed`.

Tk reads that status during normal refresh; the worker never calls Tk.

## Selection and safety validation

The selected stable identity must still resolve to a visible current repeater at
activation time. Missing/stale GPS, filtering, source replacement, selection
loss, radio disconnect, incomplete radio state, or transmitting state prevents
submission. The command path never falls sideways to a neighboring repeater.

## Unsupported configurations

Checkpoint #169 does not weaken the #168 representability rules. In particular, the installed FT-891 exposes one CTCSS tone register, not independent RX and TX tone registers.

If a repeater requires a configuration that #168 cannot represent exactly, the typed radio capability returns `unsupported_manual_handoff`. The background controller exposes that outcome unchanged, and the repeater panel presents the manual-handoff message instead of claiming success.

## Successful configuration is not transmit authorization

A successful single press means only that the #168 receive/configuration sequence completed and read back correctly. The panel explicitly tells the operator to verify antenna/tuning before transmitting.

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

- single press submits exactly the selected repeater once;
- a rapid follow-up press while execution is active cannot replay;
- rotation, filter, context, Back, source mutation, Active change, and radio loss invalidate staging;
- reconnect does not restore stale staging;
- Context Button #2 remains Active-only;
- unsupported outcomes remain truthful manual handoffs;
- background execution never requires Tk-thread CAT access.

Real checkpoint acceptance must additionally exercise the installed physical controls on `anvilmobile` with the installed FT-891, using the already bench-accepted #168 radio capability. The acceptance must confirm same-band single-press execution, selection/safety behavior, Context Button #2 isolation, and truthful unsupported/manual-handoff presentation without adding any transmit authority.

## Installed acceptance — 2026-08-12

Checkpoint #169 was accepted on the installed `anvilmobile` system using the real vehicle control panel and FT-891 against exact PR #189 commit `83cff0cdefa6f43c95f5e0dd48ed0acde012e1ba`.

The operator verified:

- first encoder press staged the selected repeater without changing FT-891 frequency or mode;
- encoder rotation, Back, and Active/All filter changes preserved stable selection behavior without sideways fallback;
- Context Button #2 changed only local Active state without configuring the FT-891;
- the second identical encoder press performed the real #168-proven FT-891 repeater configuration exactly once;
- radio loss cleared a pending stage, and reconnect did not resurrect or execute it;
- the FT-891 Standard COM interface remained unopened for the entire installed test;
- no PTT, MOX, keying, or other transmit operation was exercised.

The optional installed manual-handoff case was skipped because no visible local repeater with an unsupported tone plan was available during acceptance. That path remains covered by automated tests, which require unsupported configurations to return truthful manual handoff rather than fabricated success.

After acceptance, the temporary PR worktree and test UI were removed and the normal Rolling Thunder UI was restored successfully.