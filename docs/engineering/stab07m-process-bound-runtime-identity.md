# STAB-07M — Process-bound protected-release identity

Status: **source implementation and offline tests only; not installed on AnvilMobile**.

## Contract

The process identity verifier no longer requires the unachievable assertion
that Python code objects in memory have been independently reconstructed. It
checks a narrower, concrete chain:

1. The release directory is named by the expected 40-character commit SHA and
   is protected by root ownership, non-writable path components, and a complete
   SHA-256 manifest covering application source, virtual environment and deploy
   files.
2. The system service has exactly one expected dashboard process. Its user,
   cgroup, working directory, command line and resolved executable match the
   protected release's isolated `python -I -B` launch path.
3. The Tk callback heartbeat is private and fresh, and carries the same PID,
   kernel boot ID, `/proc/PID/stat` start ticks and release SHA observed by the
   verifier. A recycled PID or heartbeat from another process, boot, or release
   is refused.
4. Recovery reconciliation accepts only the explicit
   `protected_release_process_identity_verified` result and a SHA matching the
   journal's previous or target release. A signed approval cannot override a
   failed identity check.

The evidence is called **protected release/process identity**. It does not
claim to read Python code objects from memory or independently establish
physical radio receive/PTT release. The existing Tk status remains a software
responsiveness signal only.

## Legacy and production boundary

The current AnvilMobile mutable-checkout launch has no root-owned SHA release
directory and cannot pass these checks. The repository's existing deployment
candidate still installs into that checkout; it is not converted or installed
by this change. A separately reviewed protected-release installer/service
integration must produce a root-owned release, manifest, isolated copied
interpreter/venv and matching launch environment before the new verifier can
pass on the Pi. The checker does not auto-install, restart, switch service
paths, or change any production database/configuration.

The verifier hashes the installed venv and executable files. It does not
reconstruct the complete Raspberry Pi OS or authenticate every base OS package.
Any app-only deployment must separately record acceptance of the installed
Raspberry Pi OS baseline and ensure the protected application environment does
not replace system libraries. A full OS image rebuild retains the separate
native-package provenance gates. Intel/x86_64 is outside this current target.

## Deterministic coverage

- `tests/test_runtime_release_identity.py`: protected inventory, exact process
  launch, executable path, process-instance heartbeat, stale/mismatched
  heartbeat, wrong release, malformed or writable files, and CLI disposition.
- `tests/test_ui_deployment_readiness.py`: Tk callback freshness and rejection
  of recycled PID/start-time or boot-mismatched heartbeat evidence.
- `tests/test_recovery_process_identity.py`: recovery inspector validates boot
  ID and process start ticks along with service/cgroup singleton state.
- `tests/test_recovery_reconciliation.py`: reconciliation refuses a missing or
  mismatched protected process identity even when the approval is signed.

All tests use disposable procfs and release fixtures; no Pi, radio, Forge,
network, root installation, SQLite mutation, CAT/PTT or RF is needed.

## Remaining acceptance steps

1. Review the protected-release installer and systemd launch integration as a
   separate change; verify rollback preserves the prior release and data.
2. Obtain owner-authorized installed wrapper/unit/drop-in inspection and record
   the exact protected release and process-bound heartbeat on AnvilMobile.
3. Verify the application against the accepted Pi OS baseline; perform the
   separately required parked GPS/receive-only and physical PTT checks.

Until those steps pass, exact installed runtime identity and full release
readiness remain **NO GO**. The operator can still clear the application
lockout; a system restart restores operator control. Neither software status
nor this identity verifier proves physical PTT release.
