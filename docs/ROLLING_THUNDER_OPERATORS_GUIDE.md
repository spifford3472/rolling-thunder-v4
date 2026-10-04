# Rolling Thunder Operator's Guide

## 1. What Rolling Thunder is

Rolling Thunder is an in-vehicle amateur-radio operating console designed to reduce the amount of attention required to manage radio, logging, location, spotting, weather, and supporting information while mobile.

The primary user interface runs on the Raspberry Pi named `anvilmobile`. It combines local hardware state with retained backend information from Forge. The system is deliberately local-first: loss of Forge, WireGuard, cellular coverage, QRZ, Wavelog, weather providers, or other remote services must not erase a valid local contact or prevent core local operation.

Rolling Thunder is not intended to replace operator judgment. It presents information, performs bounded receive tuning and approved feature-specific actions, and records contacts. Where the radio or antenna still requires a manual operator action, Rolling Thunder should say so rather than pretend the action was completed.

## 2. Why use it

Rolling Thunder brings several mobile operating tasks into one consistent interface:

- current radio frequency and mode;
- GPS position and Maidenhead grid;
- POTA and DX opportunities;
- free-form Browse tuning;
- native FT8 CQ browsing and one-QSO-at-a-time operation;
- nearby six-meter repeaters;
- DMR hotspot activity and DMR contact logging;
- current and retained weather;
- location-aware severe-weather alerts;
- map, radar, POTA park markers, and vehicle position;
- callsign/contact intelligence;
- local contact logging and later synchronization to Wavelog;
- system/service health and degraded-state visibility.

The design goal is to let the operator see what matters now, make one explicit action, and receive clear feedback.

## 3. The basic operating model

Rolling Thunder is organized into dashboard contexts, or screens. The current contexts are:

1. POTA
2. DX
3. Browse
4. FT8
5. Repeaters
6. AI Advisor
7. Weather
8. Settings
9. Log
10. DMR

The physical-control layer converts buttons and the rotary encoder into generic application actions. The meaning of a context button or encoder press can change with the active screen, but the underlying control path is shared and guarded against duplicated/rapid-repeat events.

Common operator concepts include:

- **Next Context** — move to the next screen.
- **Home Context** — return to POTA.
- **Rotate encoder** — move a selection, scroll, zoom, or tune depending on context.
- **Short encoder press / Activate Selection** — act on the currently selected item.
- **Back** — cancel or clear the active selection where supported.
- **Voice** — start bounded callsign capture.
- **Commit** — durably save a ready pending contact.
- **Discard** — clear the current pending callsign/contact state.
- **Context Buttons #1-#3** — screen-specific commands.

The screen itself does not directly operate serial ports or network services. Slow work is performed by background services and the dashboard displays immutable published state.

## 4. Persistent dashboard information

### Radio state

Rolling Thunder continuously polls the configured radio through the typed radio/CAT layer. The dashboard may show frequency, mode, connection state, and other approved radio state.

If the radio is disconnected or its state is incomplete, actions that require a reliable target should fail closed rather than guess.

### GPS and Maidenhead grid

The installed GPS is the shared source of vehicle location. Rolling Thunder derives the current Maidenhead grid from the trusted GPS position.

The same location state is consumed by mapping, contact logging, FT8, repeater distance calculations, weather applicability, and Forge location publication. A feature should not maintain a competing definition of the vehicle's current position.

### Status and health

The dashboard uses status/health presentation to show routine actions, success, warnings, degradation, and failures.

Typical states include:

- ready/live;
- retained/cached;
- degraded/stale;
- disabled/unavailable;
- explicit error/failure.

Retained data is intentionally kept visible when it remains useful, but the UI should identify that it is retained rather than live.

## 5. POTA screen

### Purpose

POTA presents current Parks on the Air spots from the shared Forge spot service. It is intended to help the mobile operator find useful active stations and move the receiver to the exact selected spot.

### What is shown

POTA cards are derived from provider-neutral spot records and can include:

- callsign;
- park reference and park name;
- frequency;
- mode;
- operator name/grid when available;
- spot age and related metadata;
- local worked-today indication.

A successfully logged POTA combination is marked worked for the current UTC date using callsign + displayed POTA mode + amateur band. The marker survives dashboard restart during the same UTC day.

### Filters

POTA supports the mobile HF band cycle:

- 80 m
- 40 m
- 20 m
- 17 m
- 15 m
- 12 m
- 10 m

Mode groups are:

- SSB
- CW
- FT4
- FT8
- DATA
- ALL

POTA also applies its configured spot-age rule. Its filter state is independent from DX.

When POTA is activated, Rolling Thunder prefers the current radio band when it is one of the supported bands; otherwise it falls back to 20 m. POTA begins from SSB filtering.

### Using the screen

Rotate the encoder to move among visible spots. Context controls cycle the POTA band and mode filters. Changing a filter cancels a previously staged/selected action if that action is no longer valid.

A single activation of a selected POTA row snapshots the exact selected identity, callsign, frequency, and normalized mode and submits a background receive-tune request.

Rolling Thunder never silently chooses the next row if the selected spot disappears.

### Cross-band warning

On a successful cross-band receive tune, Rolling Thunder may display:

```text
SET BAND TO <BAND> METERS — TUNE ATAS-120
```

That message is an operator handoff. It does not claim that the radio front panel is in the required band context or that the ATAS-120 has been tuned.

## 6. DX screen

### Purpose

DX presents live DX spotting information retained by Forge. The production DX source is DX Summit IRC, consumed through one long-lived Forge connection.

The Pi does not connect directly to DX Summit.

### What is shown

DX uses the same provider-neutral spot domain as POTA and presents callsign, exact frequency, normalized mode, and available enrichment/source metadata.

DX does not inherit POTA's maximum-age filter.

### Filters and controls

DX supports the same 80/40/20/17/15/12/10 m bands and SSB/CW/FT4/FT8/DATA/ALL mode groups.

DX filter state is independent from POTA. DX starts from ALL modes when activated.

Rotate to select a station; context controls cycle filters; short activation performs the same exact one-selection background receive-tune path used by POTA.

### DX backend behavior

Forge maintains one persistent IRC connection to the DX Summit `#CQDX` stream. Normal Rolling Thunder refreshes read Forge's retained state and do not cause new IRC connections.

A healthy long-running system should normally show zero unnecessary reconnects.

## 7. Browse screen

### Purpose

Browse is the free-form operating screen for ordinary receive tuning and contact work that does not begin from a POTA/DX/repeater candidate.

### What it does

Browse uses the shared radio state and tuning boundary. It supports operator-controlled frequency adjustment, tuning-step changes, and mode changes without creating an independent radio-control implementation.

The current Browse controller supports cycling tuning step and mode, then adjusting frequency with the generic movement controls.

### Contact workflow

Browse can participate in the normal callsign capture and Commit/Discard workflow. A pending callsign may also trigger the shared callsign-information overlay when that feature is enabled and Forge is available.

Contacts committed from Browse use the same durable local contact path as other non-FT8 workflows.

## 8. FT8 screen

### Purpose

The FT8 screen is a native CQ browser and bounded one-QSO-at-a-time operator workflow. It is not a general list of every decoded FT8 message.

A callsign becomes eligible when Rolling Thunder decodes that station calling CQ and it remains within the activity window.

### CQ row states

Current row presentation includes:

- **Yellow** — fresh CQ, normally one or two CQ observations.
- **White** — repeated CQ, normally three or more CQ observations.
- **Gray** — station previously called CQ but recent traffic shows it active with another station.
- **Red + !** — an attempt failed/timed out/exhausted retries or hit execution/preparation failure today on this band.
- **Blue + ■** — the operator intentionally aborted an attempt today on this band.
- **Tree symbol** — the decoded CQ explicitly contained a POTA token.

A successful callsign/band combination disappears from the CQ list for the rest of the UTC day. The same callsign on another band remains eligible.

### Controls

- Rotate encoder — move through eligible CQ stations.
- Short encoder press — explicitly authorize exactly one QSO with the selected station when transmit is enabled.
- Context Button #1 — cycle supported FT8 bands and tune the standard FT8 dial frequency.
- Context Button #3 during an active QSO — abort the current FT8 QSO.
- Leaving FT8 — abort active FT8 work and restore normal radio settings.

### Radio preparation

Before an authorized FT8 transmission, Rolling Thunder prepares/verifies the approved FT-891 settings including the selected FT8 dial frequency, 20 W transmit power, and SSB-BFO USB.

Preparation failure is fail-closed: no PTT and no FT8 transmit audio.

Leaving the FT8 context restores the approved normal radio settings, including 100 W and SSB-BFO AUTO.

### Safety

Every FT8 QSO requires a new explicit operator action. Rolling Thunder does not automatically call the next decoded station.

See `docs/FT8_OPERATOR_GUIDE.md` for the detailed FT8 operating reference.

## 9. Repeaters screen

### Purpose

The repeater screen presents nearby six-meter analog repeaters from the approved local deployment data set.

### What is shown

Repeater cards include:

- channel/callsign name;
- receive frequency;
- derived shift;
- TX and RX tone values;
- current GPS-derived distance;
- effective ACTIVE or INACTIVE state.

Distances are calculated from the current trusted GPS position. Stale or unavailable GPS is displayed as such rather than producing guessed distances.

### Filters and controls

Default view is Active only.

- Context Button #1 — toggle Active-only / All.
- Context Button #2 — toggle the selected repeater's local Active/Inactive preference.
- Rotate encoder — move stable repeater selection.
- Short encoder press — run the selected repeater's typed radio-configuration workflow.
- Back — clear selection.

The source CSV is not rewritten by Active/Inactive changes; local overrides are stored separately.

## 10. AI Advisor screen

The AI context is currently a reserved dashboard context in the present codebase. The context exists in navigation, but the current context definition still identifies its detailed content as future work.

Operators should therefore not depend on the AI screen for safety-critical or radio-control decisions until implemented behavior is documented and accepted.

Any future implementation must update this Operator's Guide.

## 11. Weather screen

### Purpose

Weather shows retained Forge weather for the current mobile area and location-aware severe-weather alerts.

### Current conditions

When data is available the screen can show:

- Fahrenheit and Celsius temperature;
- relative humidity;
- normalized condition/icon;
- sunrise and sunset;
- next three future hourly temperatures;
- precipitation probability;
- provider attribution.

### Weather status

- **LIVE** — fresh usable backend state.
- **RETAINED** — previously good data retained after restart or temporary backend loss.
- **STALE** — usable data whose source age is beyond the normal fresh state.
- **DISABLED** — feature disabled.
- **UNAVAILABLE** — no usable data.
- **ERROR** — current refresh/error condition while still-valid retained data may remain visible.

The source age is based on provider/source time; restarting the dashboard does not make old weather appear fresh.

### Severe-weather alerts

Alerts are point-specific to the latest trusted vehicle GPS location. Rolling Thunder does not intentionally warn merely because an alert exists somewhere else in the county or region.

The Weather Alerts area normally shows:

```text
WEATHER ALERTS
NO ACTIVE WEATHER ALERTS
```

When applicable alerts are active, the screen shows a driving-oriented summary including event, expiration/end time, headline/area summary, severity, and status.

If a published alert summary exceeds the viewport, generic rotary movement scrolls the alert text while WEATHER is active.

### Audible alerts

Current notification policy includes:

- Tornado Warning, Severe Thunderstorm Warning, Flash Flood Warning — urgent distinctive alert;
- Tornado Watch, Severe Thunderstorm Watch — attention chime;
- other warnings — normal warning chime;
- advisories — visible and normally silent.

The same alert should not replay merely because the Pi or dashboard restarts.

## 12. Settings screen

Settings controls operator-visible preferences without moving provider/hardware logic into the UI.

Current cards include:

### Map Zoom

Rotate the encoder to zoom out/in within the configured map bounds.

### Map Style

Context Button #2 switches DAY/NIGHT style when more than one installed style is available. A manual override remains until the next real solar transition.

### Radar Image

Context Button #1 toggles Pi-side radar-image display/work. The preference is persisted.

### Callsign Info

Context Button #3 enables/disables the callsign-information overlay. The preference is persisted.

Turning callsign information off immediately hides/invalidates the active overlay and prevents new lookups until re-enabled.

## 13. Log screen

### Purpose

LOG shows recent locally stored Rolling Thunder contacts and their remote synchronization state.

The local SQLite contact is the authoritative success record. Wavelog synchronization occurs later in the background.

### What is shown

The newest ten contacts are displayed newest-first. Rows include:

- UTC date/time;
- callsign;
- band;
- offline-resolved country abbreviation when known;
- synchronization state.

Synchronization states include:

- **✓ SYNC** — synchronized;
- **○ WAIT** — pending;
- **! FAIL** — a remote synchronization attempt failed and remains retryable.

The header shows unsynchronized and total local counts.

### Controls

Context Button #1 requests synchronization of unsynchronized contacts now. The request runs in the background and does not make local logging dependent on Wavelog availability.

## 14. DMR screen

### Purpose

The DMR panel monitors the configured WPSD/MMDVM hotspot and supports DMR contact logging. It has no transmit authority.

### Monitored talkgroup

Rolling Thunder learns the currently monitored talkgroup from RF activity by the configured operator callsign. It does not assume a fixed talkgroup such as TG3100.

If no monitored talkgroup is known, the panel displays `TG ?` and history/current-audio logging selection is disabled.

### Activity filtering

The operator-facing history is filtered to the current monitored talkgroup. Unrelated busy talkgroups do not become selectable logging candidates.

Current-audio and history staging freeze the exact talkgroup into the staged QSO. If the monitored talkgroup changes, a staged QSO from the prior talkgroup is invalidated and must be staged again.

DMR failure does not block ordinary local logging, GPS, mapping, POTA/DX, repeaters, controls, or radio polling.

## 15. Live map

### Purpose

The live map provides vehicle position and local situational awareness while remaining useful with installed/offline map packages.

### Map behavior

The primary map is north-up and can use installed regional MBTiles, runtime cache, then permitted online map retrieval according to configured source priority.

The map may show:

- vehicle position;
- course/heading-oriented vehicle marker;
- POTA park markers;
- weather radar;
- map/GPS/radar health;
- local weather information;
- optional callsign-information overlay.

Loss of online maps does not automatically blank already available installed/cached map data.

### POTA markers

At higher zoom levels, POTA parks are shown with reference/name labels; at lower zoom levels they are compact yellow dots. Park catalog coordinates are approximate situational-awareness pins, not proof of an activation boundary.

### Radar

Radar is an optional overlay with its own health/lifecycle. Radar failure must not prevent base-map use.

## 16. Callsign information overlay

### Purpose

The optional contact-information overlay answers:

1. Who is this station?
2. Where are they operating?
3. What is the weather there?
4. Have I worked them before?

It is a shared dashboard capability and is not owned by POTA alone.

### Information sources

Forge may combine:

- QRZ identity/QTH;
- latest exact-callsign Wavelog contact history;
- target current weather;
- POTA park coordinates when a selected POTA activation provides a better current operating location.

If no previous QSO exists, the overlay displays:

```text
FIRST CONTACT
```

### Failure behavior

If Forge, QRZ, Wavelog, weather, or the network is unavailable, the lookup failure does not block radio control or local contact logging. No large modal failure should interrupt the operating workflow.

## 17. Contact logging

Rolling Thunder uses durable local logging.

The core rule is:

```text
Commit locally first
    -> preserve the QSO
    -> synchronize remotely later
```

A valid local contact must not disappear because Wavelog, Forge, WireGuard, or the internet is down.

The current local database also retains retry state and supporting metadata required for later synchronization.

## 18. Forge backend

### What Forge is

Forge is the backend-services host used by Rolling Thunder. It performs external-provider and server-style work that should not block the mobile UI.

Forge is intentionally being treated as a reusable backend platform. Its services should be callable by other authorized applications in the future, not only by Rolling Thunder.

### Spot / weather / radar service

The primary Forge spot service publishes a private retained API and owns:

- POTA ingestion;
- DX Summit IRC ingestion;
- provider health;
- optional disabled DXSpider fallback;
- retained canonical spot snapshots;
- weather;
- severe-weather alerts;
- radar;
- mobile-location state used by backend services.

Production DX Summit behavior is one long-lived IRC connection with PING/PONG and failure-only reconnect/backoff. Rolling Thunder polling does not create a new DX Summit connection.

### Callsign information service

A separate callsign-information process owns QRZ, Wavelog contact-history, target-weather work, and bounded caches.

The Pi sends a callsign and optional current POTA location context; Forge returns compact contact intelligence.

### Contact synchronization service

A separate contact-sync process receives normalized locally committed contacts and synchronizes them to the approved Wavelog station location.

It uses durable idempotency state so retries do not casually create duplicate Wavelog QSOs.

### Why services are separate

Separating backend processes limits failure domains. A Wavelog authentication problem should not stop DX spots. A radar/provider problem should not stop local logging. A dashboard restart should not restart a healthy long-lived DX Summit connection.

## 19. Offline and degraded operation

Rolling Thunder should continue to provide useful local functions when remote services fail.

Examples:

- locally committed contacts remain safe;
- cached/retained spots may remain visible with truthful status;
- installed/cached maps continue when available;
- local GPS continues;
- radio polling/control can continue;
- repeaters continue from the local data set;
- Wavelog synchronization waits and retries later;
- failed callsign intelligence does not block Commit;
- weather/radar/backend failure does not grant or remove radio transmit authority.

## 20. Startup behavior

The production service uses an uptime-aware startup safeguard.

If Raspberry Pi system uptime is already at least 180 seconds, starting or restarting Rolling Thunder proceeds immediately.

If system uptime is less than 180 seconds, the launcher waits only for the remaining time until system uptime reaches three minutes. This allows boot-time hardware/desktop services to settle without imposing a new three-minute delay on ordinary later service restarts.

## 21. Interpreting warnings and failures

### Tuning failure

A receive-tune failure means Rolling Thunder could not verify the requested action. Treat the radio's actual state as authoritative and correct it manually.

### Cross-band ATAS warning

`SET BAND TO ... — TUNE ATAS-120` requires operator action before transmit.

### Retained data

Retained/cached data can be useful but may not reflect the newest provider state. Read its health/age status.

### GPS stale/unavailable

Do not assume displayed old location is current. Location-specific calculations and alerts deliberately degrade when trusted GPS is unavailable.

### Synchronization failure

A Wavelog synchronization failure is not a lost QSO if the contact was successfully committed locally.

### FT8 failed/aborted attempt

Failed or aborted FT8 attempts are not normal QSOs and are not sent to Wavelog as completed contacts.

## 22. Recovery philosophy

Rolling Thunder favors explicit recovery points, durable local state, and reversible deployments.

Before major experimental development, preserve a known-good release/tag plus production configuration and database-safe backups. Experimental code should never require reconstructing a known-good production state from memory.

## 23. More detailed references

For subsystem-specific detail, see:

- `docs/FT8_OPERATOR_GUIDE.md`
- `docs/CALLSIGN_INFO.md`
- `docs/SHARED_SPOT_DOMAIN.md`
- `docs/REPEATERS.md`
- `docs/DMR_HOTSPOT.md`
- `docs/WEATHER_PANEL.md`
- `docs/WEATHER_ALERTS.md`
- `docs/LIVE_MAP.md`
- `docs/FORGE_SPOT_SERVICE.md`
- `docs/FORGE_CONTACT_SYNC.md`
- `docs/PI_AUTOSTART.md`
