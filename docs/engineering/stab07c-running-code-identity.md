# STAB-07C — Historical running-code identity investigation

**Status: OFFLINE SOURCE / NO-GO for production** (2026-11-14).
No application, service, file permission, sudoers, database, radio or host change
has been performed. Uses Desktop Commander; SpiffBridge remains optional and
is not needed for development or diagnostics.

**Current source disposition (2026-11-17):** the design below is historical.
`stab07m-process-bound-runtime-identity.md` implements protected-release file,
executable and command-path checks plus a Tk heartbeat bound to PID, boot ID,
process start ticks and release SHA. It leaves
`loaded_python_bytes_independently_proven=false` and reports only
`protected_release_process_identity_verified`. The current mutable-checkout Pi
process cannot pass, and no protected-release launcher has been installed;
production identity and full release remain NO GO.

## Real AnvilMobile evidence (read-only)

The system manager reported active MainPID `60400`. `/proc/60400/exe`
resolved to `/usr/bin/python3.13`; its `cwd` was
`/home/geoff/projects/rolling-thunder-v4` and the command line invoked
`/home/geoff/projects/rolling-thunder-v4/.venv/bin/python` with
`/home/geoff/projects/rolling-thunder-v4/.venv/bin/rolling-thunder-ui`.
Git HEAD was `ba58b0b2a3b9b10b73dcdcb1ee046528f79b6d62`, but the source tree,
virtual environment and checkout are owned by `geoff` with mode `0775`.
There is no `/opt/rolling-thunder/releases/` pinned release directory.

**Conclusion:** HEAD, PID/cgroup, cwd, command line and Tk heartbeat do NOT
prove which `.py` or `.pyc` bytes that interpreter has imported. Editing a
mutable checkout does not change HEAD and may leave previously imported
modules in the process. Reporting runtime loaded-code identity as verified on
these observations would be unsafe. The current release remains **NO GO**.

## Implemented offline independent evidence component

`deploy/rolling-thunder-runtime-identity.py` provides a read-only independent
process-to-artifact verifier, separate from the application and from the
signed-approval issuer. It is an uninstalled future capability requiring a
root-controlled release layout. It does NOT modify a running process or read
operator QSO data. To report `protected_release_and_process_path_bound`, it
requires *all* of the following:

1. An exact lowercase 40-hex Git SHA naming a release directory, equal to a
   protected `release-manifest.json` embedded in that release.
2. All path components root-owned, non-symlink and not group/world-writable.
   Full inventory and SHA256 agreement for every file beneath `src/`, `.venv/`
   and `deploy/`, plus tracked manifest entrypoint metadata. Missing, extra,
   unexpectedly writable or symlinked files cause refusal. Hashing and
   directory traversal have bounded per-file and aggregate limits.
3. System-level `rolling-thunder.service` active under `geoff`; expected
   MainPID user ownership and exact cgroup, `/proc/PID/cwd` bound to that
   protected release directory, plus an exact four-argument launch command:
   `<release>/.venv/bin/python -I -B <release>/.venv/bin/rolling-thunder-ui`.
   Python `-I` disables user site and environment injection and `-B` disables
   bytecode writes. No fallback accepts current editable launch semantics.

At the time of this historical investigation, the reported state was
**artifact/process path binding**, NOT proof of independently verified Python modules in memory. A process may have loaded
modules before a disk check, may load dynamically, or may be executing a code
object not reconstructable by hashing disk. The report's
`loaded_python_bytes_independently_proven` remains **false**. The current
verifier now exits successfully only after the protected release, live process
instance and fresh matching Tk heartbeat all pass; this does not claim to read
Python objects from memory. See STAB-07M for its current contract.

This protects against falsely accepting mutable checkout HEAD, duplicate
identity, missing manifests, altered source or untrusted paths. It does not
make the current running service satisfy the new model and does not provide a
magic independent assertion of in-memory code. In particular, a root-generated
manifest is trusted only as an installation artifact; the precise build must
also be independently tied to a reviewed Git SHA through a reproducible,
cryptographically verified release process.

## Reconciliation integration and hazard control

The separate read-only `deploy/rolling-thunder-recovery-inspect.py` reports
`loaded_python_bytes_independently_proven=false` and requires the explicit
protected-release/process identity result. Signed reconciliation refuses an
unverified mutable checkout before accepting an approval receipt. A signed
owner approval cannot substitute for process evidence. Tests that exercise the
downstream approval path inject synthetic positive evidence; live inspection
does not accept that fixture or a mutable checkout.
No new autorollback, journal-clearing, service command, CAT/PTT or radio control
path was introduced.

## Remaining acceptance design and sequence

- Build and review a protected release installer/service integration for the
  Pi's existing OS baseline. The mutable-checkout deployment candidate is not
  sufficient and has not been replaced or installed.
- Confirm that the privileged release builder binds the complete protected
  manifest to the reviewed exact commit and pinned application environment.
  The process verifier checks installed bytes but does not by itself prove the
  manifest's creation provenance.
- Perform separately authorized parked installation/rollback and verify the
  process-bound Tk heartbeat on AnvilMobile. The source verifier remains
  offline-only until then.
- Require owner-approved read-only inspection of original installed wrapper
  hash and protected FT8 drop-in; consistent parked SQLite/WAL snapshot and
  QSO preservation; independent physical PTT de-key verification; signed owner
  authorization issuer; full regression and GitHub CI at exact final SHA.
- Any later privileged installation or infrastructure change requires
  an approved and committed record in
  `spifford3472/ki5vnb-qth-infrastructure` with file paths, integrations,
  permissions, jobs, validation, rollback and change history. It is not done
  in STAB-07C.

## Deterministic tests

`tests/test_runtime_release_identity.py` covers protected source and manifest
identity, executable/command path, PID/boot/start ticks, matching Tk heartbeat,
and malformed or wrong-process evidence. A successful result still reports
loaded-code proof FALSE. See STAB-07M for current offline coverage.

2026-11-14: Added only offline read-only evidence and conservative reconciliation
NO-GO enforcement. Rollback is revert of this draft code; no installed host
changes or runtime recovery actions occurred.

## STAB-07D continuation (2026-11-14)

A reproducible **source-only** archive builder and an independent signed process-start observation verifier have been built offline. Neither includes pinned Pi wheels, protected host installation, trusted launch observer, or actual imported Python bytecode proof. The inspector/reconciler must continue to fail closed. See `stab07d-protected-release-and-launch-witness.md`.
