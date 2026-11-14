# STAB-07C — Independent running-code identity: evidence and fail-closed design

**Status: OFFLINE SOURCE / NO-GO for production** (2026-11-14).
No application, service, file permission, sudoers, database, radio or host change
has been performed. Uses Desktop Commander; SpiffBridge remains optional and
is not needed for development or diagnostics.

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

The reported state is explicitly **artifact/process path binding**, NOT proof
of independently verified Python modules in memory. A process may have loaded
modules before a disk check, may load dynamically, or may be executing a code
object not reconstructable by hashing disk. The report's
`loaded_python_bytes_independently_proven` remains **false** and its release
disposition stays `blocked_manual_review`, even with all checks green.
The independent command-line verifier always exits with **status 75** (refused) even when protected artifact and process paths bind successfully; no caller may treat static artifact identity as release acceptance.

This protects against falsely accepting mutable checkout HEAD, duplicate
identity, missing manifests, altered source or untrusted paths. It does not
make the current running service satisfy the new model and does not provide a
magic independent assertion of in-memory code. In particular, a root-generated
manifest is trusted only as an installation artifact; the precise build must
also be independently tied to a reviewed Git SHA through a reproducible,
cryptographically verified release process.

## Reconciliation integration and hazard control

The separate read-only `deploy/rolling-thunder-recovery-inspect.py` now always
reports `runtime_code_identity.loaded_python_bytes_independently_proven=false`
for an unverified live runtime. The signed reconciliation executor now refuses
a report without independent proof **before** accepting any approval receipt.
An approved and signed human boolean is not sufficient proof of executing
bytes. Existing tests that exercise the *downstream* approval path inject a
synthetic positive evidence source; live inspection deliberately cannot do so.
No new autorollback, journal-clearing, service command, CAT/PTT or radio control
path was introduced.

## Remaining acceptance design and sequence

- Specify and independently test a reproducible, root-controlled protected
  release build from a pinned exact commit, including dependencies and native
  extensions, startup bootstrap and release signature. Avoid mutable editable
  installs or adding two competing launcher instances. Review service restart,
  full rollback, source/venv integrity and permission boundary.
- Produce a trustworthy runtime launch attestation bound to the *exact process
  instance* (PID plus boot ID and start ticks), release content, launch-time
  verified hashes and reliable audit history. A secure exec-to-Python handoff
  and dynamic module integrity strategy must be justified; do not simply
  trust arbitrary process-generated JSON, environment values or Git HEAD.
- Independently cross-check the running process with the protected launch
  provenance, current artifact hashes, systemd MainPID/cgroup, Tk heartbeat and
  startup audit. Protect against PID reuse, code replaced after startup,
  symlink/path swaps, compromised verifier and unsigned claims. Treat failed
  or partial proof as `unverified` and preserve the blocked transaction.
- Integrate the independent source with reconciliation only once its trust
  boundary and real parked tests are accepted. No current verifier reports
  `loaded_python_bytes_independently_proven=true` in production.
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
identity, launched process path/cgroup binding, mismatch SHA, writable and
symlinked source, untracked Python and virtualenv files, missing manifest,
wrong cwd, PID, cgroup, entrypoint and nonisolated interpreter. Crucially a
successful protected artifact binding still reports loaded-code proof FALSE.
`tests/test_recovery_reconciliation.py` covers refusal to attest an incomplete
runtime identity even when an approval is correctly signed.

2026-11-14: Added only offline read-only evidence and conservative reconciliation
NO-GO enforcement. Rollback is revert of this draft code; no installed host
changes or runtime recovery actions occurred.
