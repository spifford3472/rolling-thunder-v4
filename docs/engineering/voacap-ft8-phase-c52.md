# Phase C5.2 — Forge prospective source audit, no readiness promotion

This checkpoint adds a provider-free SQLite *read-only* source adapter,
`forge_ft8_prospective_inventory.audit_prospective_inbox`, and optional
`--inbox-db` / `--history-db` CLI inputs to the C5.1 readiness timer.
The adapter checks v2 operator-choice UTC, immutable event payload SHA256,
transmitted-period presence, explicit Forge field-observed provenance,
provider-ready links marked pre-choice and training-eligible, and link/provider
availability no later than the frozen operator choice instant. It maintains
per-band counts and exclusions while preserving the independent-source
database as strictly read-only. It neither fetches missing provider forecasts
nor modifies radio state. Missing stores/tables and invalid hashes fail closed.

Counts are explicitly *inventory metrics only*. Even genuine field-origin,
pre-choice forecasts may be insufficient to learn a calibrated contact
success probability or to establish that 15 W is noninferior to 20 W; real
randomized control/test comparisons and pre-registered forward held-out
analysis are still necessary. The existing C5.1 readiness CLI continues to
emit OFF/COLLECTING/DEGRADED, never READY or applied wattage.

**Not production deployment.** Do not point the example timer at assumed
SQLite paths. Its current C4 example path has not been verified against
the installed C3 worker permissions. The approved deploy wrappers do not
support the component yet. Before activation implement a component-scoped,
exact-SHA staging/wheel/deploy/rollback helper; verify service ACL, real
source paths, schema compatibility, read-only copies of data and genuine
provider configuration. C4 pilot provider egress still requires separate
authorization and budget checks. Deploy compatible Forge receiver before
the Pi v2 event stream.

See issue #312 for mandatory end-to-end scientific calibration and service
automation gates. Without those, a boot-started timer will report
COLLECTING forever and is not an acceptable completed power optimizer.
