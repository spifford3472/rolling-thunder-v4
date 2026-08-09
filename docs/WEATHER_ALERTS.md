# Location-Aware Severe Weather Alerts

Issue #182 adds severe-weather alert situational awareness after the retained
weather panel work in #165.

## Hard relevance invariant

Rolling Thunder may display or sound a location-specific weather alert only
when the latest trusted current Rolling Thunder GPS point is relevant to that
alert.

The implementation is deliberately point-specific. It must not surface an
alert merely because it is nearby, affects another part of a county, or is
present elsewhere in the region.

If a trustworthy current GPS location is unavailable, the system must not
claim that a newly observed location-specific alert applies to the vehicle.
Previously retained state may remain visible only with truthful retained or
location-unverified presentation.

## Provider and authority boundary

The supported path is:

```text
NWS active-alert point query
    -> Forge provider
    -> provider-neutral retained Forge alert state
    -> versioned Forge REST
    -> Pi retained alert client
    -> immutable application state
    -> WEATHER panel and alert-audio controller
```

The Pi does not query the National Weather Service directly.

Forge uses the latest trusted retained mobile location as the point supplied to
the NWS active-alert endpoint. The provider result is therefore tied to the
exact point used for that request. Entering or leaving an alert area is observed
as a change in the active alert set returned for successive trusted points.

NWS requires a distinct User-Agent for API clients. Alert polling must remain
bounded and must not exceed NWS guidance; the initial Rolling Thunder target is
one eligibility check no more frequently than every 30 seconds.

## Retained alert domain

The provider-neutral alert representation retains enough information for
truthful presentation and durable deduplication, including:

- stable provider alert identifier;
- event name;
- severity;
- urgency;
- certainty;
- headline;
- effective, onset, ends, and expires timestamps when supplied;
- provider/source attribution;
- the latitude/longitude point used for applicability;
- provider fetch time;
- active/cancelled/expired lifecycle information needed by the retained state.

The retained state also exposes provider health and source age independently of
whether the active alert set is empty. An empty, successfully refreshed set is
a valid `NO ACTIVE WEATHER ALERTS` result, not an unavailable state.

## Location transitions

A new alert becomes newly relevant when either:

1. NWS first returns a newly issued alert for the current trusted point; or
2. the vehicle moves and NWS returns an already-existing alert that did not
   apply to the prior trusted point.

Leaving an affected area removes the alert from the active presentation.
Re-entering may create a new applicability transition, but audible replay policy
is separately controlled by durable acknowledgement/deduplication state.

## Audible notification

Audio is event-driven, never poll-driven. Polling the same unchanged alert set
must not repeatedly make sound.

Initial policy:

- Tornado Warning, Severe Thunderstorm Warning, and Flash Flood Warning:
  urgent distinctive alert;
- Tornado Watch and Severe Thunderstorm Watch: attention chime;
- other warnings: normal warning chime;
- advisories: visible and silent by default.

The same provider alert identifier must not replay solely because the dashboard
or Pi restarted. Durable Pi acknowledgement/deduplication state survives
restart.

This is a Rolling Thunder notification only. It does not emulate EAS and grants
no transmission authority.

Audio failure is isolated from local logging, GPS, maps, radar, controls, spots,
weather presentation, and radio polling.

## WEATHER panel

The existing WEATHER context keeps its accepted current-conditions and hourly
presentation in the upper portion of the panel. Approximately the lower third
is reserved for `WEATHER ALERTS`.

Normal state is compact:

```text
WEATHER ALERTS
NO ACTIVE WEATHER ALERTS
```

When one or more alerts apply to the current trusted point, the panel shows only
driving-safe summary information: event, local expiration/end time, concise
headline or area text, and severity/status. Full provider descriptions and long
instruction bodies are not rendered in the driving panel.

## Threading and failure isolation

NWS HTTP, SQLite, deduplication persistence, and audio playback never execute in
Tk callbacks. Tk consumes immutable already-published state.

Provider failure must preserve any still-valid retained state while marking its
health truthfully. GPS loss must not fabricate new applicability. All failures
remain isolated from core Rolling Thunder operation.

## Radio safety

Issue #182 adds no PTT, MOX, keying, tuner, transmit-power, receive-tuning,
automatic-transmit, or unattended-transmit authority.

## Acceptance

Before merge, the exact accepted head requires:

- provider parsing tests using local fixtures only;
- trusted-point applicability and enter/leave tests;
- no-trusted-GPS behavior tests;
- empty-active-set, lifecycle, cancellation, and expiration tests;
- retained/offline/error-state tests;
- durable audible deduplication and restart tests;
- severity-to-audio-policy tests;
- WEATHER panel integration and installed driving-readability acceptance;
- audio-failure isolation tests;
- Ruff, strict MyPy, full pytest, pre-commit, and `git diff --check`;
- exact-head GitHub Actions;
- controlled Forge and `anvilmobile` acceptance;
- explicit repository-owner merge authorization.
