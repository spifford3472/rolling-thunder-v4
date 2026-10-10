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
best-effort configured transmit-power snapshot. When weather notes are enabled,
synchronized Wavelog notes use weather already captured on the contact and explicitly
show `N/A` when it is absent; contact synchronization never waits on public weather.
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
trigger the shared contact-information overlay. POTA park coordinates have
priority for target weather/map placement when the contact is known to be at a
current park activation.

The overlay itself is shared infrastructure and is not a POTA-only popup.

## If POTA data is unavailable

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

## Band/mode advisory

Rolling Thunder can present U.S. Amateur Extra band/mode advisories. These are
operator warnings, not a substitute for operator responsibility or regulatory
knowledge.

## Contact location

Normal contact logging uses the shared current GPS/Maidenhead state available at
the appropriate contact lifecycle point.

---

# 8. FT8 Screen

The FT8 DX Intelligence browser shows CALL, COUNTRY (conservative callsign-prefix
abbreviation), GRID, and REACH (LOW/MEDIUM/HIGH ranking confidence or PENDING).
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
- Leaving the FT8 context aborts active FT8 work before restoration.

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

- **Encoder** — zoom map out/in.
- **Context Button #1** — enable/disable radar image display when available.
- **Context Button #2** — switch DAY/NIGHT map style when both styles are
  available.
- **Context Button #3** — enable/disable the callsign-information overlay.

The page displays the effective zoom and availability of the map/radar/callsign
controls.

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
- target local time when a reliable IANA timezone accompanies that weather;
- prior-QSO summary;
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

The overlay follows the shared pending callsign. Callsign replacement, Commit,
Discard, timeout, or disabling the feature invalidates the current overlay.

`LOCAL` means the contacted target's time, including daylight-saving rules. If Forge
cannot establish that timezone reliably, the field is left blank rather than showing
the vehicle/operator timezone.

If Forge/QRZ/Wavelog/weather is unavailable, contact logging and radio operation
continue; an enrichment failure is not a Commit failure.

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
on the QSO, and missing contact or local weather is shown as `N/A`.

If the contact has no operator notes, its Wavelog ADIF `NOTES` value is `Mobile QSO`.
Existing notes are kept exactly and are not prefixed, appended, or replaced. Station
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
| Settings | Runtime display/preferences | Encoder zoom; Buttons 1 radar, 2 style, 3 callsign info |
| Log | Recent contacts/sync status | Button 1 forced sync |
| DMR | Monitor/log hotspot contacts | Button 1 current caller; Button 2 commit; encoder history |
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
