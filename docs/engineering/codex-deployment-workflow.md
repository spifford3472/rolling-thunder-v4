# Codex Development and Deployment Workflow

## Purpose

This document defines the persistent Codex development environment on Forge and
the approved deployment paths for Rolling Thunder v4.

Codex performs development and automated testing in an isolated source
workspace. Production deployment remains an explicit owner-approved action.

## Development Workspace

Persistent Forge development workspace:

    /home/geoff/projects/rolling-thunder-codex

Repository:

    git@github.com:spifford3472/rolling-thunder-v4.git

Codex must not perform normal development inside production runtime
directories.

Before beginning new work:

1. fetch current GitHub state;
2. verify the working tree is clean;
3. start from current `origin/main` unless continuing an explicitly named branch;
4. create a focused feature/fix/docs branch;
5. make the smallest change that satisfies the assigned task;
6. run relevant targeted tests during development;
7. run repository-standard quality gates before completion where practical;
8. commit and push the feature branch when ready for review;
9. report the branch, exact SHA, tests, status, risks, deployment status, and
   merge status.

Never push directly to `main`.

Never merge without explicit repository-owner approval.

Never deploy without explicit repository-owner approval.

Merge approval and deployment approval are separate decisions.

## Forge Deployment

Approved command:

    sudo -n /usr/local/sbin/rolling-thunder-forge-deploy <component> <EXACT_40_CHAR_GIT_SHA>

Allowed components:

    contact-sync
    callsign-info
    spots

The target SHA must be an exact 40-character commit available on a pushed
origin branch.

The wrapper is expected to perform component-specific validation, database backup, package or
checkout installation, service restart, health validation, deployment-state
tracking, and rollback handling.

### contact-sync

Service:

    rolling-thunder-forge-contact-sync.service

Health:

    http://192.168.9.170:8767/health

Healthy state requires:

    availability == "available"

### callsign-info

Service:

    rolling-thunder-forge-callsign-info.service

Health:

    http://192.168.9.170:8788/health

Healthy state requires:

    status == "healthy"

### spots

Service:

    rolling-thunder-forge-spots.service

Health:

    http://192.168.9.170:8766/api/v1/health

Healthy deployment requires:

    service_status == "healthy"
    dx_connection.state == "live"

The spots service owns the persistent DX Summit IRC connection.

Do not restart, reinstall, or otherwise disturb spots while deploying another
Forge component. Do not deploy spots unless the assigned change actually
requires a spots deployment or the repository owner explicitly authorizes it.

## anvilmobile Deployment

Approved Forge-to-anvilmobile command:

    ssh -i /home/geoff/.ssh/rolling_thunder_deploy \
      -o IdentitiesOnly=yes \
      -o BatchMode=yes \
      rollingdeploy@anvilmobile \
      'sudo -n /usr/local/sbin/rolling-thunder-deploy <EXACT_40_CHAR_GIT_SHA>'

The dedicated SSH key is constrained by a forced command on anvilmobile.

Do not use the operator's ordinary SSH account to bypass the deployment gate.

Do not manually copy code into the anvilmobile production checkout.

The anvilmobile deployment wrapper is expected to validate the requested pushed SHA, backs up
the production database, checks out the exact requested commit, refreshes the
editable install, runs database initialization/migrations, verifies database
integrity, restarts the Rolling Thunder service, and performs rollback on
failure.

## Production Verification

After an explicitly approved deployment:

1. verify the exact intended SHA;
2. verify only the intended component/service was affected;
3. verify systemd reports the service active;
4. verify the component health endpoint;
5. perform relevant application/operator acceptance;
6. report the exact deployed SHA;
7. report rollback readiness or any rollback event.

A successful deployment test does not authorize a merge.

## RF Safety

Rolling Thunder controls real amateur-radio equipment.

Do not initiate live RF merely as an automated software test.

When RF transmission is required for acceptance testing, Geoffrey must
explicitly authorize it.

Prefer, in order where appropriate:

- unit tests and deterministic mocks;
- recorded data;
- receive-only validation;
- dummy-load testing;
- explicitly authorized live-air testing.

Existing CAT/PTT/transmit interlocks must fail closed and must not be weakened
as part of unrelated work.

## Current component limitations

The generic Forge wrapper documents contact-sync, callsign-info and spots only.
Newer PSK Reporter, propagation and FT8 intelligence services have separate
release gates and must **not** be deployed using an undocumented component
argument or inferred wrapper support. Check the deployed wrapper and the
service-specific rollout instructions before any authorized cutover.

An approved merge is not approval to deploy. A CI pass does not replace
operator acceptance or authorize live RF.
