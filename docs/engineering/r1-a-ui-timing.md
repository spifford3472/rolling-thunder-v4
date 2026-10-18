# R1-A1 — opt-in UI critical-path timing

Source: `ui_timing.py` and `ui_main.py`; scope #345. Disabled by default. Set `RT_R1A_UI_TIMING=1` only on an authorized **nonproduction** process for measurement. Do not edit production unit or env without separate approval.

Collects monotonic durations in milliseconds for four aggregate categories: `refresh` (full Tk callback), `controls` (physical dispatch), `map` (all map widget update including radar image conversion), and `refresh_gap` (time between prior refresh completion and current start). Each collector retains the most recent 256 observations and logs p95 and max every 240 callbacks. No callsigns, location, QSO payload, image or RF data are recorded. Collection does not trigger requests or radio commands.

Metrics are **diagnostic**: `refresh_gap` includes the nominal 250ms scheduled delay; it is not a direct indication of FT8 deadline slip. Radar-specific PhotoImage cost is included in `map` but must be distinguished from base map and POTA work using paired scenarios. Exceptions still propagate; the collector does not swallow errors. A catastrophic exception before callback completion won't generate the current `refresh` measurement; use existing exception logs.

Validation approach: run `pytest -q tests/test_ui_timing.py` plus existing directly affected UI integration tests on an isolated machine. Three integrated replay scenarios: radar disabled, radar enabled cached frames, radar enabled slow/unavailable Forge with simulated controls and FT8 receive. Compare existing FT8 `boundary_lateness_ms`, `periods_dropped`, clock health, and UI p95/max; do not add micro-tests or operate RF. Observe whether map cost dominates refresh, or whether delays instead originate in controls or scheduling/CPU. **Do not infer causal improvement from counters alone.**

This patch does not instrument individual CAT writes, PTT or FT8 timing, which remain available via existing diagnostic paths; deeper hooks require a separate evidence-based decision. No production deployment, merge or test RF is authorized by this documentation.
