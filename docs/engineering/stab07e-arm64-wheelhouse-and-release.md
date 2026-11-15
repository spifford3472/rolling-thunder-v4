# STAB-07E — Hash-pinned ARM64 wheelhouse and reproducible release transport

**Status:** offline development candidate, November 14, 2026. **PRODUCTION NO GO.**
No Rolling Thunder branch was merged. No file was installed or modified on
AnvilMobile, its service was not restarted, and no network, CAT/PTT, SQLite or
RF changes were made. Forge development used Desktop Commander; SpiffBridge is
not required.

## Target measured on AnvilMobile (read-only)

- Debian 13 `arm64`, `aarch64`, glibc 2.41; Python 3.13.5.
- Protected OS interpreter `/usr/bin/python3.13`: root:root mode 0755;
  SHA256 `bd241b38381974ae27d7d5098a6d0e6dda0a744b5e9fdd6fe3a1ae632588961e`.
- Installed OS packages `python3.13-minimal`, `python3.13`,
  `libpython3.13-minimal`, `libpython3.13-stdlib` and `libpython3.13`:
  version `3.13.5-2+deb13u4`.
- The interpreter's native dependencies include libc, libm, libz, libexpat,
  the dynamic loader, and OS-managed library packages. **Only the interpreter
  executable SHA was captured**, not the entire interpreter/std-lib/native
  system dependency closure. Those dependencies remain outside the payload.
- A read-only `pip freeze` from the existing geoff-writable editable venv
  established observed versions. Its unrelated developer packages and editable
  Git source are **not** copied into the release candidate. The target dependency
  profile combines declared base/speech extras and observed optional hardware
  imports; final runtime feature coverage still requires independent review.

## Complete candidate wheel set for the selected dependency profile

`deploy/locks/stab07e-anvilmobile-cp313-aarch64.json` records 26 explicit
package versions, filenames and SHA256 digests, CPython 3.13.5, AArch64 and
glibc 2.41. The adjacent `.requirements.txt` is a pip `--require-hashes`
manifest. The wheelhouse resides on Forge at
`/home/rt-remote/workspaces/rt-stab07e-wheelhouse/` (25 MB) and is deliberately
**not** committed as binary blobs to the Rolling Thunder source repository.

The dependency set includes Pillow, pycountry, pydantic and pydantic-core,
pyserial, PyYAML, Vosk, cffi, requests, `srt`, their metadata-resolved
transitive dependencies and the observed relevant Bleak/DBus, web-socket,
CayenneLPP, cryptography and serial-asyncio package dependencies. The locked
package versions are explicit and no wheelhouse installation or production
package upgrade occurred.

Vosk 0.3.45 uses a `py3-none-manylinux2014_aarch64` wheel. The initial
resolution failed when that legacy tag was omitted. After explicitly enabling
`manylinux2014_aarch64`, its required `srt 3.5.3` had no compatible published
wheel. `srt-3.5.3.tar.gz` (SHA256
`4884315043a4f0740fd1f878ed6caa376ac06d70e135f306a6dc44632eed0cc0`)
was built in two isolated Forge pip wheel invocations with
`SOURCE_DATE_EPOCH=1700000000` and `PYTHONHASHSEED=0`. The two built pure-Python
wheels were byte-for-byte identical, SHA256
`a8c17cb4d88016230151f55c1d51ab4a3ff01cca9a3057653b1c2a1c6aba16ca`.
The build tooling was resolved from pip's index for these trials, **not yet
pinned or independently audited**, so this is not final reproducible
supply-chain provenance.

## Implemented source, integrity and transport checks

- `deploy/rolling-thunder-wheelhouse.py`: verifies the exact target and lock
  schema; one and only one hash-matching wheel per pinned package; package
  name/version/Requires-Python and wheel metadata consistency; ARM64 CPython
  3.13 compatible wheel tags; each native `.so` is AArch64 ELF64; no
  symlink, traversal or Python `.pth` injection entry; bounded file/archive
  size; all active PEP 508 `Requires-Dist` metadata requirements resolve to
  explicitly locked versions for the target environment. No network or pip
  installation occurs during verification.
- Forge also executed **pip's own fully offline dependency resolution** with
  `--no-index`, `--only-binary=:all:`, `--require-hashes` and exact target
  CPython/ARM64 tags. All 26 wheels resolved using only the cached wheelhouse;
  no wheel was installed or compiled on AnvilMobile.
- 90 native ELF objects across the wheel set were identified as AArch64, not
  the Forge machine architecture. This does **not** establish that the native
  libraries will load correctly with every OS library on the Pi.
- `deploy/rolling-thunder-release-payload.py`: verifies wheelhouse/lock,
  regenerates source archive from immutable exact-Git blobs, and produces a
  deterministic canonical tar with `source.tar`, locked wheel files,
  `dependency-lock.json`, and `release-payload.json` enumerating component
  hashes and failure-safe status flags. It excludes live SQLite, credentials,
  station settings, the Pi interpreter, and OS shared libraries.
- The exact source SHA `96b96da934585269f5b2cf80ca3187d8675ebbaa`
  produced the same 46,151,680-byte transport tar twice, SHA256
  `a8b984bd154e55158056874e8ebd852e1a6dd2bc534a689514537c4819d547c1`.
  Both copies reside in the isolated
  `/home/rt-remote/workspaces/rt-stab07e-artifacts/` directory on Forge.
  These files are **not installed releases** and no permanent artifact
  publication/retention contract is implied.

## Explicit incomplete/full-release distinction

The wheelhouse now gives an offline, hash-pinned **candidate package layer**,
not a complete, protected, executable Pi release. The payload manifest always
states `interpreter_included=false`, `signed_release=false`,
`root_owned_release=false`, `loaded_code_proven=false`, and
`production_ready=false`. Its builder reports `offline_payload_not_installable`;
the wheelhouse verifier reports `release_installable=false` and
`reviewed_provenance=false`. Do not modify these flags merely because offline
hash checks pass.

Outstanding before creating a complete protected release:

1. Independently vet the published wheel digests, signatures/provenance,
   licensing and exact source-distribution and build-toolchain hashes.
2. Pin/attest the **complete** target OS interpreter, standard library,
   dynamic loader and system shared-library dependency closure; ensure a
   compatible and tested trust mechanism for apt/OS security updates.
3. Independently rebuild/test the locked Python dependencies on an actual
   isolated ARM64 Python 3.13.5 environment, including native imports, Vosk
   speech, Tk, serial, BLE and expected hardware adapters with fakes.
4. Build a **non-editable** application wheel from the exact source SHA;
   verify offline `pip install --no-index --require-hashes` behavior in an
   isolated target-compatible venv and compare installed `RECORD` files.
5. Construct a root-owned, access-controlled, non-mutable installed release
   under an approved path with an exact manifest that covers the venv,
   interpreter and native modules; validate the expected systemd launch
   command, approved configuration/data paths, crash/restart and rollback.
6. Independently sign release/launch provenance, bind it to the exact process
   and kernel start event, and establish loaded-code proof beyond disk hashes.
   Signed observations and Git HEAD alone are insufficient.
7. Obtain separate owner approval for merges, privileged installation,
   production restart/deploy and parked RF; inspect the protected FT8 drop-in
   and original wrapper; validate database/WAL/QSO integrity and physical
   radio receive state. Document actual related infrastructure changes in
   private `spifford3472/ki5vnb-qth-infrastructure` with exact paths,
   integrations, jobs, validation, rollback and history before completion.

## Testing, rollback and change history

`tests/test_arm64_wheelhouse_payload.py` tests target compatibility, exact
wheel hashes, dependency closure, missing/extra files, rejected x86 native
ELF, `.pth` injection, symlinked/tampered files and repeated transport payload
identity using a disposable Git tree and synthetic wheels. The full existing
pytest suite and strict MyPy/Ruff remain mandatory. No test touches live
hardware or copies data from the active Pi.

Change history 2026-11-14: Added the offline wheelhouse lock, verifier,
transport builder, local real-payload reproducibility check and developer
instructions. Rollback is to abandon the draft branch and delete only the
explicitly named Forge candidate files after independent owner review; there
are no production host changes to undo. **Release decision: NO GO.**

## STAB-07F staging continuation (2026-11-14)

The exact Git application wheel was built twice identically and a 30-file payload candidate was verified and staged in a private Forge-only directory using no-replace atomic publication. A native ARM64 test runner and full interpreter/OS dependency closure are still missing; the staging utility explicitly refuses production-ready claims. See `stab07f-isolated-runtime-staging.md`.
