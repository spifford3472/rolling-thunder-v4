# STAB-07D — Reproducible source candidate and signed launch observation

**Status:** OFFLINE CANDIDATE; production **NO GO** (2026-11-14). No privileged
installation, production Git change, restart, database operation, radio command,
or RF test. Engineering uses Desktop Commander; SpiffBridge is not required.

## What was actually built

`deploy/rolling-thunder-release-build.py` reads an exact lowercase 40-character
Git commit exclusively from its Git blob tree, not the mutable worktree. It
requires source entry points (`pyproject.toml`, `src/rolling_thunder/ui_main.py`,
`deploy/rolling-thunder-autostart`) and allowlists `src/`, `deploy/`,
`pyproject.toml` and `README.md`. It refuses symbolic links, submodule entries,
invalid/ambiguous paths, missing entrypoints and oversized objects. It excludes
`config/`, live SQLite, secrets, local user settings and `.venv`.

Output is a deterministic tar containing a canonical `source-manifest.json`
with exact Git SHA, file names and SHA-256 digests. Entries have sorted names,
normalized UID/GID/mtime and file modes; it is a **source-only candidate** with
`dependencies_pinned=false` and `runtime_proven=false`. It makes no attempt to
install dependencies, initialize a venv, sign itself or alter a host. Tar
header metadata and layout are reproducible for the same tested tool/runtime;
reproduction on an independently built environment remains to be verified.

On isolated Forge, the real repository commit
`3806f7bfabb58622c2793207ab6f273a646e3320` produced a 20-MB-class source
candidate twice. Byte-for-byte comparison passed and both had SHA-256:
`a87bb46e08bdb1543af6f60e34aa16f1a44de7bb0a720ea3b2dce3b808a141bf`.
These local `/tmp/rt-stab07d-source-*.tar` artifacts are NOT installed or
approved as production releases; the runtime remains on its existing SHA.

## Signed launch-observation verification contract

`deploy/rolling-thunder-launch-witness.py` independently verifies a detached
Ed25519 signature on canonical JSON from a **future trusted observer**. The
public key would be independently provisioned and root-controlled at
`/etc/rolling-thunder/launch-witness-ed25519.pub`; the signing private key must
never be placed in this repo, on AnvilMobile, or in ChatGPT output. Signed fields
include project `spifford3472/rolling-thunder-v4`, host `anvilmobile`, system
service `rolling-thunder.service`, exact release SHA, boot ID, PID, process
start ticks and observation UTC time. The verifier requires private regular
witness files, trusted public-key ownership, valid signature, recognized scope,
current matching kernel boot ID and exact PID-start-tick identity. Stale (>24 h),
future, tampered, unsigned, wrong-key, wrong-boot or reused-PID witnesses fail
closed. Signature verification uses OpenSSL 3 with memory-backed descriptors.

A verified observation establishes *the signing authority's report* about a
particular live process start. It does not by itself prove that the authority
actually observed a trusted exec, that the process has not modified its runtime,
or that imported Python code matches a protected artifact. Therefore even a
valid signature returns only
`signed_launch_observation_bound_to_live_process`, with
`loaded_python_bytes_independently_proven=false`,
`disposition=blocked_manual_review` and a nonzero command exit. The trusted
observer, secure signing/key rotation, audit retention, cryptographic binding
to a complete protected release and actual launch-time code evidence **do not
exist** as installed capabilities. Reconciliation remains fail-closed.

## Why this is not a finished protected release

- The repository has no independently accepted fully hash-pinned dependency
  lock/wheelhouse for the target Pi runtime. A deterministic source archive
  alone is insufficient to reproduce the virtual environment, native modules,
  or exact interpreter.
- A root-owned, protected, immutable release directory has **not** been built
  or staged on AnvilMobile. No systemd unit points at a protected release.
- The existing `rolling-thunder-runtime-identity.py` expects an actual
  release with a fully enumerated `.venv`, protected source and process path.
  The source candidate intentionally cannot pass those production checks.
- A trustworthy process launch provenance path must bind code hashes,
  interpreter and dynamically loaded modules to the kernel process identity,
  not merely sign an unverified operator statement. A signed launch observation
  is necessary supporting evidence, not sufficient in-memory code proof.
- Converting the existing `-I -B` proposed Python launch into an actual safe
  entrypoint requires ensuring the source package is installed non-editably
  and its import paths do not depend on uncontrolled PYTHONPATH or user-site
  packages; it has not been attempted on the Pi.
- Source manifests are unsigned here. Authenticity requires separate signed
  release provenance linked to reviewed Git commit, dependency lock and
  independent trusted key distribution before any privileged install.
- Protected FT8 drop-in and root deployment wrapper still need owner-authorized
  on-device comparison; an active SQLite WAL requires a parked consistent
  snapshot; physical PTT de-key must be independently observed.

## Offline tests and failure semantics

`tests/test_protected_release_build.py` tests exact blob extraction,
byte-for-byte deterministic archives, worktree mutation immunity, secrets
excluded, invalid SHA, tracked symlink refusal and changed commit inventory.
`tests/test_launch_witness.py` tests real disposable Ed25519 signatures, boot
identity, start ticks, PID reuse, malformed/expired/future evidence, wrong
project, host, SHA, forged/unsafe key, unsafe receipt and refusal without
in-memory proof. Tests do not contact Pi devices or require root.

## Proposed next acceptance sequence (all subject to separate owner approval)

1. Lock Python, wheel and native dependencies for actual Pi architecture and
   interpreter with hashes and verified vendor provenance; establish repeatable
   isolated installation and second-host reproducibility tests.
2. Build a complete signed root-owned pinned release image in a staging
   environment; validate exact file inventory, sources, venv/ELF/native wheels,
   permissions, read-only operational config and data separation.
3. Create and independently security-review an on-device privileged trusted
   observer whose signing key is isolated from the dashboard process and whose
   evidence spans exact artifact hashes, exec/boot ID/start ticks and audit log.
   Do not use the current unsigned operator or dashboard self-report as proof.
4. Exercise start/stop/rollback with no radio hardware in isolated tests, then
   require an explicitly approved parked validation of systemd, SQLite/WAL,
   operator UI, CAT/PTT and physically confirmed receive state.
5. Obtain separate approvals for merges, privileged installation, exact-SHA
   production deployment/restart, and RF. Document all real infrastructure
   modifications in private `spifford3472/ki5vnb-qth-infrastructure` with
   configuration paths, integrations, jobs, validation, rollback and history
   before considering work complete.

**Rollback:** discard this offline draft and local source archives. No production
installation or service state was modified; there is nothing to roll back on
AnvilMobile. Change history: 2026-11-14, initial source archive/witness candidate
and deterministic tests added. Do not misstate this as completed in-memory
runtime attestation.
