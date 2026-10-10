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
