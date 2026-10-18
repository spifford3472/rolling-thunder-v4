# R1-A1 — opt-in UI critical-path timing

Source: `ui_timing.py` and `ui_main.py`; scope #345. Disabled by default. Set `RT_R1A_UI_TIMING=1` only on an authorized **nonproduction** process for measurement. Do not edit production unit or env without separate approval.

Collects monotonic durations in milliseconds for four aggregate categories: `refresh` (full Tk callback), `controls` (physical dispatch), `map` (all map widget update including radar image conversion), and `refresh_gap` (time between prior refresh completion and current start). Each collector retains the most recent 256 observations and writes p95 and max to stderr every 240 callbacks (captured by systemd/journald without requiring root Python INFO logging). No callsigns, location, QSO payload, image or RF data are recorded. Collection does not trigger requests or radio commands.

Metrics are **diagnostic**: `refresh_gap` includes the nominal 250ms scheduled delay; it is not a direct indication of FT8 deadline slip. Radar-specific PhotoImage cost is included in `map` but must be distinguished from base map and POTA work using paired scenarios. Exceptions still propagate; the collector does not swallow errors. A catastrophic exception before callback completion won't generate the current `refresh` measurement; use existing exception logs.

Validation approach: run `pytest -q tests/test_ui_timing.py` plus existing directly affected UI integration tests on an isolated machine. Three integrated replay scenarios: radar disabled, radar enabled cached frames, radar enabled slow/unavailable Forge with simulated controls and FT8 receive. Compare existing FT8 `boundary_lateness_ms`, `periods_dropped`, clock health, and UI p95/max; do not add micro-tests or operate RF. Observe whether map cost dominates refresh, or whether delays instead originate in controls or scheduling/CPU. **Do not infer causal improvement from counters alone.**

This patch does not instrument individual CAT writes, PTT or FT8 timing, which remain available via existing diagnostic paths; deeper hooks require a separate evidence-based decision. No production deployment, merge or test RF is authorized by this documentation.

## R1-B bounded radar tile redraw

When radar frame or viewport changes, the Tk adapter now queues visible radar tiles rather than constructing every `PhotoImage` synchronously in one refresh. At most **two new radar tiles** are created per UI refresh, with remaining tiles appearing during subsequent 250 ms refresh cycles. Queued stale tiles are cleared on radar disable or viewport redraw; pending same-frame tiles survive unrelated snapshot updates. Network radar fetching remains on the existing background worker, while Tk canvas/image calls stay on the Tk thread.

This bounds the number of radar image conversions per callback rather than guaranteeing a hard millisecond deadline. The visual radar layer can fill progressively for several refresh cycles. Compare R1-A timing `map` and `refresh` p95/max under actual garage conditions, including frame swaps and rapid viewport changes, before declaring the latency issue resolved. Normal FT8, CAT/PTT and controller paths are unchanged.
