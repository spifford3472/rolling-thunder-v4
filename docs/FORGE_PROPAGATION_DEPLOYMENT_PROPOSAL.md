# Forge Propagation Exact-SHA Deployment Integration

## Verified dispatcher boundary

This repository does not install or modify the root-owned
`/usr/local/sbin/rolling-thunder-forge-deploy`. Its source was inspected separately
and transcribed for this adaptation. The verified public interface is:

```text
rolling-thunder-forge-deploy <component> <40-lowercase-hex-sha>
```

The helper defines `SOURCE_REPO=/opt/rolling-thunder-forge-callsign-info` and
`SPOTS_REPO=/opt/rolling-thunder-forge`, runs Git operations through
`run_as_geoff`, and uses `verify_remote_sha REPO SHA` to require that the commit is
contained in a pushed remote branch. Its existing `contact-sync`, `callsign-info`,
and `spots` branches share later `STATE_FILE`, virtualenv, database, health-wait,
stop, backup, and rollback behavior.

Propagation must not enter that legacy shared path. The insertion fragment in
`deploy/rolling-thunder-forge-deploy-propagation-dispatch.example` belongs
immediately after the helper's existing exact-SHA syntax validation and immediately
before its `STATE_FILE` prerequisite or other legacy deployment logic. It fetches
`origin` in `SOURCE_REPO` through `run_as_geoff`, calls the existing
`verify_remote_sha`, and `exec`s the dedicated propagation-only root hook. The
three existing branches remain textually and semantically unchanged.

## Isolated component boundary

The early propagation branch executes:

```text
/usr/local/libexec/rolling-thunder-forge-deploy-propagation EXACT_40_SHA
```

The staged component hook independently validates the SHA and confines installation
to the propagation component. It does not accept a branch, tag, abbreviated SHA,
path, service name, account name, option, or arbitrary command.

The root-owned staging contract is:

```text
/var/lib/rolling-thunder-forge-deploy/propagation/<40-lowercase-hex-sha>/
  COMMIT_SHA
  wheelhouse/
    SHA256SUMS
    rolling_thunder-<version>-<tags>.whl
    <all reviewed dependency wheels>
```

`COMMIT_SHA` contains exactly the requested SHA plus a newline. `SHA256SUMS` covers
every wheel. The component hook requires the staging directories and all descendants
to be root-owned, non-symlink, and not group/world writable before checking the
manifest. The unprivileged preparation tool builds from `git archive` of the exact
pushed commit, never from the working tree. It writes a separate review artifact,
not the privileged tree. After review and checksum verification, an authorized
operator promotes those exact bytes into a newly created root-owned directory and
verifies them again. The old `release-candidate/20261008/wheelhouse` was built from
uncommitted content and is ineligible; its presence is not commit provenance.

The hook creates an immutable release at:

```text
/opt/rolling-thunder-forge-propagation/releases/<40-sha>
```

It reserves that final SHA path before creating the virtualenv and installs only from
the staged wheelhouse with `pip --no-index`; pip-generated launchers therefore name
the final path and are never relocated from a temporary directory. It records the SHA
and runs the installed propagation launcher with provider-free `--help` validation as
the dedicated service identity before atomically changing the relative `current`
symlink. An existing immutable release is validated the same way and fails closed
without changing `current` when broken. A failed new install/validation removes only
the newly reserved SHA directory. The systemd unit and Phase 1 rollout helper resolve
the executable through `current`. If the dedicated service was active, only
`rolling-thunder-forge-propagation.service` is restarted. A failed restart restores
the prior link when one existed and attempts to restart that prior release. An
inactive service remains inactive.

The hook does not install or edit systemd units, configuration, sysusers definitions,
state databases, credentials, firewall rules, timers, or any other service. Those
privileged Phase 1 assets remain a separate, manual, disabled-by-default install.

## Privilege and path model

| Actor or path | Required privilege/ownership | Purpose |
| --- | --- | --- |
| Existing central dispatcher | existing root-owned `0750` policy, one reviewed early branch | exact-SHA syntax, pushed-origin validation, dispatch |
| Component hook | `root:root 0750` under `/usr/local/libexec` | immutable release install and isolated service restart |
| Staging tree | `root:root`, no group/world write | trusted offline wheel input for one exact SHA |
| Application/release roots | `root:rolling-thunder-propagation 0750` | code readable/executable but not writable by runtime account |
| `current` symlink | root-managed | atomic selection of one immutable release |
| Runtime account | `rolling-thunder-propagation`, dedicated primary group, home `/var/lib/rolling-thunder-forge-propagation`, shell `/usr/sbin/nologin` | run only the propagation collector |
| Config | `root:rolling-thunder-propagation 0640` under `/etc/rolling-thunder-forge-propagation` | persistent operator-reviewed settings, never overwritten by code deploy |
| State | runtime-account-owned `0750` under `/var/lib/rolling-thunder-forge-propagation` | dedicated SQLite state only |

The runtime identity receives no root command, shell, write access to code, or access
to spot/contact-sync paths. The root hook deliberately has no component selector,
which prevents caller-controlled service or destination selection.

## Review, preparation, and integration procedure

These steps are for an authorized operator after the reviewed changes have been
committed and pushed. Set `SHA` to that exact commit; never use the current
uncommitted review wheelhouse.

1. Record the installed helper hash, owner, mode, and a recoverable root-owned backup.
   Compare the current installed source with the previously inspected transcription;
   stop on any difference that changes the insertion context or named functions.
2. Review the component hook, insertion fragment, preparation tool, unit, Phase 1
   rollout helper, tests, and complete Git diff at `SHA`.
3. From the exact checkout, run the unprivileged preparation dry run and build:

   ```bash
   SHA=<approved-40-character-lowercase-commit>
   ARTIFACT_ROOT="$(mktemp -d)"
   deploy/prepare-forge-propagation-stage dry-run "${SHA}" "${ARTIFACT_ROOT}"
   deploy/prepare-forge-propagation-stage build "${SHA}" "${ARTIFACT_ROOT}"
   test "$(cat "${ARTIFACT_ROOT}/${SHA}/COMMIT_SHA")" = "${SHA}"
   (cd "${ARTIFACT_ROOT}/${SHA}/wheelhouse" && \
     sha256sum --check --strict SHA256SUMS)
   MANIFEST_SHA256="$(sha256sum \
     "${ARTIFACT_ROOT}/${SHA}/wheelhouse/SHA256SUMS" | awk '{print $1}')"
   ```

   The tool fetches `origin`, requires the commit in a fetched origin branch, exports
   the commit with `git archive`, builds a fresh complete wheelhouse, and manifests
   every wheel. It refuses root execution and refuses to replace an artifact.
4. In a privileged review session, apply only the insertion fragment at its documented
   location. Do not replace the helper and do not edit its three existing component
   branches. Syntax-check the candidate, compare those branches byte-for-byte with
   the backup, then atomically install it while retaining the backup.
5. Install the reviewed component hook as
   `/usr/local/libexec/rolling-thunder-forge-deploy-propagation`, `root:root 0750`.
6. Install the separately reviewed Phase 1 sysusers, unit, configuration, rollout,
   and directory assets from `docs/PROPAGATION_HISTORY.md`. Keep the configuration
   disabled and the unit stopped.
7. Promote the reviewed artifact into a new root-owned stage; do not copy from the
   old wheelhouse and do not overwrite an existing SHA directory:

   ```bash
   sudo install -d -o root -g root -m 0755 \
     /var/lib/rolling-thunder-forge-deploy/propagation
   test ! -e "/var/lib/rolling-thunder-forge-deploy/propagation/${SHA}"
   sudo install -d -o root -g root -m 0755 \
     "/var/lib/rolling-thunder-forge-deploy/propagation/${SHA}" \
     "/var/lib/rolling-thunder-forge-deploy/propagation/${SHA}/wheelhouse"
   sudo install -o root -g root -m 0644 \
     "${ARTIFACT_ROOT}/${SHA}/COMMIT_SHA" \
     "/var/lib/rolling-thunder-forge-deploy/propagation/${SHA}/COMMIT_SHA"
   sudo find "${ARTIFACT_ROOT}/${SHA}/wheelhouse" -maxdepth 1 -type f -name '*.whl' \
     -exec install -o root -g root -m 0644 -t \
     "/var/lib/rolling-thunder-forge-deploy/propagation/${SHA}/wheelhouse" -- {} +
   sudo install -o root -g root -m 0644 \
     "${ARTIFACT_ROOT}/${SHA}/wheelhouse/SHA256SUMS" \
     "/var/lib/rolling-thunder-forge-deploy/propagation/${SHA}/wheelhouse/SHA256SUMS"
   test "$(sudo sha256sum \
     "/var/lib/rolling-thunder-forge-deploy/propagation/${SHA}/wheelhouse/SHA256SUMS" \
     | awk '{print $1}')" = "${MANIFEST_SHA256}"
   sudo sh -c 'cd "$1" && sha256sum --check --strict SHA256SUMS' sh \
     "/var/lib/rolling-thunder-forge-deploy/propagation/${SHA}/wheelhouse"
   ```

   The separately recorded manifest hash detects a user-writable artifact changing
   between review and promotion. If promotion fails before deployment, remove only
   the newly created `${SHA}` stage after confirming the literal path; no current
   release was changed.
8. Exercise invalid, abbreviated, option-like, uppercase, extra-argument, and
   unknown-component inputs before the first valid deployment.
9. Deploy the exact SHA, confirm `current` and its `COMMIT_SHA`, run the provider-free
   Phase 1 dry run, and verify that spot, contact-sync, Pi, Wavelog, and radio services
   have neither restarted nor changed.
10. Record the central helper's before/after hashes, deployed SHA, wheel manifest,
    unit/config/helper hashes, prior/current symlink targets, service enabled/active
    state, and rollback result.

Activation and provider smoke testing remain separate explicit actions in
`docs/PROPAGATION_HISTORY.md`; code deployment grants neither network approval nor
activation approval.

## Rollback

Before first deployment, restoring the recorded helper backup removes only the new
dispatcher branch. After deployment, code rollback is an ordinary deployment of the
previous exact pushed 40-SHA, with its own separately built and promoted stage. That
changes only the propagation `current` link. The hook restarts the propagation unit
only if it was already active.

For service rollback, use the existing propagation rollout helper's `deactivate`
action and restore `enabled: false`. Preserve the dedicated database. Removing old
release directories is deliberately outside this hook and requires a separately
reviewed retention procedure.

An already-created release whose launcher refers to a removed `.incoming` path is
not repaired or replaced in place. Follow
`FORGE_PROPAGATION_BROKEN_RELEASE_RECOVERY.md` to preserve it, install the corrected
hook, and deploy a fresh reviewed exact SHA without provider access.

## What is safe now

It is safe in the unprivileged repository workspace to review, lint, syntax-check,
test, dry-run, and build a fresh exact-commit review artifact after the commit is
pushed. This repository work performs no privileged install, production edit,
deployment, service restart, provider request, or activation.
