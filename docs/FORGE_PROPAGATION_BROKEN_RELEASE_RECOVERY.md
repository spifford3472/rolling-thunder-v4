# Forge Propagation Broken-Release Recovery

## Scope

This runbook is for an authorized Forge administrator after a propagation release
was created with a console launcher that names a removed `.incoming` virtualenv.
The repaired hook fails closed when it encounters that immutable release: it runs
the installed launcher with `--help` as `rolling-thunder-propagation` before changing
`current`, so an unusable existing release cannot be selected.

Recovery is provider-free and affects only
`rolling-thunder-forge-propagation.service`. Do not modify the central dispatcher's
existing `contact-sync`, `callsign-info`, or `spots` branches. Do not start the
collector, enable it, run `--once`, or make a provider smoke request as part of this
procedure.

## Preferred recovery: deploy a new exact SHA

Preserve the broken release for diagnosis. Do not repair its launcher in place,
replace its virtualenv, delete it, or reuse its SHA.

1. Record the broken SHA, `readlink /opt/rolling-thunder-forge-propagation/current`,
   and the propagation unit's enabled/active state. Also record the component-hook
   hash and the broken launcher's first three lines. Do not inspect or change the
   other three services.
2. Review and install the corrected component hook using the ownership, mode, backup,
   and central-dispatcher safeguards in
   `FORGE_PROPAGATION_DEPLOYMENT_PROPOSAL.md`. The dispatcher adaptation and its
   three original branches remain unchanged.
3. Commit and push the reviewed repair as a new commit. Build, review, checksum, and
   promote a fresh stage for that new exact 40-character SHA. Never promote the old
   uncommitted wheelhouse.
4. Invoke the existing dispatcher for `propagation` and the new SHA. The hook creates
   the virtualenv directly at its final release path, validates the real pip-generated
   launcher under the service identity, and only then changes `current`. If validation
   fails, the newly created incomplete release is removed and `current` is unchanged.
5. Confirm that `current` and its `COMMIT_SHA` name the new SHA. Run the rollout
   helper's `dry-run`; this performs configuration/launcher checks without database
   or provider access. Confirm that the three original Forge services were neither
   restarted nor changed.
6. If the propagation unit was inactive, leave it inactive. If it was active, confirm
   that the isolated hook restarted only that unit and that it is healthy. Activation
   or network smoke testing still requires its separate explicit authorization.

The broken release may be removed only later under a separately reviewed retention
procedure. It must never be made current again.

## If no new reviewed SHA is ready

Stop. Leave `current` and the unit state unchanged; if the unit is already inactive,
keep it inactive. Do not bypass validation by manually repointing `current`, editing
the generated launcher, copying an interpreter, or changing the service unit. Prepare
the new reviewed SHA first, then use the preferred recovery above.
