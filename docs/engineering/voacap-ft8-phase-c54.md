# C5.4 Forge-only readiness service release and rollback candidate

This checkpoint supplies **separate, component-scoped** release tools, not a
modification to existing C3 worker, spots, contact-sync or Pi installers:

- `deploy/scripts/stage-forge-ft8-readiness.sh` packages an exact pushed Git
  commit into a pinned offline wheelhouse and validates source identity.
- `deploy/scripts/install-forge-ft8-readiness.sh` is a *proposed* root-owned
  admin-only helper. It requires an exact 40-character Git SHA, a root-owned
  mode-0700 stage under
  `/var/lib/rolling-thunder-forge-deploy/staging/ft8-readiness/`, checksum-
  verified offline wheels, a root-owned policy initially set to
  `mode: "off"`, and three reviewed C3/C4 SQLite source paths.
- `deploy/scripts/rollback-forge-ft8-readiness.sh` restores the prior
  readiness-only symlink and systemd units from an explicitly supplied
  root-owned private backup; it does not restart C3 or Pi.
- `deploy/systemd/rolling-thunder-forge-ft8-readiness.service` uses an
  isolated dynamic service identity with supplemental **read-only C3 and C4
  service groups**, no IP access, strict filesystem sandbox, isolated state
  directory and no radio/provider control.
- `rolling-thunder-forge-ft8-readiness-preflight` verifies the *actual* three
  source schemas and SQLite quick-integrity before enabling anything.

## The one-time administrator commissioning path

This is a proposed procedure for a **separately reviewed, approved** new
component, not authority to install files from a developer worktree.

1. After GitHub CI, code review and a merge, choose and pin the **exact main
   commit SHA**. Staging requires all dependency wheels locally, obtained
   through the existing approved offline wheelhouse process. Example:

   ```bash
   bash deploy/scripts/stage-forge-ft8-readiness.sh \
     /home/geoff/projects/rolling-thunder-v4-voacap-c54 \
     <EXACT_40_CHAR_APPROVED_SHA> \
     <REVIEWED_ABSOLUTE_DEPENDENCY_WHEELHOUSE> \
     /home/geoff/projects/ft8-readiness-stage-candidate
   ```

2. Root/admin reviews the SHA, script, checksum manifest and every wheel;
   copies the stage to a root-owned private directory under
   `/var/lib/rolling-thunder-forge-deploy/staging/ft8-readiness/`.
   Authorize and install the new component helper into a trusted, root-owned
   executable path. **Do not invoke a developer-writable deployment script as
   privileged code.**
3. Resolve the actual C3 inbox/history and C4 baseline database paths from
   protected service configurations. Put only these three reviewed paths in
   a root-owned `/etc/rolling-thunder-forge-ft8-readiness/paths.env`;
   install a root-owned `policy.yaml` with `mode: "off"`. Source
   directories must grant the dynamic service C3/C4 *read*, not write.
   Verify SQLite read-only/WAL behavior and avoid active source migrations.
4. Authorized administrator runs the reviewed root-owned exact-SHA helper.
   It builds a distinct root-owned release, preserves previous link/systemd
   units, validates the preflight, installs only readiness units, starts its
   15-minute timer and one non-actuating OFF-mode service run, and checks
   status inventory reads are available. On failure it rolls back the
   readiness service link/units. Record the printed backup path.
5. Reboot/suspend/source-unavailable acceptance: confirm the timer autostarts,
   status survives restarts, actual C3/QSO, POTA, spots, Wavelog and Pi remain
   unaffected. Verify no network provider calls or CAT/PTT. Manually test
   changing the YAML mode and restarting **only readiness**, and OFF/invalid
   config degradation. Retain the previous release and backup for rollback.

## What this explicitly does NOT complete

An installed readiness timer is NOT a calibrated power optimizer. Source
inventory counts alone cannot authorize a learned starting wattage.
C4 provider calls and historical baseline research sampling are still gated
and disabled; no experimental 15 W transmit assignments are enabled.
A production C3/C4 real-observation evaluation worker, calibration,
pre-registered randomized test cohort and reproducible certificate producer
must still be completed and approved. The existing data only support
retrospective explanations and limited regional as-of audits, not causal
lower-power proof. No code in this package has RF actuation authority.
See issue #312.
