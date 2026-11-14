# STAB-07G — Isolated ARM64 execution and installed-runtime evidence

**2026-11-14. Offline Forge test only. Production: NO GO.**

No change was made to AnvilMobile, its current source checkout, QTH networks,
OPNsense, systemd, sudoers, privileges, radio devices, QSO databases or RF.
No Rolling Thunder PR was merged. This work used Desktop Commander, **not**
SpiffBridge. The test binary execution occurred under emulation on Forge.

## Test architecture and exact provenance

Forge is x86_64. Its restricted user cannot access the Docker daemon and did
not install host packages, register binfmt entries, change kernel settings or
obtain root. A statically linked `qemu-aarch64-static` binary was downloaded
as the Ubuntu `qemu-user-static` 8.2.2 package (archive SHA256
`5bb397f66063efa349f6fd5cb3b68cd96f29edd0994e4ba5115cf0859a716bf0`),
verified and **extracted to a private Forge workspace** with `dpkg-deb -x`.
Its extracted binary SHA256 is
`e4f8d99e9ff69c3cefffab71cee358ce2af1ecba1282d04c3eeb44ef76f5a71e`.
No package maintainer scripts were run.

The isolated ARM64 sysroot was assembled from **55 Debian 13 ARM64 packages**.
Their package versions, repository paths and exact SHA256 digests are retained
in `deploy/locks/stab07g-debian-arm64-sysroot.json`. Every downloaded `.deb`
was checked against the selected Debian `Packages.xz` index before extraction.
**The Debian Release/InRelease GPG signature was not independently verified**:
the index was acquired over HTTPS and its exact digest was recorded; the
manifest is test provenance, not independently signed deployment authority.

The emulated sysroot uses Debian `python3.13 3.13.5-2+deb13u5`. The actual Pi
previously reported Python 3.13.5 **`3.13.5-2+deb13u4`**, so interpreter
package bytes and some OS libraries are **not bit-identical** to production.
The emulator successfully executed CPython 3.13.5 and imported its native
`ssl`, `sqlite3`, and Tkinter library components. The test-image CA bundle was
created from Debian's pip wheel after skipping all Debian package post-install
scripts; this affects the **private sysroot only**. Emulation is a compatibility
check, not a claim of same-device/hardware release equivalence.

Local scratch directories, all owned by `rt-remote`, are:

- `/home/rt-remote/workspaces/rt-stab07g-sandbox/downloads` — downloaded and
  checksum-verified test `.deb` archives and ARM64 package index;
- `/home/rt-remote/workspaces/rt-stab07g-sandbox/sysroot` — extracted Debian
  ARM64 test OS, static QEMU and temporary CA bundle;
- `/home/rt-remote/workspaces/rt-stab07g-sandbox/runtime` — isolated arm64
  Python venv and **test-only** import script;
- `/home/rt-remote/workspaces/rt-stab07g-sandbox/logs` — local evidence, not
  persisted to SQLite or station logging;
- existing STAB-07E wheelhouse at
  `/home/rt-remote/workspaces/rt-stab07e-wheelhouse`, and the STAB-07F
  reviewed noneditable app wheel under `/tmp/rt-stab07f-app-wheel-1`.

These are user-owned scratch artifacts, **not root-controlled protected release
folders**, and may be removed after review. They are not new systemd services,
ports, timers, persistent jobs, trusted authorities or runtime integrations.
The 55 Debian archives and QEMU executable are deliberately not committed as
binary blobs in the Rolling Thunder repository.

## Isolation: why this cannot reach the radio

The `bwrap` invocation uses `--unshare-user`, `--unshare-pid`,
`--unshare-net`, `--die-with-parent`, immutable `--ro-bind` of the private
sysroot and candidate venv, a sandbox-local procfs, minimal `--dev /dev`, a
separate temporary filesystem and `--clearenv`. It does **not** expose the
Forge home directory, station USB nodes, host sockets, credential files, live
QSO DB or AnvilMobile. Networking is disabled and the guest network interface
inventory contained only `lo` (loopback).

`deploy/rolling-thunder-arm64-sandbox.py` restricts the available operations to
`native-smoke` and `pip-check`, verifies the pinned QEMU executable SHA256 and
target AArch64 ELF interpreter, and constructs only the read-only/nosocket
sandbox arguments. It refuses arbitrary commands, unapproved/unsafe roots,
missing guest scripts and unexpected emulator bytes. It cannot install or
restart production code.

`deploy/rolling-thunder-arm64-native-smoke.py` tests **imports only**. It blocks
window creation, socket connections, SQLite connects, serial opens and
subprocess launches during the `rolling_thunder.ui_main` import. It deliberately
does not invoke `ui_main.main()` or start a Tk event loop. Radio USB and audio
nodes are absent. The script emits stable JSON, no QSO/secret data, and
`ui_started=false`, `physical_radio_tested=false`,
`production_ready=false`, `loaded_python_bytes_independently_proven=false`.

## Installed artifact validation actually completed

1. An isolated CPython 3.13.5 ARM64 venv was created using the QEMU emulator.
   Python `-m venv --without-pip` was necessary because there was no host
   binfmt registration. Pip 25.1.1 was bootstrapped from the **SHA-checked
   Debian `python3-pip-whl` package** without network or target host changes.
2. All **26 exact STAB-07E locked wheels** installed using pip
   `--no-index --only-binary=:all: --require-hashes` with the local wheelhouse.
   No dependencies were downloaded or compiled on AnvilMobile.
3. The exact STAB-07F noneditable
   `rolling_thunder-4.4.1-py3-none-any.whl` (SHA256
   `e41205e240628ebed8ab658104710e411f5189a8cab92cbeb7ae75fd29517a31`)
   installed under `--no-index --no-deps --require-hashes`. This is a proper
   wheel installation, **not** an editable working-tree import.
4. Native/packaged smoke test **18/18 passed** (including `ssl`, SQLite,
   Tkinter/_tkinter, Pillow C extension, PyYAML C extension, Pydantic Core,
   CFFI, Vosk, pyserial, `serial_asyncio_fast`, Bleak, DBus Fast, WebSockets,
   PyCryptodome, CayenneLPP, core application and guarded `ui_main` import).
   The first smoke script used the wrong module names for two installed
   distributions; it was corrected using their actual wheel contents. The
   corrected import report is green without faking dependencies.
5. The actual ARM64 `pip check` reported **no broken requirements**.
6. `deploy/rolling-thunder-arm64-record-audit.py` independently traversed the
   extracted venv from Forge, without importing foreign extensions, and
   verified **2,213 SHA256 file hashes across 2,240 RECORD entries** for the
   26 dependencies plus Rolling Thunder. The 27 unhashed entries are the
   `RECORD` files themselves (whose self-hash is inherently absent). Debian
   pip bootstrap is a separately managed OS test dependency and not falsely
   claimed as part of the 26-wheel lock. The audit refuses modified, missing,
   unexpected, symlinked or unhashed application/dependency files.

### Re-running the read-only acceptance checks on Forge

```bash
cd /home/rt-remote/workspaces/rt-stab07
python deploy/rolling-thunder-arm64-sandbox.py \
  --sandbox /home/rt-remote/workspaces/rt-stab07g-sandbox \
  --action native-smoke
python deploy/rolling-thunder-arm64-sandbox.py \
  --sandbox /home/rt-remote/workspaces/rt-stab07g-sandbox \
  --action pip-check
python deploy/rolling-thunder-arm64-record-audit.py \
  --venv /home/rt-remote/workspaces/rt-stab07g-sandbox/runtime/venv \
  --lock deploy/locks/stab07e-anvilmobile-cp313-aarch64.json
```

Only execute these commands on the **existing private Forge test workspace**.
The helper is a validation runner, not a trusted host installer. If the
workspace has been deleted or changed, rebuild separately from pinned source
artifacts and revalidate every hash. Do not transfer it to AnvilMobile.

## What STAB-07G still does NOT prove

- Complete full-screen UI startup/shutdown, actual Tk event-loop heartbeat,
  physical touch/monitor/audio/GPS, PTT release, FT8 transmit behavior or
  real radio USB access. Those are deliberately excluded from import-only tests.
- A bit-for-bit replica of AnvilMobile's Python interpreter, Debian/Raspberry
  Pi native libraries, systemd, kernel, device access or OS package revisions.
- A complete supply-chain signature chain: Debian index GPG authenticity,
  external wheel upstream provenance and the SRT build-toolchain pins still
  require independent acceptance.
- A root-owned, immutable deployed release; trustworthy process launch
  attestation; actual imported Python bytecode proof; signed owner approval;
  protected wrapper/FT8 configuration acceptance; parked SQLite/WAL backup
  consistency and preservation of new QSOs; and physical radio RX/PTT proof.
- Production rollback behavior. Only the **isolated test workspace** is
  disposable; no active service or persistent DB was changed. STAB-07F's
  existing no-replace stage tests remain the offline rollback guard, not a
  production recovery substitute.

## Test ownership, repeatability and change history

- `tests/test_arm64_sandbox.py` checks the unprivileged networkless fixed
  command, no extra mounts, emulator hash and arch refusal, private paths and
  negative approval/command tests. It never runs QEMU in normal CI.
- `tests/test_arm64_record_audit.py` covers exact package inventory, wheel
  RECORD file hashes, symlink/escape/missing/modified-file refusal and the
  mandatory nonproduction status. No live files are touched.
- The normal full Python, strict MyPy, Ruff and GitHub CI gates apply to this
  candidate. CI is x86_64 and cannot replace the **separately executed**
  Forge ARM64 emulation evidence recorded above.

**Rollback:** abandon this draft PR and remove the named disposable Forge
scratch workspace only after preserving the test evidence needed for review.
There are no AnvilMobile or network infrastructure changes to revert.

**2026-11-14 change history:** Extracted verified QEMU and Debian ARM64
package archives into Forge scratch, executed isolated Python and installed
27 locked packages (26 dependencies plus application), ran native smoke/RECORD
checks, added fail-closed offline rerun tools, pins, tests and this report.
Release decision remains **NO GO** until independent parked physical and
privileged deployment acceptance is completed under separate owner approval.
