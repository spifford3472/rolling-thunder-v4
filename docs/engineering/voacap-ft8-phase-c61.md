# C6.1 — Forge baseline sampler safe commissioning candidate

Release source: C6 merged PR #316, main SHA `d78c74bb4132be09a14a646d24860a366416ff67`.
This increment adds an offline, exact-SHA stage packager and a narrowly scoped
root-owned C4 sampler installer. It is **not** the forecast-provider activation.

Installer prerequisites:
- reviewed, root-owned 0700 component stage under
  `/var/lib/rolling-thunder-forge-deploy/staging/voacap-baseline/<SHA>`
  containing checksum-verified wheels, component identity, service/timer files;
- root-owned `/etc/rolling-thunder-forge-voacap-baseline/config.json`
  with `process_enabled=false`, `scheduler_enabled=false`,
  `provider_enabled=false`, and exact C4 database path;
- system account `rolling-thunder-propagation` with existing C4 database
  ownership; complete standalone wheel install, accessible venv permissions;
- no existing deployed C4 sampler release; separate update/rollback review
  required to replace one;
- preserved C3, C5.4 readiness, provider and Pi state.

Use `deploy/scripts/stage-forge-voacap-baseline.sh` (with pinned SHA
from a published origin branch, local offline dependency wheelhouse and fresh
staging destination). Administrator copies/verifies into the root-owned
private staging namespace, reviews the script and runs
`deploy/scripts/install-forge-voacap-baseline.sh <SHA> <ROOT_STAGE>`
from a trusted root-owned location. The installer stages release and
systemd units, runs one OFF-mode cycle, enables the 6-hour timer, reports
its backup directory and rolls back link/units on first-run failure.
It does not alter C3/C5.4 or send provider requests.

Next separate steps C6.2–C6.4:
1. Pin a small audited home-grid6 / target-grid4 inventory, solar SSN
   observation & capture timestamps, provider service 0.3.0/model version.
2. Verify the adapter's body and hour-band response contract using a fake
   local provider and no real network requests.
3. Obtain a limited first-provider-request operator authorization;
   use one slot, max one local POST, 10s timeout, documented rollback.
4. Only after observing a valid `ready` C4 future pre-choice slot should
   scheduler/provider gates and budget-limited 6-hour timer be authorized.

A green C6.1 installation is not scientific model qualification and never
authorizes learned wattage.
