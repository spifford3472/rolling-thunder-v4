# FT8 DX intelligence CP1: offline scoring foundation

This versioned model produces relative ordering **only**; it is not a calibrated
probability of QSO success. It never tunes, keys, changes power or selects a CQ.

DX distance is computed from Maidenhead centers, saturating above long paths.
Reachability starts at a *neutral prior*, not a presumed failure. Recent
directional evidence can move priority up or down in proportion to freshness
and independent-receiver count. Local received SNR is only weakly weighted:
hearing a CQ well does not establish reciprocity.

Callers must verify receiver direction, frequency/band, age, and provenance
before supplying evidence. Completed-QSO PSK archives alone cannot stand in
for live actionable coverage. Missing grid, stale data, or absent reports
lower confidence, not rank to zero. Current model score is **not a percentage**.

CP1 deliberately does not sort the live CQ browser, change persistent
selection, integrate Forge APIs, adjust FT8 power, or modify QSO machinery.
Future integration must freeze selection during negotiation, avoid reordering
under the encoder cursor, and verify real-world model calibration before
presenting numeric reachability probabilities.

## CP2 forward-compatible inputs (not integrated)

`ft8/propagation_inputs.py` reserves independent, typed VOACAP and
space-weather slots, both defaulting to `unavailable`. Each snapshot records
source, state, observation/validity times and provider version. A validity
check may classify metadata as usable but does **not** cause a scoring effect.

When integrated later, VOACAP needs path origin/destination (including current
mobile coordinates), UTC time, band/frequency, antenna assumptions, target
reliability and prediction provenance. Space-weather inputs may include Kp,
Ap, solar flux, X-ray/flare and geomagnetic disturbance indicators with UTC
timestamps and provider freshness. These are **future design examples**, not
currently parsed or populated fields. Provider-specific accuracy, direction,
coverage, missingness and weighting must be validated before use.

No forecast is consulted by `rank_cqs`, and no automatic radio power
adjustment follows from these extension contracts. An absent, stale or
temporarily unreachable feed must never force a closed-band determination.

## Async ranking cache checkpoint (not wired to live CQ browser)

`FT8RankingCache` accepts a caller-owned executor and callable. Missing
stations return immediately as `pending`, display as **NEW** above ranked
entries, and are never hidden due to a 1-second backend timeout. The UI
should render pending feedback promptly; it must not block for that second.
Cached station rankings have a 30-minute monotonic TTL, scoped by callsign,
band, local grid, and remote grid. Expired entries remain visible with their
previous score while refreshing in the background (stale-while-revalidate).
Worker failure leaves unranked stations visible and never blocks FT8 receive.

Ranking updates are advisory and must not move the highlighted/selected
station under an encoder press or during a QSO. The eventual UI consumer
must freeze browse ordering during active selection, coalesce refreshes,
and avoid oscillating rows. Cache currently has no disk persistence, no
worker scheduling/timeout policy, and no live UI integration. Future work
should introduce bounded retry backoff on provider outages, bounded worker
queue, maximum entries/eviction and clear source-data age semantics.

## CP2.3 browser ordering boundary

The panel controller now accepts an optional, pure activity-order callback after
worked-today and other eligibility filters have removed suppressed CQs. No
ranking can reintroduce a filtered successful QSO. The controller holds the
current callsign sequence while the operator highlights a station or a QSO is
active. New stations remain available, appended until the selection clears.

This is a guarded **integration seam**, not yet an enabled ranking UI:
production composition does not yet supply the cache-backed callback.
The existing yellow/white/gray/red/blue status colors, green POTA tree,
friend markers, selected-row highlight, and QSO workflows are untouched.

## CP2.3 local-first runtime activation

FT8 runtime now constructs a local-only, bounded-thread FT8 browser ranker.
The existing CQ suppression filter runs first; the panel's ordering callback
scores callsigns and grids on a background executor. Unranked stations display
`NEW` in their **existing callsign color**, sorted ahead of scored stations;
the existing green POTA tree and friends are unchanged. A station remains
selectable even when no score exists. Cache freshness is 30 minutes, separated
by callsign, band, local/remote grid; mobile GPS Maidenhead is used when
available, otherwise configured operator home grid is used.

This is *local DX-opportunity ordering*, NOT evidence-backed reachability or a
calibrated QSO probability. No Forge provider is queried. The operator's
highlight locks ordering; the FT8 authorization/QSO/RF sequence is unchanged.
The scoring executor closes without waiting on shutdown. Future pre-contact
PSK enrichment must use bounded/coalesced provider retries before activation.

## CP2.4 outbound PSK evidence read adapter (not connected to live ranking)

`forge_psk_path_evidence.py` provides bounded, read-only access to existing
normalized PSK Reporter history. It requires **our callsign as the sender**, FT8
mode, frequency neighborhood, the last 30 minutes, and receiver grids within
600 km of the prospective DX station. It deduplicates receivers by callsign
and returns observation counts, latest time and median nearby-receiver SNR.
Missing history returns empty neutral evidence, not a closed-band prediction.
The historical per-QSO query pipeline may have little pre-QSO coverage.

This checkpoint deliberately does not convert counts/SNR into an uncalibrated
0–1 quality estimate, expose a network endpoint, or send evidence to the Pi.
Provider provenance and sample freshness must be validated before connecting
to the ranking model. This module never writes to production data.
