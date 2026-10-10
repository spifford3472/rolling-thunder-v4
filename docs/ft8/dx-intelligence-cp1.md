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

## CP2.4 Forge evidence snapshot cache (not yet live)

`forge_psk_evidence_snapshot.py` wraps the read-only historical path adapter
with a bounded 2-minute cache, up to 256 sender/target-grid/frequency keys,
explicit observed/no-recent-evidence status and versioned JSON-compatible
snapshot fields. These are **observations**, not predicted QSO probabilities.
No listener, provider polling, secrets or production data modifications were
added. The existing PSK ingestion API remains unchanged; wiring an authenticated
private read endpoint and a Pi-side bounded background client requires another
checkpoint and review. Existing normalized archives may be sparse before
contact completion; do not advertise live reception coverage without evidence.

## CP2.4 private evidence API boundary (not deployed)

`forge_psk_evidence_api.py` adds a pure private HTTP request/response boundary
for `GET /api/v1/ft8/outbound-psk-evidence` with sender, target grid, and
frequency. It requires a separate long bearer token, does no writes or provider
polling, and emits the versioned cached snapshot without storage locations or
credentials. Unsupported methods, missing authorization and malformed requests
fail closed. **No network listener, environment secret, route registration, or
production service enablement is included in this checkpoint.** A later gated
composition step and Pi-side bounded background client are required before
mobile FT8 receives these snapshots. Data remains observational, not a QSO
success probability.
## CP2.4 guarded Pi evidence client (not yet wired to ranking)

`ft8/psk_evidence_client.py` provides a bounded read-only authenticated client
for the planned Forge endpoint. It validates directional outbound sender,
receiver area, band frequency, schema, nonfuture age <=30 min, and receiver
count; all network, stale, malformed and auth failures return no evidence.
It MUST run only in a background worker: no UI or radio callback may make a
synchronous network request. The client is not yet configured or called at
runtime; evidence-to-quality calibration and authenticated listener rollout
remain distinct gated checkpoints. No transmit behavior changes.

## CP2.4 standalone loopback evidence listener (disabled by default)

`forge_psk_evidence_server.py` provides an explicit opt-in loopback-only
HTTP adapter for the independent evidence API. It does not modify or restart
the existing Forge PSK worker. Before starting, the server verifies that the
operator-supplied normalized history database exists and includes the
`psk_reception` columns needed for directional observations. The PSK worker's
`history.sqlite3` is **not assumed** to be this database; its schema and
coverage must be audited independently. Missing/incorrect data aborts startup.
The separate token is loaded from an environment variable. No systemd unit,
listener activation, external address binding or production config is included.
Pi client remains unconfigured, and the observation-to-ranking evidence
calibration remains pending. No RF/power changes.
## CP2.4 normalized history coverage audit

`forge_psk_coverage_audit.py` is an operator-run read-only diagnostic: it
reports aggregate KI5VNB outbound FT8 receptions, independent receivers and
receiver-grid availability over the last 30 minutes, two hours and day. It
fails explicitly for missing/inaccessible or incompatible databases, and never
changes service permissions or discloses receiver identities. It is not a
normalized data ingest or a scheduled poll. The production worker's own
history database is not interchangeable with a normalized `psk_reception`
table. Before enabling evidence-backed ranking, an authorized operator must
identify the normalized database and verify sufficient pre-contact coverage.
