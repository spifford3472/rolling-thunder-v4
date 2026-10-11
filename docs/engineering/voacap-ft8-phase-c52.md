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

## Separate C4 regional as-of join

The C3 history per-attempt VOACAP link primarily describes retrospective or
post-attempt calculations, which are **not** the same as C4's provider-neutral,
pre-choice regional research forecasts. The independent
`forge_ft8_c4_asof.audit_c4_choice_pairs` reader now joins only explicitly
matching local 6-character grid, remote target-grid prefix, band, fixed C4
six-hour forecast window, and a verifiably earlier generated provider result.
It also checks the immutable plan identity, provider/model versions, request
and response SHA256, SSN timestamps and the v2 selection time. This returns
**regional as-of inventory counts**, not calibrated success odds. It correctly
rejects missing source paths or late provider predictions. Region-grid
resolution is deliberately limited to the exact cataloged target grid:
neither location inference nor extrapolation is permitted. These regional
forecasts are insufficient to establish a minimum wattage by themselves.

The optional readiness CLI inputs expose both the C3 attempt-link audit and
the C4 regional-as-of join under separate output keys to prevent mixing
retrospective and prospective evidence. Even when a regional join is valid,
the learned-power readiness remains COLLECTING until independently validated
holdout calibration and a real bounded 20 W control-vs-lower-power trial exist.

### Readiness unit path validation

The candidate timer's service now loads three explicit data-source paths from
a root-managed `/etc/rolling-thunder-forge-ft8-readiness/paths.env` instead
of embedding an unverified C4 SQLite filename. See
`deploy/systemd/forge-ft8-readiness.paths.env.example`. Its
`ConditionPathExists` requires both policy and paths configuration. The
non-networked dynamic service account has a supplemental C3 read group but
should not be started until operators verify actual C3/C4 database paths,
directory traversal permissions, SELinux/AppArmor if applicable, SQLite
WAL read access, and the isolated status-state directory in a staging run.
No live unit was installed or activated in this branch.
