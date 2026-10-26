# R1-A1 — opt-in UI critical-path timing

Source: `ui_timing.py` and `ui_main.py`; scope #345. Collection is disabled by default and enabled with `RT_R1A_UI_TIMING=1`. The October 18 production baseline has this setting enabled. Do not change production unit or environment settings without separate approval.

Collects monotonic durations in milliseconds for six aggregate categories: `refresh` (full Tk callback), `controls` (physical dispatch), `map` (whole map widget update), `base_map` and `radar` (their respective map-update subsections), and `refresh_gap` (time between prior refresh completion and current start). Each category retains the most recent 256 observations and writes p95 and max to stderr every 240 callbacks (captured by systemd/journald without requiring root Python INFO logging). No callsigns, location, QSO payload, image or RF data are recorded. Collection does not trigger requests or radio commands.

Metrics are **diagnostic**: `refresh_gap` includes the nominal 250ms scheduled delay; it is not a direct indication of FT8 deadline slip. Radar-specific PhotoImage cost is included in `map` but must be distinguished from base map and POTA work using paired scenarios. Exceptions still propagate; the collector does not swallow errors. A catastrophic exception before callback completion won't generate the current `refresh` measurement; use existing exception logs.

Validation approach: run `pytest -q tests/test_ui_timing.py` plus existing directly affected UI integration tests on an isolated machine. Three integrated replay scenarios: radar disabled, radar enabled cached frames, radar enabled slow/unavailable Forge with simulated controls and FT8 receive. Compare existing FT8 `boundary_lateness_ms`, `periods_dropped`, clock health, and UI p95/max; do not add micro-tests or operate RF. Observe whether map cost dominates refresh, or whether delays instead originate in controls or scheduling/CPU. **Do not infer causal improvement from counters alone.**

### R1-C3 bounded subphase probe

The same disabled-by-default environment flag now adds correlated detail only to
the existing rate-limited `R1C2_SLOW_REFRESH` record. Fixed enum-like tokens split
the broad `map_prepare` interval across radio/status synchronization, weather and
alert publication, GPS/map snapshot and viewport requests, POTA/radar requests,
and FT8 snapshot/presentation calls. Map update reports count/total/max duration
for base/radar planning, base64 preparation, `PhotoImage`, canvas insertion, POTA,
and overlay/status work. Accepted physical commands report only their typed action
token and count/total/max duration. The dispatcher still executes actions inline
and in the same order; rejected/unknown source events are not reported.

Per-refresh detail is bounded by a fixed token inventory and discarded when the
next refresh begins. Slow records remain limited to one per second. No callsigns,
coordinates, event IDs, source inputs, QSO/control payloads, image bytes, audio,
or secrets are retained or printed. Disabled collection does not call the timing
clock. The probe changes no Tk ownership, queue limit, request order, exception
propagation, FT8 timing/state, radio command, or transmit authority.

This probe does not instrument individual CAT writes, PTT or FT8 timing, which
remain available via existing diagnostic paths. Source tests establish attribution
boundaries, not Raspberry Pi stall improvement or field causality. No production
deployment or test RF is authorized by this documentation.

### Offline export reporting

`tools/issue345_timing_report.py` reads one exported timing-text file only. Its CLI
requires `--input PATH` and `--source-sha SHA`; `--scenario` accepts only the
operator-declared labels `radar_off`, `radar_on`, `forge_slow`, or `unlabeled` and
defaults to `unlabeled`. It performs no subprocess, journal, network, database, or
hardware access. Input is limited to an 8 MiB regular file, 100,000 lines, 64 KiB
per line, and 4,096 recognized records. Output JSON contains only fixed timing
metric/phase/subphase/action names, counts and durations, the declared scenario and
source SHA, and explicit incomplete-evidence booleans. Unknown or malformed lines
are counted but never copied or converted to zero.

The report summarizes only the minimum and maximum values *reported by* overlapping
rolling-window aggregate records; it never averages those p95 values or calls them a
global percentile. Correlated slow records remain separate by refresh ID, including
legacy broad-phase records that have no fine detail. They are a rate-limited selected
sample rather than all refreshes or operator end-to-end latency. Reports therefore
always leave global percentiles, complete slow-sample coverage, operator latency,
and issue acceptance unavailable. Synthetic and fixture inputs must remain labeled
as such outside this utility and must never be presented as installed field evidence.

## R1-B bounded radar tile redraw

When radar frame or viewport changes, the Tk adapter now queues visible radar tiles rather than constructing every `PhotoImage` synchronously in one refresh. At most **two new radar tiles** are created per UI refresh, with remaining tiles appearing during subsequent 250 ms refresh cycles. Queued stale tiles are cleared on radar disable or viewport redraw; pending same-frame tiles survive unrelated snapshot updates. Network radar fetching remains on the existing background worker, while Tk canvas/image calls stay on the Tk thread.

This bounds the number of radar image conversions per callback rather than guaranteeing a hard millisecond deadline. The visual radar layer can fill progressively for several refresh cycles. Compare R1-A timing `map` and `refresh` p95/max under actual garage conditions, including frame swaps and rapid viewport changes, before declaring the latency issue resolved. Normal FT8, CAT/PTT and controller paths are unchanged.

## R1-B2 base-map budget and rendering timing

New base-map tile images are queued and rendered at most two per Tk refresh; queued work is reset on full viewport rebuild and retained by key when the same zoom viewport is updated. The map can fill progressively after pan/zoom. This complements R1-B radar batching, without changing background map retrieval or radio control. Pending base tiles continue advancing each regular UI refresh even with no new snapshot.

When `RT_R1A_UI_TIMING=1`, logs also include `base_map` and `radar` duration metrics. These measure their respective synchronous update sections, while `map` continues to measure the whole map widget update. Compare these metrics for the same sample windows; they do not prove which individual tile conversion is expensive. Validate raster appearance and responsiveness with actual Pi display before closing R1-B.

### R1-B2a logging correction

The `base_map` metric is explicitly observed around base-map snapshot work and the pending base-tile flush on every widget update (including unchanged snapshots). This repairs a missing timing hook from R1-B2. No scheduling, rendering, radio, or radar behavior is changed by this correction. Use the separate `base_map`, `radar`, `map` and `refresh` aggregates to select the next focused investigation, rather than attributing unrelated maxima to the same callback.

## R1-C1 FT8 band presentation

FT8 receive-band tuning continues on its established background worker and retains existing CAT/PTT authorization. While the tune status is TUNING, the dashboard band field shows `TUNING <target>`. Once the worker publishes a verified `ReceiveTuneOutcome`, the dashboard may show its verified frequency and band before the ordinary one-second radio-state polling snapshot catches up. Once polling confirms that frequency, the outcome is acknowledged and cannot overwrite subsequent independent radio changes. An unsuccessful tune never presents the requested band as confirmed. No polling cadence change or additional CAT query is introduced.
