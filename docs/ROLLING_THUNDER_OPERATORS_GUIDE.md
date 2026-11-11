# Rolling Thunder Operator's Guide

## About this guide

Rolling Thunder is a mobile amateur-radio operating console built to reduce the
number of separate applications, displays, and manual lookups an operator must
manage while driving or operating portable/mobile.

This guide describes the current implemented system from the operator's point
of view. It explains what each screen is for, what information it shows, how the
controls behave, what alerts or degraded states may appear, and which functions
depend on the Forge backend.

The engineering documentation under `docs/engineering/` is the companion
developer reference. This document intentionally emphasizes use rather than
implementation.

---

# 1. What Rolling Thunder Is

Rolling Thunder brings together several operating tasks that would otherwise
require multiple programs:

- radio frequency and mode awareness;
- receive tuning;
- callsign capture and contact logging;
- POTA and DX opportunity discovery;
- native FT8 receive/QSO operation;
- nearby six-meter repeater selection;
- DMR hotspot monitoring and contact logging;
- GPS position and Maidenhead grid;
- live/offline mapping;
- weather, radar, and severe-weather alerts;
- contact information and prior-QSO context;
- synchronization to the home logging system.

The goal is not to automate the operator out of amateur radio. The goal is to
reduce workload while keeping important actions explicit, predictable, and
visible.

## Core operating philosophy

### Local first

The Raspberry Pi in the vehicle is the primary operator console. Local functions
such as radio state, GPS, local contact storage, and installed map data should
remain useful even when cellular service, WireGuard, Forge, or a public provider
is unavailable.

### Preserve the contact first

A completed contact is written to the local Rolling Thunder database before
remote synchronization is considered complete. Loss of the home network or
Wavelog does not make a locally committed contact disappear.

New POTA, DX, Browse, and FT8 contacts retain their originating workflow and a
best-effort configured transmit-power snapshot. New ordinary QSO notes remain blank
unless explicitly supplied; automatic POTA/mobile/weather notes are no longer added.
Existing saved notes and structured weather remain intact; contact synchronization
never waits on public weather.
Unavailable weather never prevents saving or synchronizing the QSO.
The capture uses only fresh weather already published for the car and the exact
contacted callsign/target. Retained car weather must also match the contact's frozen
local coordinates or, when those are unavailable, its frozen local grid. Stale or
mismatched endpoint weather remains `N/A`, and later
retries retain the original snapshot rather than replacing it with newer conditions.

### Shared behavior stays consistent

POTA, DX, Browse, FT8, DMR, and other screens share services such as GPS,
contact logging, radio state, and callsign information. This is why the same
operator concepts behave consistently across screens.

### Deliberate radio authority

Receive tuning is intentionally controlled through typed application services.
FT8 transmission is a separate, explicitly authorized and bounded workflow.
Rolling Thunder does not treat ordinary screen selection as permission for
unattended transmission.

---

# 2. System Overview

## anvilmobile

`anvilmobile` is the Raspberry Pi that runs the full-screen Rolling Thunder
dashboard in the vehicle.

It handles the operator interface, FT-891 control, GPS, local storage, physical
controls, installed/offline map packages, FT8 audio/decoding/encoding, and
local-first contact workflows.

## Forge

Forge is the backend server used for provider-facing and heavier network work.

Forge currently provides services for:

- POTA and DX spot aggregation;
- persistent DX Summit IRC ingestion;
- retained provider health;
- callsign/contact intelligence;
- QRZ enrichment where configured;
- Wavelog history and contact synchronization;
- mobile-location intake;
- weather;
- severe-weather alerts;
- radar.

Forge is designed as a reusable backend. Its services are not tied exclusively
to the Rolling Thunder display and may be consumed by other authorized software
in the future.

## Radio and interfaces

The installed mobile radio path centers on the Yaesu FT-891. CAT is used for
approved control/state functions. FT8 audio uses the DigiRig/audio path and a
separately bounded FT8 transmit workflow.

## GPS

The GPS receiver supplies current vehicle position and movement information.
Rolling Thunder uses that shared position for:

- the live map;
- Maidenhead grid;
- contact logging;
- FT8 QSO context;
- repeater-distance calculations;
- Forge mobile location;
- location-aware weather alerts.

## Physical controls

Rolling Thunder maps physical controls into generic operator actions such as:

- move previous / next;
- activate the current selection;
- Back;
- next/home context;
- Context Button #1, #2, and #3;
- Voice;
- Commit;
- Discard.

The exact meaning of the context buttons depends on the active screen and is
described in each section below.

---

# 3. Starting Rolling Thunder

Rolling Thunder is managed by `rolling-thunder.service`.

## Three-minute minimum system uptime

The dashboard uses a minimum Raspberry Pi uptime of 180 seconds.

If the Pi has just booted, Rolling Thunder waits only until the Pi itself has
been up for three minutes. This allows the desktop, USB hardware, storage, and
network environment to settle.

If the Pi has already been running for more than three minutes and the service
is restarted, Rolling Thunder starts immediately rather than imposing another
three-minute delay.

The launcher also prevents a second dashboard process from being started for the
same user.

## What to expect after startup

The dashboard may initially show unavailable or degraded states while hardware
and retained/network services publish their first state. These states should
recover independently as their corresponding services become available.

A network service being unavailable should not be interpreted as failure of the
entire console.

---

# 4. Reading the Dashboard

## Contexts

The current dashboard contexts are:

- POTA
- DX
- BROWSE
- FT8
- REPEATERS
- AI
- WEATHER
- SETTINGS
- LOG
- DMR
- ANTENNAS / RF EXPOSURE (only when explicitly enabled in configuration)

The persistent map/situational region is separate from the normal context page.

## Status and health

Rolling Thunder favors explicit health/status words rather than relying on color
alone.

Common meanings include:

- **ready/live/healthy** — current usable data;
- **retained/stale/degraded** — useful prior data remains available but current
  refresh or freshness is degraded;
- **disabled** — feature intentionally turned off;
- **unavailable** — no usable current/retained state is available;
- **error/failure** — an attempted action or service operation failed.

Color is used as a glance aid, but status text is authoritative.

## Pending callsign, Commit, and Discard

Several workflows can place a callsign into the shared pending-contact state.
This can come from voice capture or from selecting an operating opportunity such
as POTA/DX/FT8.

**Commit** writes an eligible pending contact through the local durable logging
path.

**Discard** clears the pending callsign when the operator did not complete the
contact.

A pending callsign may also trigger the shared callsign-information overlay when
that feature is enabled.

On the POTA, DX, and FT8 station browsers, the overlay is selection-driven rather
than highlight-driven. An explicit accepted station action can show it. Moving the
highlight, changing band, or leaving the context dismisses it until another
explicit accepted station action.

---

# 5. POTA Screen

## Purpose

The POTA screen helps the operator find current Parks on the Air activations,
filter them for the desired mobile operating conditions, select a station, tune
the receiver, and preload the callsign for the contact workflow.

## What is shown

The screen presents provider-neutral spot cards containing the most useful
current POTA information available from the retained Forge snapshot, including
callsign, frequency/mode, park information, and available enrichment.

Worked state is shown separately from spot identity so a later spot for the same
callsign/mode/band can still be recognized as worked even if the exact frequency
or park changes.

## Controls

- **Encoder / move previous-next** — move stable selection through visible POTA
  spots.
- **Encoder press / activate selection** — submit the exact selected receive
  target through the shared receive-tuning path and preload the callsign.
- **Context Button #1** — cycle the POTA band filter.
- **Context Button #2** — cycle the POTA mode filter.
- **Back** — clear the current selection.

The supported shared mobile HF band cycle is 80, 40, 20, 17, 15, 12, and 10
meters. POTA shows only Phone/SSB and CW spots. The mode cycle is ALL, SSB/PHONE,
and CW; ALL means all of those allowed voice/CW modes and never includes digital
spots. Distinct activators remain separate rows even when they share the same park
and exact frequency, such as operators handing one microphone between contacts.

## Selection safety

Selection is tied to a stable spot identity, not a row number. If refresh changes
the list, Rolling Thunder will not silently redirect an action to a neighboring
row.

If action-critical data changes or the selected spot disappears, staging/
selection is invalidated rather than guessed.

## Tuning

A POTA selection uses the shared receive-tuning service. If the radio state is
not usable—for example disconnected or transmitting—the action is rejected.

A cross-band operation may produce an operator reminder to establish the correct
front-panel band/ATAS context rather than pretending CAT has completed an
unsupported physical/radio step.

## Callsign information

When callsign information is enabled, the selected/pending POTA callsign can
trigger the shared contact-information overlay after an accepted encoder press.
POTA park coordinates have
priority for target weather/map placement when the contact is known to be at a
current park activation.

The overlay itself is shared infrastructure and is not a POTA-only popup.
Encoder browsing and an accepted band-filter change dismiss it; merely highlighting
the next row does not open another popup. Pressing the selected station again may
show it again without adding a confirmation press or changing receive tuning.

## If POTA data is unavailable

Forge retains the last complete durable POTA/DX snapshot when a new combined
snapshot cannot be stored. A supported digital-mode row is valid snapshot data even
though the mobile POTA filter intentionally presents only SSB/phone and CW; it must
not invalidate the retained snapshot refresh.

A provider or Forge outage may leave retained state available. Rolling Thunder
should identify retained/degraded state truthfully rather than treating old data
as live.

Local logging, radio, GPS, maps, and unrelated screens continue independently.

---

# 6. DX Screen

## Purpose

The DX screen presents current DX spots from the Forge retained spot service and
uses the same stable selection/tuning framework as POTA.

## Where the spots come from

Forge maintains one long-lived connection to the DX Summit IRC feed. Forge
ingests the live `#CQDX` stream continuously, retains a bounded cache, and
publishes DX data through the Forge API.

Rolling Thunder on the Pi does **not** connect directly to DX Summit.

This avoids repeated connect/scrape/disconnect behavior and allows Forge to
serve the same backend data to other authorized applications in the future.

## Controls

- **Encoder / previous-next** — move through visible DX spots.
- **Encoder press** — tune to the exact selected receive target and preload the
  callsign.
- **Context Button #1** — cycle DX band filter.
- **Context Button #2** — cycle DX mode filter.
- **Back** — clear selection.

DX uses the same supported mobile HF bands as POTA. DX shows only Phone/SSB and
CW spots. Its mode cycle is ALL, SSB/PHONE, and CW, with ALL limited to those
allowed modes.

After a DX contact is successfully committed to local storage, every DX spot
for that callsign on the same amateur band is marked with the light-blue worked
treatment and `— WORKED` for the rest of the current UTC day. Exact frequency
and mode do not change the DX worked marker; a spot for the callsign on another
band remains unworked. A failed or discarded contact is not marked worked.

## Health and freshness

Forge exposes provider health separately from spot data. A healthy DX service
means the retained/publication path is functioning; retained/degraded states
should be read as such.

A silent radio band is not by itself proof that the IRC connection failed.

The shared callsign-information overlay follows the same DX behavior as POTA:
an accepted encoder press may show the selected station, while browsing rows,
changing the band filter, or leaving DX dismisses it. Re-selecting the same or a
different station can show it again and still uses the existing single-press tune.

## DX Summit reconnect behavior

A healthy connection can remain open for weeks or months. Connection age does
not trigger reconnect. Forge reconnects only after a genuine connection failure
and uses backoff.

---

# 7. Browse Screen

## Purpose

Browse is the free-form operating screen for ordinary receive tuning and contact
capture outside a spot/repeater-specific workflow.

## Controls

- **Encoder** — move frequency up/down by the currently selected tuning step.
- **Context Button #2** — cycle the tuning step.
- **Context Button #3** — cycle the Browse mode.
- **Voice / callsign capture** — capture a callsign through the shared pending
  callsign workflow.
- **Commit / Discard** — complete or cancel the pending contact workflow.

The supported Browse controls execute through background radio-control services;
the Tkinter screen itself does not open CAT.

## Optional Tron voice commands

Tron voice commands are disabled by default. After `tron.enabled: true` is
configured alongside offline speech, tap the physical callsign **Discard/Cancel**
button three times within two seconds to start or stop listening. Each press
keeps its normal discard behavior. The listener starts as soon as the offline
model is ready; there is no countdown. F12 remains available as a keyboard
shortcut when a keyboard is attached.
A large 20-point popup shows start/stop results and the answer to **“Tron
status”** for three seconds. Other successful Tron commands do not create
status boxes; navigation itself shows the result.

Every command must begin with “Tron”. Supported commands include help, status,
current screen; show POTA, DX, Browse, FT8, Weather, Repeaters, DMR, log, or
settings; next/previous station; first/last station; and select/choose station.
These movement commands use the current screen’s existing selection controls.
“Select station” only highlights the current station; use the physical controls
to approve or reject a QSO. Voice cannot authorize a QSO, transmit, change RF
power, commit a contact, tune Browse, configure a repeater, or edit settings.
Unsupported phrases are ignored.

The physical callsign button always takes microphone priority. It cancels an
active Tron recording, waits for its audio process to exit, and then runs the
existing callsign capture. Listening resumes afterward if it was active. If the
microphone is unavailable, the status bar reports the condition and callsign
capture retains priority.

Rolling Thunder can present U.S. Amateur Extra band/mode advisories. These are
operator warnings, not a substitute for operator responsibility or regulatory
knowledge.

## Contact location

Normal contact logging uses the shared current GPS/Maidenhead state available at
the appropriate contact lifecycle point.

---

# 8. FT8 Screen

CP3 supervised power pilot: new FT8 QSO attempts start at 20 W. When enabled
by operator-approved power configuration, repeated unanswered grid calls may
raise CAT power in verified 5 W steps under the existing band ceilings.
Report/73 messages do not trigger increases. Manual power changes suspend
automatic control for the current QSO; abort remains available. Directional
PSK observations currently rank DX opportunities, not calibrated wattage.


The FT8 DX Intelligence screen displays up to ten CQ rows at once. Above and
below overflow indicators are bright white and match the CQ callsign font size.
FT8 station rows use 30-point bold text, matching the top DX recommendation,
and CALL receives one-quarter of the table width for a denser display.
The top DX recommendation uses larger lettering. Compact row spacing preserves
the mobile view; actual legibility requires operator visual acceptance.

The FT8 DX Intelligence browser shows CALL, COUNTRY (conservative callsign-prefix
abbreviation from the offline prefix table, expanded with selected ARRL/ITU allocations;
unknown prefixes display a dash, not a guessed country), GRID, and REACH (LOW/MEDIUM/HIGH ranking confidence or PENDING).
A compact TOP recommendation summarizes the first currently ranked CQ.
REACH is **not** a numerical probability of making a contact. Unknown propagation
or missing Forge observations result in neutral ranking, not a claim the path is closed.
The old SNR/audio diagnostic values remain in the receive diagnostics and
underlying CQ data, but no longer occupy browser table columns. Encoder selection,
receive-only operation, and incoming call presentation remain unchanged.



## Purpose

The FT8 screen is a native Rolling Thunder FT8 CQ browser and bounded one-QSO
operator workflow. It is not simply a general list of all decoded messages.

## CQ browser

A station enters the browser when Rolling Thunder decodes it calling CQ.
Subsequent non-CQ activity may update informational fields but cannot extend the
six-period lifetime measured from the most recent actual CQ.

Typical states include:

- **yellow** — actual CQ age 0-1 periods;
- **white** — actual CQ age 2-3 periods;
- **gray** — actual CQ age 4-5 periods;
- **red + !** — failed/exhausted attempt for that callsign/band today;
- **blue + square marker** — operator-aborted attempt;
- **tree/POTA marker** — CQ explicitly included a POTA indication.

A successful callsign/band contact is removed from the eligible list for the
rest of the UTC date. A U.S. callsign explicitly calling `CQ DX` is not listed as
an eligible FT8 target. An explicit `CQ POTA` remains eligible and carries the
green tree marker. The far-right side of the FT8 status area shows the parsed
decode count from the most recently completed decode cycle in the same large type as
the FT8 header. It is hidden when no count is available and on every other screen.

## Controls

- **Encoder** — move through eligible CQ stations.
- **Encoder press** — explicitly authorize/start one QSO with the selected
  station when transmit is enabled and all checks pass.
- **Context Button #1** — cycle supported FT8 bands and tune the standard FT8
  dial frequency.
- **Context Button #3** — abort an active FT8 QSO; in terminal/result state it
  returns to the browser.
- **Back** — abort active work, acknowledge terminal state, or clear selection
  depending on current FT8 state.
- A terminal QSO result stays visible for about three seconds, then Rolling
  Thunder returns the FT8 lifecycle to its CQ browser. The cleanup also occurs
  if another context is selected; it does not move you back to FT8.
- Leaving the FT8 context aborts active FT8 work before restoration.

An accepted explicit CQ activation may show the shared station-information popup.
Encoder browsing, an accepted FT8 band change, or leaving FT8 dismisses it and it
stays hidden across refresh, even if a highlighted or active target remains. A later
accepted activation of the same or another station can show it again. Popup behavior
does not add a press, authorize transmission, or change the bounded QSO workflow.

While the CQ browser is idle, a valid decode addressed to the configured local
callsign opens a prominent incoming-call alert showing the caller, received SNR,
and grid when known. **Context Button #2** explicitly answers that exact caller
through the bounded responder workflow. A grid-bearing inbound starts with our
signal report; an inbound signal report starts with our acknowledged report.
Both continue to the normal final 73. **Context Button #3** ignores the caller.
The alert never interrupts an active or terminal QSO, and a decode never grants
transmit authority by itself.

Button #2 leaves the alert present if the responder workflow cannot start. After
a completed QSO, repeat addressed traffic from that same station is suppressed
for the next six FT8 periods so the final exchange is not mistaken for a new
call. Other callsigns appear immediately; the worked callsign can appear again
after the bounded cutoff. Failed and aborted attempts are not suppressed this
way.

## One authorization means one QSO

Rolling Thunder never automatically moves from a completed/failed station to a
new station and transmits again.

Each QSO requires a new explicit operator authorization for one selected target.

## Radio preparation

Before transmit, Rolling Thunder prepares and verifies the approved FT-891 FT8
state. The current operating design uses the documented FT8 dial frequency,
SSB-BFO USB, and a one-time initial power target calculated from the frozen local
and remote Maidenhead grids. Unknown distance and paths through 3,000 km start at
20 W; increasingly long paths use documented 5 W steps and paths beyond 14,500
km start at the hard 70 W maximum. Failure is fail-closed: no PTT and no
transmit audio. Rolling Thunder does not continually reset power after QSO start,
so a manual operator adjustment remains authoritative.

Leaving FT8 restores the documented normal radio values.

## QSO grid behavior

At the start of a QSO attempt, Rolling Thunder accepts GPS location for logging
only when the latest position is no more than 120 seconds old. A trusted position
freezes the full six-character Maidenhead grid plus coordinates and jurisdiction
for that QSO; those values remain fixed until that QSO succeeds, fails, is aborted,
or otherwise ends.

If GPS is missing or older than 120 seconds, FT8 may still use the configured home
grid for the on-air protocol exchange, but the completed contact does not claim that
grid as its mobile logging location. Forge routes that contact to `Mobile - Unknown
Location`. The next QSO evaluates GPS freshness again and obtains the then-current
location.

## Logging

A successful FT8 QSO enters the normal Rolling Thunder local contact path.
Failed/aborted attempts are not logged as ordinary QSOs, but may be retained as
performance/analysis telemetry.

Phase B retains every terminal FT8 attempt locally for later diagnostics, including
success, no answer, busy-target exhaustion, abort, interruption and equipment/
preparation faults. This adds no screen or control and does not change selection,
power policy, transmit authority, contact logging or Wavelog. Optional Forge
delivery and VOACAP processing are off by default; network/provider loss leaves the
local attempt queued and never turns missing data into a propagation failure.

Phase C4/C6 forecast sampling is a separately supervised Forge-only service. Its
production timer may run four times daily under an immutable, bounded plan; it has
no dashboard control, AI recommendation, band ranking, power advice, radio command,
or transmit authority. Any stored 20-W value is a model reference, not a measurement
or instruction, and VOACAP reliability is not QSO success probability. A successful
timer exit is not by itself proof of forecast coverage: cycle JSON and the
administrator-only query-only `--health` report distinguish provider-stored ready,
cache-reused ready, unavailable, pending, missing, stale, skipped, and failed/missed
slots. It also binds coverage to the exact plan and per-day slot identities rather
than treating matching totals as sufficient evidence.

Phase C5 adds offline Forge evaluation and a shadow-only explanatory data contract.
It still adds no dashboard control or displayed recommendation and cannot reorder a
CQ, set power, authorize a QSO, key PTT or transmit. The configuration term
`armed_when_ready` means scientific readiness only in this phase. Normal FT8 starts
remain at the current 20-W baseline under the existing operator-approved policy;
Forge loss or a failed readiness check cannot change radio operation.

After local persistence, successful FT8 contacts request the same background
Forge/Wavelog synchronization as ordinary contacts. A trusted mobile grid routes to
`Mobile - XXXX - YY`; an untrusted/missing mobile location routes to `Mobile - Unknown
Location`. For an explicit `CQ POTA`, Rolling Thunder also checks the current cached
POTA spots and records the park reference only when callsign/frequency/mode identify
exactly one park; ambiguous matches are left blank rather than guessed. A local
success or performance record does not prove remote upload: check the LOG row for
SYNC. WAIT can include optional QRZ
enrichment; Sync Now does not bypass that readiness gate. A failed optional QRZ
lookup releases the contact without a remote grid. If WAIT persists, collect
the contact/enrichment and sync evidence described in `FORGE_CONTACT_SYNC.md`.

For additional detail see `FT8_OPERATOR_GUIDE.md`.

---

# 9. Repeaters Screen

## Purpose

The repeater screen presents nearby configured six-meter repeaters based on the
current trusted GPS location and local repeater deployment data.

## What is shown

Each row can show:

- repeater/channel name;
- receive frequency;
- shift/offset;
- RX/TX tone information;
- distance from current GPS position;
- effective Active/Inactive state.

The default view shows Active repeaters only.

## Controls

- **Encoder** — move stable selection through the current repeater list.
- **Encoder press** — configure/tune the selected repeater through the typed
  repeater radio-configuration path.
- **Context Button #1** — toggle Active-only / All.
- **Context Button #2** — toggle the selected repeater's local Active preference.
- **Back** — cancel transient state or clear selection.

Changing the Active flag is a local operator preference. It does not itself
configure the radio.

## GPS requirements

Distance filtering requires a current usable GPS fix. Missing/stale GPS produces
an explicit unavailable/stale state rather than guessed distances.

---

# 10. DMR Screen

## Purpose

The DMR screen monitors the configured WPSD/MMDVM hotspot and supports local
logging of DMR contacts. It does not grant Rolling Thunder DMR transmit
authority.

## Monitored talkgroup

Rolling Thunder learns the monitored talkgroup from RF activity by the
configured operator callsign. It does not assume a fixed talkgroup such as
TG3100.

Until a monitored talkgroup is known, selection/logging is restricted and the
screen can show an unknown talkgroup state.

## Controls

- **Context Button #1** — stage the currently active caller on the monitored
  talkgroup.
- **Context Button #2** — commit the currently staged DMR QSO.
- **Encoder** — browse completed caller history for the monitored talkgroup.
- **Encoder press** — stage the selected history caller.
- **Back** — cancel staged QSO first, then clear history selection.

A talkgroup change invalidates a stage from the previous talkgroup.

## Failure behavior

Loss of live feed clears current-audio state rather than inventing a caller.
Usable prior history can remain while a source is marked degraded.

---

# 11. Weather Screen

## Purpose

The Weather screen presents retained current conditions, near-term forecast,
solar information, and location-relevant severe-weather alerts.

Provider work occurs on Forge; the Pi displays retained immutable state.

## Current conditions

The screen can show:

- Fahrenheit and Celsius temperature;
- relative humidity;
- normalized condition/icon;
- sunrise and sunset;
- next three future hourly temperatures;
- precipitation probability;
- provider attribution.

## Weather status

Common states:

- **LIVE** — current usable retained/provider state;
- **RETAINED** — prior valid data remains useful;
- **STALE** — useful but aged;
- **DISABLED** — feature intentionally off;
- **UNAVAILABLE** — no usable state;
- **ERROR** — latest attempt failed while prior data may still be displayed.

## Severe-weather alerts

Alerts are location-aware. Rolling Thunder should only claim an alert is
currently applicable when it has a trustworthy current location relationship.

The screen distinguishes verified-current alerts from retained/unverified alert
state.

Important warning/watch categories may also produce an audible notification
according to the configured policy. Repeated polling of the same unchanged
alert should not repeatedly replay audio.

When alert text exceeds the viewport, encoder movement scrolls the already-
published alert summary.

## Audible policy

The current policy distinguishes urgent warnings, watches, other warnings, and
advisories. The audio is a Rolling Thunder notification and is not an EAS
emulator.

---

# 12. Settings Screen

## Purpose

Settings exposes operator controls that can safely change selected runtime
preferences without editing configuration files.

## Current controls

- **Encoder** — move the highlight through MAP ZOOM, RADAR, CALLSIGN INFO,
  MAP STYLE, REBOOT, and SHUTDOWN; rotation never changes a value.
- **Context Button #1 / encoder press** — no Settings action.
- **Context Button #2** — selected-row OUT, OFF, NIGHT, or CANCEL.
- **Context Button #3** — selected-row IN, ON, DAY, or power SELECT/CONFIRM.

All six rows are visible at once at the supported display size and retain the
installed readable type sizes. A fixed footer shows the highlighted row's button
instruction. Text shows actual zoom/style, ON/OFF or
UNAVAILABLE, the selected marker, and the highlight. Power is UNAVAILABLE unless
a healthy trusted serial-v2 controller is current. The first Button #3 says
SELECT; only an active named confirmation says CONFIRM. Reboot or shutdown needs
two fresh deliberate Button #3 releases on the same row. Button #2, row/page
change, timeout, unhealthy controller, or session loss cancels.

Radio/FT8/PTT or local-commit activity blocks the request. After a power request
is accepted, all new commands—including tuning, selection, context, capture, QSO,
and commit actions—are blocked while Rolling Thunder waits for the service
manager's actual SIGTERM. The successful request itself does not preemptively
close the dashboard. A permission, guard, preference-drain, adapter, or timeout
failure leaves the dashboard usable and shows the action plus a bounded reason.
Linux shutdown does not disconnect external battery, fan, hub, or radio power; a
blank screen is not safe-unplug proof. Settings power actions also require the
host's narrow reboot/shutdown authorization; an unavailable authorization is
reported in the UI without closing the dashboard. Parked installed power-cycle
acceptance and Pi full-screen visual acceptance remain separate supervised work.

## Antenna reference / RF exposure screen

This optional screen is disabled by default. When enabled, it appears after SETTINGS
in next-context navigation and can be opened with `a` on a bench keyboard. Encoder
movement reviews already-loaded HF, VHF, and UHF antenna/installation cards. Encoder
press and Context Buttons do nothing on this screen; it cannot tune, key, transmit,
change power, or edit any displayed value. Back also has no Antennas-screen action.

The screen's sole authority is a manually maintained antenna-reference YAML file.
Update it only off-car, using retained manufacturer, installation, or measurement
sources, then restart Rolling Thunder through the normal approved procedure. There
is no in-app editor or reload. Keyboard, mouse, touchscreen, encoder, context button,
physical button, and voice input cannot alter antenna, installation, operating mode,
power, distance, reflection, RF duty, or either transmit fraction. Future voice
changes are not implemented and have no mutation authority.

The checked-in example starts empty. The screen never fabricates gain, treats missing
loss as zero, assumes HF includes 6 m, or uses current radio settings. A six-metre
antenna needs its own explicit VHF association. Cards retain gain/loss provenance and
the original dBi/dBd unit. Configured scenarios separately show mode RF-envelope duty,
forward power, controlled 6-minute and uncontrolled 30-minute TX fractions,
reflection assumption, and source.

The separate checked-in `config/antenna-reference.mobile-example.yaml` records a
specific set of operator claims dated 2026-10-13 and is not enabled or copied into
production automatically. It deliberately leaves all cable and duplexer loss values
unknown and every loss inventory incomplete, so it cannot produce a complete
exposure estimate. The ATAS-120A chain is ONLY 6.5 ft RG316. The 2 m Comet SSB224
chain is 6.5 ft RG316, CF-4160J duplexer, then 2 ft RG8X; it is distinct from the
generic dual-band antenna assigned to 70 cm, whose chain is 6 ft RG58, CF-4160J,
then 2 ft RG8X. No cable or duplexer loss or third-party certification is inferred.
The ATAS-120A record omits 30, 17, and 12 m pending confirmation, and the generic
antenna's nominal 70 cm gain remains pending datasheet mapping verification.

ONLY DRIVER antenna distance is verified in that mobile example: 90 in / 2.286 m
for the ATAS-120A, 64 in / 1.6256 m for the 2 m Comet SSB224, and 84 in / 2.1336 m
for the generic dual-band antenna operating on 70 cm. All 12 scenarios identify
that value as `front_seat_measured`. Passenger and public distances remain unknown,
so risk or safety cannot be concluded for passengers, other occupants, the public,
or aggregate/multiantenna exposure.

Distance is explicit: `hypothetical_six_foot` is exactly 6 ft / 1.8288 m and is
always unverified; `front_seat_measured` and `public_measured` require real measured
geometry. Missing, unreadable, malformed, or invalid YAML produces a visible error,
not an empty or safe-looking estimate.

The underlying calculations retain peak ERP/EIRP, both FCC limits, calculated
plane-wave distances, and missing-input details. The driving view intentionally
shows only the selected card's public-scenario summary rather than those long
diagnostics. Neither the view nor the underlying result declares an installation
safe, unsafe, compliant, or noncompliant. Near-field coupling, vehicle
body/metal/glass, real antenna pattern, occupants, and aggregate simultaneous-source
exposure remain outside the estimate. Do not rely operationally on the screen until
real sourced data has been reviewed, results have been compared with the current
ARRL reference, and vehicle-specific geometry and near-field questions have been
addressed.

A manual DAY/NIGHT selection can temporarily override automatic solar style
selection until the next real solar transition. The callsign-information
mini-map follows the same accepted DAY/NIGHT selection; map zoom remains a
primary-live-map-only setting.

---

# 13. LOG Screen

## Purpose

The LOG screen is a glanceable view of recent locally stored contacts and remote
synchronization state.

## What is shown

The panel shows recent contacts with:

- time;
- callsign;
- amateur band;
- conservative country abbreviation where available;
- synchronization state.

Synchronization markers include:

- **SYNC** — remotely synchronized;
- **WAIT** — pending;
- **FAIL** — last synchronization attempt failed.

The summary also shows unsynchronized and total local-contact counts.

## Control

- **Context Button #1** — request an operator-forced synchronization pass.

The local contact database remains authoritative even when synchronization
fails.

## Retention

Rolling Thunder can prune old contacts only after they are proven synchronized,
under the configured retention policy. Unsynchronized contacts are not discarded
merely to meet a size target.

---

# 14. AI Screen

The AI context currently exists in dashboard navigation but remains a reserved/
placeholder screen.

Operators should not assume that an AI-advisor recommendation engine is active
merely because the context is selectable.

Future implementation should be documented here before it is presented as an
operational feature.

---

# 15. Live Map and Situational Display

## Purpose

The live map provides continuous location and environmental awareness alongside
the active operating context.

## Map sources

The primary map is local-first:

1. installed regional map package when available;
2. runtime cache;
3. approved online provider;
4. explicit unavailable/partial presentation.

The installed system contains regional DAY/NIGHT packages so the map can remain
useful without cellular service inside covered areas.

## Map information

The map can display:

- current/last-known vehicle location;
- local time;
- UTC;
- Maidenhead grid;
- retained local weather temperature;
- MAP/GPS/RADAR health.

GPS health and map-data health are separate. A cached map can be usable while
GPS is degraded, and a good GPS fix can exist while online map data is
unavailable.

## Vehicle marker

The vehicle marker uses course-over-ground while moving. At low speed it retains
the last reliable heading rather than visibly jittering.

## POTA park markers

The map can display approximate POTA catalog locations.

At higher zoom, markers include park reference/name; at lower zoom they become
compact dots. These coordinates are situational pins only and are not legal
activation-boundary evidence.

## Radar

Radar is an optional overlay with an independent lifecycle from the base map.
Radar failure must not blank or block the base map.

---

# 16. Callsign Information Overlay

## Purpose

The callsign-information overlay answers four questions while leaving the
current operating screen intact:

1. Who is the station?
2. Where are they?
3. What is the weather there?
4. Have I worked them before?

## Information sources

The Pi requests a compact contact-intelligence response from the independent
Forge callsign-info service.

Depending on available data, the overlay may include:

- callsign/name/address identity;
- a contact mini-map;
- current target weather;
- target local time in black text on a compact white background at the top-right of the mini-map when a reliable IANA timezone accompanies that weather;
- WORKED N TIMES plus the last QSO date/location and band; notes/comments are omitted;
- FIRST CONTACT when no prior QSO is found.

The contact mini-map follows the primary live map's DAY/NIGHT theme. A configured
worldwide style-aware source supplies its own NIGHT tiles. When no dedicated
callsign source is configured, the normal worldwide online source supplies DAY
tiles and Rolling Thunder locally converts validated NIGHT requests into a
genuinely dark raster. DAY tiles stay unchanged, and separate cache partitions
prevent DAY pixels from being presented or stored as NIGHT.

When configured for Forge tiles, that source is an optional disabled-by-default
route on the existing private Forge spot/weather/radar service. A renderer or
map-route failure affects only the mini-map; spots, health, weather, location,
radar, local logging, and radio operation continue independently.
The route must have worldwide backing data for callsign use; the regional I-71
renderer is not worldwide coverage.

## Location priority

For a selected current POTA activation, park coordinates are preferred for the
contact's current map/weather location. Otherwise reliable QRZ coordinates can
be used. Approximate/fallback coordinates are treated conservatively and are
not presented as an exact station pin.

## Lifecycle

The overlay follows an explicitly selected shared pending callsign or the currently
relevant FT8 station while its presentation lifecycle is armed. On FT8 it appears
promptly after accepted selection for a CQ, live preparation, or active
QSO using the locally decoded grid when valid; the map marks that point as an
approximate FT8 grid center. Missing or malformed grids never create a pin. Forge
identity, history, and weather fill in asynchronously when available.

Callsign replacement, Commit, Discard, FT8 abort/completion/terminal state,
selection dismissal/expiry, timeout, or disabling the feature invalidates the
current overlay. A late result for an earlier station is not shown.

In POTA, DX, and FT8, moving through station rows, changing band, or leaving the
context dismisses the popup and prevents timer refresh from requesting lookup or
mini-map work. Highlight movement alone does not reopen it. A later accepted
explicit selection—including the same station—can start one fresh popup lifecycle.
Rejected tune/QSO commands do not select, tune, transmit, or rearm the popup.

`LOCAL` means the contacted target's time, including daylight-saving rules. If Forge
cannot establish that timezone reliably, the field is left blank rather than showing
the vehicle/operator timezone.

If enrichment fails, the overlay retains local context and shows one large status:
`NETWORK UNAVAILABLE` only when Rolling Thunder already knows the network is down;
`FORGE SERVICE NOT RESPONDING` when the network is known available but Forge fails;
otherwise `LOCATION SERVICE UNAVAILABLE`. Rolling Thunder performs no extra network
probe for this label and does not display raw error details. Contact logging, FT8
decoding/timing, radio operation, and Commit continue independently.

---

# 17. Alerts, Messages, and Degraded States

## Global status messages

Rolling Thunder has a shared status-message service so multiple features do not
blindly overwrite each other. Messages can have priorities, replacement keys,
and expiration times.

Examples include tuning progress, tuning success/failure, cross-band operator
handoff, and other short-lived operational notices.

## Cross-band antenna/radio reminder

When a receive target requires an operator band/antenna step that CAT cannot
authoritatively establish, Rolling Thunder may show a message similar to:

```text
SET BAND TO <BAND> METERS — TUNE ATAS-120
```

This is an operator handoff, not a claim that the antenna has been tuned.

## Offline/retained labels

A retained state means Rolling Thunder is deliberately showing the last valid
known data rather than erasing useful context.

Always distinguish:
- **current/live**
- **retained/stale**
- **unavailable**

when making an operating decision based on time-sensitive information.

---

# 18. Forge Backend

## Why Forge exists

Some jobs are better performed by a stable backend than by a mobile Raspberry Pi
that may lose cellular coverage, reboot, or move between networks.

Forge centralizes:

- long-lived provider connections;
- external API credentials;
- provider etiquette/rate limiting;
- retained snapshots;
- heavier normalization/caching;
- integration with home services such as Wavelog.

## Spot/weather/radar/map service

The primary Forge service publishes retained spot, health, weather, alert,
location, and radar capabilities. It can also expose optional on-demand
style-aware map tiles through the same private listener; no second production
map daemon or port is required.

### POTA

Forge retrieves/normalizes POTA provider data and publishes provider-neutral
records for clients.

### DX Summit

Forge maintains the persistent DX Summit IRC session. The Pi simply consumes
the retained Forge API.

### DXSpider fallback

A persistent DXSpider implementation exists as a disabled fallback. It is not
the normal production DX source.

### Weather and alerts

Forge uses retained mobile location to obtain provider weather and location-
appropriate NWS alert state, then publishes normalized data.

### Radar

Radar provider/network work runs on Forge. The Pi consumes prepared/retained
radar data and integrates it into the map without coupling base-map availability
to radar availability.

## Callsign information service

A separate Forge process combines configured QRZ identity, Wavelog previous-QSO
history, and target weather into a compact contact-intelligence API.

Keeping this separate also keeps provider credentials off the Pi.

## Contact synchronization service

A separate Forge process accepts normalized contact synchronization requests and
performs controlled Wavelog integration with idempotency safeguards.

For a contact with complete frozen mobile grid/state/zone context, Forge routes the
QSO to a verified Wavelog Station Location named `Mobile - XXXX - YY` (for example,
`Mobile - EM79 - OH`) inside the configured station logbook. A contact without a
trusted frozen mobile location is routed to `Mobile - Unknown Location`, which has
no fabricated grid/state/CQ/ITU metadata. This routing uses the location captured
with the contact; a later vehicle position cannot redirect a retry. Grid-based
dynamic Station Locations keep a four-character grid, while the QSO keeps its full
captured grid when available.

The full local QSO grid is the sole Rolling Thunder grid identity; the four-character
station profile grid is derived from it. Rolling Thunder submits the full grid in ADIF,
but Wavelog 3.2.3 overwrites its stored QSO value from the grid4 station profile. This
requires a separate Wavelog provider/API change; no station profile is moved among
six-character subsquares as a workaround. Contact sync uses weather already present
on the QSO without adding weather text to new notes.

Blank notes are omitted from Wavelog ADIF. Explicit existing notes remain exact;
old claimed uploads retain their original payload on retry. New POTA and Browse
contacts do not generate notes from their park or location. Station
creation/linking or Wavelog failures do not undo the local contact; the LOG retry
path remains available.

## Propagation environmental collector

Forge has a separately supervised, disabled-by-default Phase 1 collector for hourly
HamQSL solar and KC2G ionospheric snapshots. It has no dashboard control, radio or
transmit authority, contact-log callback, Wavelog path, or effect on contact retry.
Its failure therefore does not change radio operation, FT8, local logging, or contact
synchronization. Forge administrators inspect and activate it separately; vehicle
operators do not need to enable or acknowledge it.

Its code-deployment path also remains separate: a reviewed, pushed exact 40-character
commit selects an immutable propagation-only release and cannot select another
service. The dispatcher adaptation is staged for an authorized Forge administrator;
it validates the origin commit and exits into the isolated hook before any legacy
shared-service deployment work. Fresh wheels must be built from that committed Git
tree, checksum-manifested, reviewed, and separately promoted to root-owned staging.
The older uncommitted wheelhouse is never deployment input. Code deployment does not
activate the collector or authorize provider access.

The deploy hook builds the propagation virtualenv at its final immutable SHA path
and validates the real installed launcher before selecting it. An existing release
with a broken launcher is not selected or repaired in place; Forge administrators use
the separate broken-release recovery runbook and a fresh reviewed SHA. This recovery
does not alter the original contact-sync, callsign-info, or spots services and does
not authorize provider access.

The release candidate contains two separately supervised, disabled QSO-analysis services. The completed-QSO VOACAP worker includes authenticated private ingestion and a durable inbox; the PSK Reporter FT8 worker includes authenticated private event ingestion, a scheduler and isolated databases. Both have hardened off-by-default units, dedicated identities, and reversible exact-SHA release selection. The Pi now has an independently gated durable delivery/retry outbox, but it has no dashboard control, contact-sync hook, Wavelog path, or effect on radio operation. Source delivery, receiver ingestion, and provider egress all remain disabled pending separately approved credentials, private ingestion acceptance, and bounded provider testing. Failure or absence never blocks local logging.

## Forge is reusable

Forge is intentionally not a private helper for one Rolling Thunder screen.

Its useful capabilities should remain callable by other authorized applications.
A future web interface, another vehicle, analytics program, or different radio
client should be able to use the same backend contracts without reproducing
Tkinter concepts.

---

# 19. What Happens When Something Fails

Rolling Thunder is designed to fail in pieces rather than as one monolithic
system.

Examples:

- **Forge unavailable:** local logging, radio, GPS, and installed maps can
  continue; network-enriched screens become retained/degraded/unavailable.
- **GPS unavailable:** map position, current grid, repeater distance, and
  location-sensitive alerts degrade; unrelated radio/log functions continue.
- **Map provider unavailable:** installed/cache map data may remain usable.
- **Weather provider unavailable:** retained weather may remain visible and is
  marked truthfully.
- **DX provider connection lost:** Forge retains bounded prior state while
  reporting provider degradation and reconnecting with backoff.
- **Wavelog unavailable:** locally committed contacts remain stored and can be
  retried.
- **Callsign intelligence unavailable:** the contact can still be logged; the
  enrichment overlay simply does not become a prerequisite.
- **FT8 preparation/transmit failure:** the FT8 attempt fails closed; unrelated
  dashboard functions continue.
- **FT8 receive degraded:** the FT8 footer identifies clock, audio, dropped-slot,
  decoder, or diagnostic-storage trouble. NTP is the primary readiness source;
  trusted GPS verifies UTC when NTP is unavailable. Receive diagnostics never
  authorize transmission.

---

# 20. Operating Safety Notes

Rolling Thunder reduces workload but does not replace operator judgment.

- Keep attention on driving and traffic conditions.
- Treat band/mode advisories as assistance, not legal authority.
- Treat POTA map pins as approximate situational information, not activation
  boundary proof.
- Treat retained/stale network information according to its age.
- Do not assume a radio/antenna action occurred unless Rolling Thunder reports a
  completed supported action or explicitly hands control back to the operator.
- FT8 transmission requires explicit authorization for the selected QSO; do not
  assume passive decoding can key the radio.

---

# 21. Quick Screen Reference

| Screen | Primary use | Key controls |
| --- | --- | --- |
| POTA | Find/tune park activators | Encoder select; press tune; Button 1 band; Button 2 mode |
| DX | Find/tune DX spots | Encoder select; press tune; Button 1 band; Button 2 mode |
| Browse | Free-form receive/contact workflow | Encoder frequency; Button 2 step; Button 3 mode |
| FT8 | Native CQ browser and bounded QSO | Encoder select; press start; Button 1 band; incoming Button 2 answer / Button 3 ignore; active Button 3 abort/ack |
| Repeaters | Nearby 6 m repeater selection | Encoder select; press configure; Button 1 filter; Button 2 active toggle |
| Weather | Conditions/forecast/alerts | Encoder scrolls long alert text |
| Settings | Runtime preferences/power request | Encoder selects; B2 lower/off/cancel; B3 higher/on/confirm; B1/press inert |
| Log | Recent contacts/sync status | Button 1 forced sync |
| DMR | Monitor/log hotspot contacts | Button 1 current caller; Button 2 commit; encoder history |
| Antennas / RF exposure | Read configured reference/advisories | Encoder view navigation only; all data edited manually off-car in YAML |
| AI | Reserved | No production advisor behavior yet |

---

# 22. Further Reference

Detailed subsystem documents remain available for technical or advanced operator
reference:

- `docs/FT8_OPERATOR_GUIDE.md`
- `docs/CALLSIGN_INFO.md`
- `docs/SHARED_SPOT_DOMAIN.md`
- `docs/REPEATERS.md`
- `docs/DMR_HOTSPOT.md`
- `docs/LIVE_MAP.md`
- `docs/WEATHER_PANEL.md`
- `docs/WEATHER_ALERTS.md`
- `docs/PI_AUTOSTART.md`

For development/agent work, begin with:

- `AGENTS.md`
- `docs/engineering/index.md`
- `docs/engineering/ownership-and-dependencies.md`
- `docs/engineering/shared-component-contracts.md`


## FT8 and voice microphone selection

FT8 entry automatically sets and verifies menu **11-05 SSB MIC SELECT = REAR**
(`MIC = 0`, `REAR = 1`). FT8 uses the rear DATA/RTTY audio path.
Returning from FT8 to Browse, POTA, or DX sets **11-05 = MIC** so ordinary SSB
voice uses the front microphone. The destination context is authoritative;
the prior menu value is not restored.

The existing typed FT-891 adapter owns CAT encoding and readback. FT8 receive
entry/band changes and pre-QSO preparation require REAR. A failed write,
malformed reply, or mismatched readback prevents QSO authorization; no PTT or
transmit audio is permitted through the preparation path. Existing USB,
11-07 SSB BFO, IPO/preamp, NAR, NB, power, and bounded transmit policy remain.

Shared exit/rollback cleanup attempts MIC even if another restoration fails.
Failed-QSO recovery that remains on the FT8 screen reapplies REAR; a requested
context exit skips that recovery. CAT-safe shutdown performs serialized normal
receive cleanup before disconnect. With CAT unavailable, restoration cannot be
confirmed: check 11-05 manually before voice operation. Hardware acceptance of
this change is still required.


## Known/friend callsign stars

A small gold ★ beside a remote callsign means it is an active entry in your
Forge friend directory. Stars appear on POTA/DX cards, FT8 CQ rows, the pending
callsign/Browse area, contact information, DMR audio/history, and LOG contacts.
A star does not mean worked, selected, eligible for FT8, or authorized to transmit.

On the trusted private network, open
`http://192.168.9.170:8788/admin/known-callsigns`. Add or edit a callsign and an
optional name/comment. Uncheck Active to hide its star, check Active to restore
it, or use Delete and confirm permanent removal. Comments are private Forge
administration data and do not travel to the vehicle's friend-status cache.
Matches use exact uppercase callsigns, including any operating suffix.

Changes normally appear on the next 30-second poll. When Forge is unavailable
or the classification becomes stale, callsigns render without stars and normal
operating/logging controls continue. See `KNOWN_CALLSIGNS.md` for setup and
owner deployment/acceptance instructions.


### Mobile antenna public-distance operating reference
The separate mobile antenna YAML records the driver-only normal occupancy policy (front passenger seat taken by display, rear seat by POTA equipment), with the **three measured driver distances unchanged**. Its **six-foot public separation** is a *hypothetical, operator-enforced minimum from the antenna*, not a guarantee based on road lanes or an FCC compliance certification. When parked and transmitting, visually monitor public access; if a person enters the established exclusion distance, cease transmitting until separation is restored. Do not operate on the assumption that any fixed separation is lawful until controlled/uncontrolled RF exposure evaluation is completed. The current antenna screen is informational and read-only; unknown coax and duplexer losses mean all reference evaluations are incomplete.


The optional antenna page can show a **ZERO-LOSS SCREENING ONLY** distance
and percent of uncontrolled MPE for configured scenarios when feedline losses
are unknown. It uses a zero-dB-loss numerical assumption and keeps the actual
evaluation labeled INCOMPLETE. This is an advisory *far-field estimate*, not a
confirmed safe distance or an FCC compliance determination. No radio controls
or power changes result from this screen.


A scenario with a valid conservative zero-loss screening result displays
**BASED ON ARRL RF EXPOSURE CALCULATOR** instead of a duplicate
"ADVISORY INCOMPLETE" block. The separate authoritative evaluation remains
incomplete in the application model until actual feedline/duplexer losses are
specified. The screen retains a 0 dB-loss assumption and does not assert FCC
compliance. Scenarios without a valid estimate continue to show missing inputs.

The ANTENNAS main view uses the full existing left pane for a high-contrast native
table on the selected card. BAND, MODE, and POWER use large separate cells; PUBLIC
MIN is the widest, highlighted column and shows modeled separation in feet to one
decimal place. At the physical 1280×720 in-car size, the table retains approximately
20-point rows and 21-point yellow public-minimum values. A compact one-line “ARRL RF
EXPOSURE CALCULATOR” attribution and reduced vertical margins leave all nine ATAS
rows—including 6 m SSB—fully visible above the two-line footer without scrolling.
The sizing accounts for the dashboard status strip, context title, selector/read-only
lines, borders, padding, and Tk font scaling rather than treating the whole context as
table space. It does not display driver separation or long diagnostic blocks on the
main view; the manually maintained YAML preserves detailed input provenance. The
six-foot public boundary, 0 dB cable-loss assumption, and non-certification caveat
remain visible. Encoder changes the selected card; no radio power control.

## VOACAP missing predictions

A missing or invalid required prediction value leaves that hour/band transaction blank; it is not displayed or stored as zero. Other complete predictions continue. A successful HTTP response alone does not establish a usable forecast.


## USB controller recovery (explicit v2 commissioning)

The existing serial controller setup remains supported. The new serial_v2 option
requires matching recovery firmware and a controlled parked cutover; selecting it
with legacy firmware leaves controls unavailable instead of guessing a protocol.
It reconnects in a background worker and discards old inputs. A held button must
be released and pressed again after reconnection. The bottom routine ticker shows
Controls: READY, CONNECTING, RECONNECTING, UNAVAILABLE or OFFLINE. Higher-priority
alerts still take precedence. Touchscreen operation remains available during a
controller outage. Voice capture still requires a fresh physical Voice-button press.

Do not switch protocols, flash firmware or test reconnects while driving. Keep the
known-good firmware/configuration backup until parked acceptance and soak pass.
See engineering/controller-recovery-v2.md for commissioning and rollback details.


Settings power requests permit an explicitly disconnected radio whose published
TX flag is false, provided every independent local FT8/hardware/PTT/commit guard
is idle. This supports shutting down with the radio already switched off. A retained
TX flag is never cleared by disconnection; connecting/error states remain unknown
and block the action. No live CAT query or radio command is issued by this guard.

### QSO popup and vehicle status readability (2026-11-04)

The QSO map popup shows the remote station local-time label at twice its previous font size (48-point bold); the white background is sized from the rendered text bounds. The bottom vehicle status-bar ticker text is also doubled (36-point bold). The status icons and QSO workflow are unchanged. Longer messages may not fit the available ticker width; the UI does not automatically scroll or abbreviate them.

---

## Optional MeshCore observation collector (disabled by default)

An optional, background-only MeshCore collector can be enabled by a deliberate
operator configuration change **after parked USB and GPS/controller acceptance**.
There is currently no MeshCore dashboard screen or map overlay. It monitors
incoming companion-protocol node identity announcements (including new contacts
and path-update notifications), preserves first/last seen history, and stores
each received observation with UTC time and the existing Rolling Thunder GPS
snapshot where valid. No extra GPS receiver or network pipeline is started.

`meshcore_passive.enabled` defaults to `false`. When off, the MeshCore port
is never opened and its database is not created. When explicitly enabled, the
`device` setting must be a verified physical `/dev/serial/by-path/...` USB
selector, never `/dev/ttyUSB#` or `/dev/serial/by-id`, because the installed
MeshCore CP2102 shares its generic serial identifier with another device.
Data goes into `meshcore-observations.db` beside the configured contact database,
without changing contact-log schema, QSO logging or Wavelog synchronization.

The software never sends discovery requests, advertisements, messages, radio
configuration or trace commands. Ordinary firmware-managed MeshCore ACK and mesh
routing transmissions may still occur, as permitted by the owner; no absolute
RF silence is implied. RSSI/SNR and complete observed paths are stored only
when actually available and validated; the initially supported identity
notifications provide neither. A stale, absent or low-quality GPS fix causes
an explicit null receiver location rather than an invented coordinate.

**Do not enable the collector during a drive or while the USB bus is unstable.**
The 2026-11-11 hardware investigation observed repeated USB hub protocol errors
and missing MeshCore/GPS serial interfaces. A successful software regression
suite is not a substitute for a parked physical USB, RF, and GPS/controller
acceptance check. Rollback: set `meshcore_passive.enabled: false` and restart
the application through the approved deployment process; retain the separate
database for later analysis.


### Heltec V4.3 USB receiver identification (2026-11-11)

The replacement board is a Heltec WiFi LoRa 32 V4.3 with native ESP32 USB CDC
(interface `ttyACM0`, USB vendor/product `303a:0002`) and an individual USB
serial number. The earlier V3 used an ambiguous CP2102 bridge; the V4 uses a
separate, distinguishable interface. The replacement's local-only MeshCore
`CMD_DEVICE_QUERY` returned firmware **v1.16.0-07a3ca9**, protocol **13**,
build **06-Jun-2026**, reported as **Heltec V4.3 OLED** and repeater mode off.
The firmware's board label does not imply a physically installed display.

V4 native CDC requires DTR asserted to provide USB replies; V3 CP2102 handling
keeps it deasserted. A firmware query is an intentional parked diagnostic, not
part of unattended collector behavior. The application retains its default-off
gate; this identification alone does not prove the radio is receiving nearby
nodes or that a full drive-tested collector has passed acceptance.


### Contact-sync repeated remote failures (2026-11-11)

A remote Home Platform/Wavelog HTTP 503 does not invalidate the locally saved QSO. The retry schedule doubles initially but is capped by the configured maximum, even for contacts with a very large previous failure count. The persistent retry mechanism continues to schedule future eligible attempts instead of crashing on numeric overflow. This correction does not imply the remote HTTP 503 itself is resolved. Contact-sync error status and normal manual retry remain governed by the existing logging interface.


### Separate MeshCore receiver service (planned transition, not deployed yet)

The standalone `meshcore-collector.service` operates independently of the Rolling Thunder interface and captures passive node observations while the dashboard is off. It owns the Heltec V4 USB connection exclusively. GPS positions, when available, are copied from the normal Rolling Thunder GPS service through a nonblocking local snapshot publisher; while Rolling Thunder is down, observations continue with no valid receiver GPS. History is in `~/.local/share/meshcore-collector/meshcore-observations.db`, outside the RT checkout. The private read-only local API is `$XDG_RUNTIME_DIR/meshcore-collector.sock` for authorized Rolling Thunder and SCOUT users. No network port, host-initiated RF messaging, or raw-payload persistence is added. If firmware emits 0x88 raw-RX events, only unattributed RSSI/SNR measurements are kept; no message text or presumed node association.

Cutover requires parked stop of old USB owner, lossless database copy, approved source deployment, independent service enablement, and hardware/GPS/SQLite/USB acceptance. Roll back by stopping the service and restoring the approved prior configuration and source through the deployment wrapper; never delete saved SQLite history. The installation remains pending until the owner performs or confirms those commands and verification succeeds.
