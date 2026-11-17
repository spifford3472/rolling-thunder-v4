Warning: truncated output (original token count: 17976)
Total output lines: 1555

# Rolling Thunder Operator's Guide

## Current source versus installed state — November 17, 2026

Current merged `main` is `3328c27d5eb41e4417fe6305d1942002a3488106`. PR #481's
GPS shutdown quiescence fix and PR #479's MeshCore source removal are merged;
PR #486 only redacted production evidence and documented remaining release
gaps. On November 17, the owner-authorized MeshCore collector and traffic-worker
user services were stopped, disabled, and removed from the user systemd search
path after verified backups; their data/configuration and unit definitions were
preserved. Rolling Thunder remained active and OHGO was not changed. This does
not establish the running Pi's exact code identity or complete parked USB/GPS/FT8
acceptance. The full AnvilMobile release remains **NO GO**;
see `engineering/parked-receive-only-acceptance.md` and the REL-01 packet.

The dated November 15 source note below remains historical. It describes the
STAB-07 preference-drain and startup-rollback corrections; it is not the latest
source baseline or evidence of installed readiness.

### Dated STAB-07 note — November 15, 2026

The STAB-07 preference-drain and startup-rollback corrections are **merged in
source** at `b792151313e60596e6ff3ad51f6ed4e260078718` (PR #472), not an open
candidate. The runtime now owns the one preference drain after radio cleanup;
when a prior shutdown stopped the preference executor, a retry does not flush
that stopped executor a second time. Isolated ARM64 fake-hardware tests passed;
**this does not mean the code has been installed or physically accepted on the
Pi**. Observe the actual installed SHA and radio receive state before claiming
live readiness. A successful software release result never proves RF receive.

## Shutdown safety status (STAB-04 merged source; physical acceptance pending)

The merged source prioritizes the existing FT8 transmit release and
radio adapter shutdown ahead of unrelated background worker cleanup. Shutdown
messages do not independently prove the FT-891 has returned to receive. If its
TX indicator remains on, stop operating and follow the established supervised
radio recovery procedure; do not assume software shutdown or a restart
de-keyed the radio. This merged code still requires a parked acceptance test
and does not authorize any unattended RF operation.

## CAT/PTT release safety (STAB-05B merged source; physical acceptance pending)

The merged FT-891 CAT safety correction rejects any new FT8 PTT key
request after an unsuccessful transmit-off attempt until the existing radio
adapter successfully retries the release command. This is an additional
**software inhibit**, not proof that the rig is physically in receive.
A successful CAT TX0 write alone is not physical confirmation.

If the FT-891 indicates transmit unexpectedly, stop automated operation;
independently confirm receive or safely turn off the radio, and inspect the
failure before allowing any new transmissions. Do not override the safety
inhibit merely because a software retry or service restart completed.
Supervised parked/radio testing must be approved separately.

## FT8 stuck-transmit lockout: software acknowledgment is not RF proof

If the FT-891's red TX indicator remains on unexpectedly, stop automated FT8
operation. Safely return the radio to receive or power it off before further
transmission attempts. A software timeout, reconnect, warning dismissal,
`TX0;` command, or service restart cannot by itself establish physical receive.

The FT8 warning and transmit inhibit are separate. Voice Cancel acknowledges
the warning but does not itself remove the inhibit. After you have safely
checked the radio, you can explicitly override the current-session software
inhibit using physical command buttons **1–3–1** on the FT8 screen after
acknowledging the warning with Voice Cancel. This operator recovery is
implemented in the current source. It is **your recovery
decision**, not a declaration that the software has verified physical receive.
A successful CAT `TX0;` response or `RadioState.transmitting=False` also
cannot establish physical receive. The override clears the alarm inhibit but
**does not key the transmitter, start an FT8 QSO, or override other
radio-adapter safety checks**.

If a real alarm fires, stop operating and safely inspect the FT-891's red TX
indicator. Manually de-key or power down the radio if its state is uncertain;
do not override while it might still be transmitting. The operator may
explicitly recover using the gesture after resolving the issue. The alarm is
**session-local**: a dashboard process restart creates a new clear instance,
per owner policy. Restart is not proof of de-key, so observe radio state and
exercise care before separately starting an FT8 transmit operation. New
uncertain-PTT events still trigger a fresh alarm. No unattended RF test
is authorized.

## FT8-RX-02 read-only receive-status diagnostics

Yaesu provides read-only FT-891 CAT queries for the radio/CAT transmit
status and TX/RX indicator states. The strict source-only parser is present,
but the dashboard does **not** issue those queries or use them to unlock FT8.
The reported indicators come from the radio's firmware and cannot
independently prove the absence of RF transmission. A real PTT alarm
continues to require safe operator intervention and supervised recovery.
The session-local alarm clears on a dashboard restart. The current source
also permits an explicit Voice Cancel then 1–3–1 operator override on FT8.
Neither recovery path proves the radio is in receive; inspect the rig and
avoid transmitting while physical TX is uncertain. See
`engineering/ft8-rx02-receive-evidence-and-supervised-recovery.md`.

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

When GPS data is missing or the receiver disconnects, the dashboard reports GPS
error/unavailable state and background polling attempts to reconnect. GPS loss
does not stop ordinary local logging; records may lack a current grid. During
shutdown, an in-flight GPS read must finish before the receiver is closed. If it
does not become idle within the two-second shutdown bound, the application logs
the failure and leaves the descriptor to process exit; this does not establish
that the receiver or USB path is healthy after restart.

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

## Unfinished deployment recovery (future gated capability)

STAB-06F is an **offline engineering candidate**, not currently installed. If a future authorized deployment reports an incomplete transaction, do not clear its journal, reinstall an old database or repeatedly restart the service. Park safely and preserve the transaction ID, exact running SHA, protected backups and database. The read-only inspector is diagnostic only; owner-approved reconciliation is a separate privileged process and does not itself restart the UI, restore data or prove physical PTT release. A mutable-checkout process or a stale/mismatched Tk heartbeat remains unverified, even if systemd reports active. The process-bound identity check proves the protected release path and live Tk callback identity; it does not establish physical radio state. Consult `docs/engineering/stab06f-recovery-inspection-reconciliation.md` after the capability has been separately reviewed and installed.

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
and CALL …5976 tokens truncated…Callsign replacement, Commit, Discard, FT8 abort/completion/terminal state,
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
no grid, city, or state. Wavelog requires CQ and ITU zones on every station location,
so this fallback profile uses CQ Zone 4 and ITU Zone 8. These are profile-level
defaults; the contact's missing location fields remain missing. This routing uses
the location captured with the contact; a later vehicle position cannot redirect a
retry. Grid-based dynamic Station Locations keep a four-character grid, while the
QSO keeps its full captured grid when available.

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

## Historical MeshCore receiver records

MeshCore collection, messaging, traffic analysis, and related Rolling Thunder
configuration have been removed from the active application source. Earlier
hardware, protocol, and SQLite descriptions below are retained as historical
records; they are not current setup or operating instructions. MeshCore history
and databases are not deleted by source changes. The existing installed
collector must be handled only through a separately approved production
cutover; do not use this guide to stop or remove it.

### Historical Heltec V4.3 USB receiver identification (2026-11-11)

The replacement board was recorded as a Heltec WiFi LoRa 32 V4.3 with native
ESP32 USB CDC (interface `ttyACM0`, USB vendor/product `303a:0002`) and an
individual USB serial number. Its local-only diagnostic reported MeshCore
firmware v1.16.0-07a3ca9, protocol 13, build 06-Jun-2026. These observations
are historical hardware records; the dashboard no longer uses this interface.

### Contact-sync repeated remote failures (2026-11-11)

A remote Home Platform/Wavelog HTTP 503 does not invalidate the locally saved QSO. The retry schedule doubles initially but is capped by the configured maximum, even for contacts with a very large previous failure count. The persistent retry mechanism continues to schedule future eligible attempts instead of crashing on numeric overflow. This correction does not imply the remote HTTP 503 itself is resolved. Contact-sync error status and normal manual retry remain governed by the existing logging interface.

The 2026-11-15 read-only AnvilMobile snapshot found 15 contacts still marked
failed with HTTP 503 and retry counters from 766 to 2,170. They remain stored
locally and scheduled for retry; no manual retry, contact deletion, or backup
was performed. See engineering/rel01-installed-state-snapshot-2026-11-15.md
for the exact database, retry, and backup evidence.


### Historical independent MeshCore service design

Prior plans described a separate service, Unix socket, GPS snapshot file, and
external SQLite database. The 2026-11-15 follow-up read-only inspection found
the enabled user unit `meshcore-collector.service` running outside the system
Rolling Thunder unit. Its configured serial path is absent; it is retrying and
has no open serial descriptor. The broker is enabled. The separate enabled
`meshcore-traffic-worker.service` is inactive. Observation, broker, and traffic
databases remain present and passed read-only integrity checks; the broker
contains queued records. Do not stop, disable, remove, migrate, or delete any
unit/data without separate owner approval and an accepted cutover plan. See
engineering/rel01-installed-state-snapshot-2026-11-15.md for the observed
paths, counts, and acceptance boundary.

### Current service read-only recheck — November 17, 2026

Through the Unix account that owns the user systemd manager, the collector was
still enabled and active; the traffic worker was enabled but inactive. The
historically identified MeshCore receiver USB identity was absent from current
USB enumeration. No service or data was changed. A different remote-tool
account cannot see this user manager, so a missing unit from that account is not
proof of cutover. The separately gated procedure is
`engineering/meshcore-installed-service-cutover-plan.md`; no stop, disable,
uninstall, database operation, or deletion is authorized by this observation.

## OHGO (read-only)

Select the **OHGO** context with the `o` shortcut or normal context navigation.
The screen displays incident reports received from Forge, separated by
horizontal divider lines. Its text uses the existing 42-point bold font and
wraps to the available space. A white **MORE** indicator appears when additional
text remains below the visible area. Turn the rotary encoder clockwise to scroll
down or counterclockwise to scroll up; scrolling works only on this screen and
does not change selection elsewhere. Routine refreshes preserve the scroll
position while the incident data is unchanged.

The screen reports **not configured**, **unavailable**, **stale**, **no reports**,
or current reports explicitly. An empty list during provider outage does not
mean roads are clear. Forge owns the protected OHGO key and the Pi only reads
Forge's retained route. Reports are informational and unverified for your route;
there are no automatic warnings, navigation changes, or map overlays.
