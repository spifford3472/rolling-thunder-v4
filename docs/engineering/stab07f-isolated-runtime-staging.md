# STAB-07F — Isolated candidate stage, interpreter provenance and ARM64 blocker

**Status: offline, uninstalled engineering candidate / PRODUCTION NO GO.**
Recorded November 14, 2026. Desktop Commander is the operational connection;
SpiffBridge is not required. No GitHub PR merge, privileged install, service
start/stop, radio/CAT/PTT action, SQLite write or production host change occurred.

## Exact architecture and environment observed read-only

AnvilMobile remains Debian 13 `aarch64`, CPython 3.13.5, glibc 2.41.
`/usr/bin/python3.13` is root-owned and SHA256
`bd241b38381974ae27d7d5098a6d0e6dda0a744b5e9fdd6fe3a1ae632588961e`.
Read-only `dpkg-query` reported the selected interpreter and Python library
packages at `3.13.5-2+deb13u4`; system native libraries observed included
`libc6:arm64 2.41-12+rpt1+deb13u3`,
`libexpat1:arm64 2.7.1-2`, `libffi8:arm64 3.4.8-2`,
`libgcc-s1:arm64 14.2.0-19`, `libssl3t64:arm64 3.5.6-1~deb13u2+rpt1`,
and `zlib1g:arm64 1:1.3.dfsg+really1.3.1-1+b1`.

Those are **package/version observations, not a cryptographically complete
interpreter/stdlib/ELF runtime closure**. Full recursive OS-library hashes,
Python extension import behavior and native load/link validation are not proven.

Forge is `x86_64`/Python 3.12.3. No usable `qemu-aarch64`,
`qemu-aarch64-static`, `podman`, `debootstrap`, `mmdebstrap`, or `proot` was
available through Desktop Commander. Docker is installed but the restricted
account was denied access to its socket. No permission was broadened, no
emulator registered, and no environment was installed on AnvilMobile. Therefore
**actual native ARM64 execution, Tk/serial/BLE/Vosk imports and end-to-end
service startup were NOT tested**. This prevents claiming completion of the
full STAB-07F objective.

## Reproducible noneditable app wheel

Two isolated Forge source extractions from the STAB-07E exact-Git transport
archive (source SHA `96b96da934585269f5b2cf80ca3187d8675ebbaa`)
were used to build the *noneditable* application wheel twice with
`SOURCE_DATE_EPOCH=1700000000`, `PYTHONHASHSEED=0`, and `pip wheel --no-deps`.
Both builds produced `rolling_thunder-4.4.1-py3-none-any.whl`, SHA256
`e41205e240628ebed8ab658104710e411f5189a8cab92cbeb7ae75fd29517a31`.
This is a **wheel artifact**, not installed application imports on ARM64.
Build isolation fetched the Python build backend according to the project
requirements; that backend and its full supply-chain provenance are still
not independently locked or audited.

## Offline stage implementation and boundaries

`deploy/rolling-thunder-stage-candidate.py` is a standalone, noninstalled
read-only-to-production staging utility. It accepts an already-private
user-owned `0700` sandbox, exact Git SHA, exact SHA256 of the reviewed
STAB-07E transport tar, and SHA256 of the noneditable app wheel. It refuses
symlinks, unsafe roots, unbounded or malicious tar entries, extra/missing
components, invalid source manifest, wrong wheel bytes, untrusted app wheel
hash or executable import-path injection. Its staging workflow:

1. Hashes the entire transport blob against an explicit expected SHA256;
   verifies all transport component hashes, pinned wheel names, embedded wheel
   bytes, exact source manifest and app wheel digest without executing code.
2. Writes only under an existing private nonproduction scratch directory.
   Uses one private staging directory and file fsync before publishing.
3. Sets files `0400`, subdirectories `0500`, and atomically publishes with
   Linux `renameat2(RENAME_NOREPLACE)`; **even an existing empty release cannot
   be overwritten**. Unsupported no-replace implementations fail closed.
4. Emits a `staging-record.json` marking `production_ready=false`,
   `installed_venv=false`, `native_arm64_executed=false`,
   `os_interpreter_included=false`, `root_owned_production_release=false`,
   `signed_release=false` and
   `loaded_python_bytes_independently_proven=false`.
5. Exposes an independent `--verify-only` integrity path that re-hashes all
   staged files, checks inventory, private modes and missing/extra files,
   and refuses any falsely asserted production-ready status. A signature is
   still needed to establish authentic provenance; an attacker who controls
   the bundle, digest and staging root could forge a self-consistent record.

A stage is **owned by the unprivileged Forge user**, so permission bits alone
do not establish the stronger future root-controlled immutable release or
prevent the owner from deliberately changing permissions. A successful static
integrity check must never be interpreted as proof of loaded Python code.

On Forge, the real STAB-07E payload SHA256
`a8b984bd154e55158056874e8ebd852e1a6dd2bc534a689514537c4819d547c1`
plus the noneditable app-wheel SHA above were successfully staged in
`/home/rt-remote/workspaces/rt-stab07f-stage/96b96da934585269f5b2cf80ca3187d8675ebbaa`.
A second read-only verification checked **30 staged files**, without executing
any ARM64 code or modifying production. The candidate remains local to Forge;
no production installer path, system service, timer, key, port or network
integration was created.

## Rollback and failure model

- During stage preparation failures, temporary stage files are deleted; the
  previously published candidate is never replaced.
- An unexpected crash after atomic rename but before parent sync can leave a
  candidate needing manual verification; do not consider the stage accepted
  until independent `--verify-only` succeeds. No automated force-clear.
- Successful stages never replace an existing release, and no rollback is
  attempted against AnvilMobile, the active checkout, SQLite or any QSO.
- An owner may abandon the draft and separately remove disposable Forge
  scratch artifacts after inspection. This does not constitute a production
  rollback procedure.
- Malicious tar paths, wrong component digest, simulated altered app wheel,
  changed source manifest, unsafe staging permissions, existing target,
  missing staged file and fake approval state all fail closed.

## Remaining actions (explicitly uncompleted)

1. Establish a separately approved **isolated ARM64 executor**, e.g. a
   restricted QEMU/container/test Pi that cannot access live radio or station
   databases. Do not grant unrestricted Docker access or reconfigure binfmt
   merely to satisfy this check.
2. Create a truly isolated, noneditable CPython 3.13.5 ARM64 venv from the
   approved, SHA-pinned wheelhouse, install the app wheel without network,
   verify installed `RECORD` hashes and the 26-package dependency graph.
3. Run native imports for all required hardware/UI/speech modules with
   suitable fakes and no serial/radio/network connections; verify environment
   completeness, package ABI, dynamic loader and target OS library closure.
4. Sign complete release provenance using an independently controlled key;
   define, test and stage a **separately owner-approved** root-owned immutable
   release tree and pinned systemd launch/rollback with exact SHA.
5. Independently attest loaded Python bytes, then verify readiness and
   privileged owner authorization. Require parked QSO/WAL/FT8-PTT hardware
   acceptance and separately approved installation/deployment/RF operations.
6. Before any host/network infrastructure modification affecting the specified
   QTH networks, commit paths, integrations, job changes, validation, rollback
   and change history in private
   `spifford3472/ki5vnb-qth-infrastructure`. No such modification happened
   in this offline branch.

## Validation / change history

`tests/test_protected_candidate_stage.py` provides deterministic sandbox
regressions for no-replace atomic publication, payload/app hashing, source
manifest tampering, private modes, post-stage verification, missing files and
fake approval status. Existing source/runtime safety tests remain mandatory.

2026-11-14 — Added noneditable application wheel reproducibility, read-only
Pi OS package inventory, offline staging and verification code, tests and
this NO-GO release record. There is no production installation to undo.

## STAB-07G native execution follow-up (2026-11-14)

The earlier Forge ARM64 emulator availability blocker was resolved without Docker or host privilege changes. A private, networkless QEMU/user-namespace test system now successfully installs all 26 hashed wheels and the noneditable app wheel, imports 18 ARM64 native/UI modules, and passes a 2,213-file hash audit. This does **not** establish physical UI startup or immutable production deployment. See `stab07g-isolated-arm64-execution.md`.
