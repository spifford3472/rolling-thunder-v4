# STAB-07K — Authenticated exact ARM64 OS package reconstruction

**2026-11-14 | Offline Forge candidate only | Production NO GO.**

## Objective and actual result

**Scope clarification (2026-11-17):** This workstream reconstructs the
Raspberry Pi's existing `aarch64` OS userspace as an optional full-image
reproducibility path; it is not a generic ARM deployment or migration target.
STAB-07G's QEMU ARM64 tests run on x86_64 Forge and do not emulate Raspberry Pi
board hardware. The reviewed application deployment candidate uses the Pi's
existing virtual environment and does not install or replace OS `libc` or
OpenSSL. Thus the 14/16 result blocks this reconstructed-image path. An
application-only release could instead preserve the installed Pi OS as its
baseline, but that needs explicit owner acceptance and separate verification
of the exact application environment and running process. No such acceptance
is recorded here. A possible future Intel host would require a separate
x86_64 runtime and acceptance plan.

Reconstruct the Raspberry Pi's exact installed native Debian/Raspberry Pi runtime on isolated Forge, using an authenticated `InRelease → Packages → .deb` SHA-256 chain. The complete image is **not yet buildable**: **14/16** selected exact installed packages have been cryptographically verified and acquired. The remaining **2 Raspberry Pi-patched archives** cannot be accepted without authenticated historical Raspberry Pi repository metadata.

No AnvilMobile upgrade or write, restart, service edit, radio/CAT/PTT operation, QSO read/write, package-install script, sudo change or production deployment was performed. The pre-existing STAB-07G–I ARM64 emulator and mock-dashboard test remain intact; nothing in the live emulator has been replaced with a partial build.

## Source of truth: actual installed Pi revisions

The read-only STAB-07J Pi evidence established a bounded target of 16 installed Debian package revisions and 52 native files. Exact host-specific hashes and process identifiers are withheld from this public repository. This sample is a **target** to reproduce, not proof that the system process executes those particular bytes.

A second read-only inspection of `/var/lib/apt/lists` verified:
- Debian `trixie` and Raspberry Pi `trixie` cached `InRelease` signatures with root-installed archive keys using `gpgv`;
- the uncompressed cached ARM64 `Packages` indexes matched the SHA256 and byte lengths in their signed release files;
- the signed **current** ARM64 indexes contain only **six** of the exact installed versions from the 16-package sample;
- the Pi's `/var/cache/apt/archives` has **none** of the missing ten exact older archives.

No `apt update`, `apt install` or package-list modification was requested or executed.

## Independently pinned keys and verified repository snapshots on Forge

Public signing keys were copied from Pi read-only keyring files to private, caller-owned Forge scratch as **public data only**. Their SHA256 was checked against the Pi's original root-installed public-key files before use. No private signing key was accessed, created or transferred.

The combined Debian public-key test ring SHA256 is `c042cf3ba41a234f709a6f50053ce3c23031d2d4f109a563ffc1193403b26895`, containing independently pinned bookworm automatic, trixie automatic, and trixie stable keys. The Raspberry Pi archive key SHA256 is `3a29901549ae65a910de13a32551e6eea7f45ba1fd70f0cb67e5c70d98488071`. Separate Debian security bookworm/trixie keys were also acquired and checked in private scratch for historical investigation; no security-snapshot Python package was selected in the final 14.

The verified package sources are:

| Authenticated source | Exact installed packages recovered | Verified evidence |
| --- | ---: | --- |
| Current `https://deb.debian.org/debian/`, `trixie/main` | 6 | Pinned Debian archive public keys, successful `gpgv`, signed `Packages` SHA256/size, exact archive hash and length |
| `https://snapshot.debian.org/archive/debian/20260801T000000Z/`, `trixie/main` | 2 | Independently verified historical Debian release and exact `libexpat1`, `libsqlite3-0` archives |
| `https://snapshot.debian.org/archive/debian/20260720T000000Z/`, `trixie-updates/main` | 6 | Independently verified historical Debian release, package index and all six exact Python 3.13 `deb13u4` archives |
| Current `https://archive.raspberrypi.com/debian/`, `trixie/main` | 0 | Independently verified Raspberry Pi archive signature and current package index; the required older patched revisions were not present |

**Historical signed release metadata remains historical:** signature validity at issuance and content hashes do not imply a now-current secure APT update channel. In particular, expired historical `Valid-Until` dates, if present, are not permission to install obsolete packages on the Pi. The 14 archives were downloaded into a **nonproduction user-owned Forge workspace only**.

The final, committed machine-readable evidence is `deploy/locks/stab07k-signed-exact-apt-evidence.json`. It records source release and index SHA256 values, public-key fingerprints by hash, every verified exact `.deb` SHA256/size/path and the remaining two installed revisions.

### Recovered exact package revisions

- Current Debian: `libffi8 3.4.8-2`, `libgcc-s1 14.2.0-19`, `libstdc++6 14.2.0-19`, `libtcl8.6 8.6.16+dfsg-1`, `libtk8.6 8.6.16-1`, `zlib1g 1:1.3.dfsg+really1.3.1-1+b1`.
- Historical Debian `trixie/main`: `libexpat1 2.7.1-2`, `libsqlite3-0 3.46.1-7+deb13u1`.
- Historical Debian `trixie-updates/main`: `python3.13`, `python3.13-minimal`, `python3.13-tk`, `libpython3.13`, `libpython3.13-minimal`, `libpython3.13-stdlib` — **all exact version `3.13.5-2+deb13u4`**.

The first two lists plus Python represent **14/16 exact package versions** from the Pi's observed 16-package sample.

### Still missing: Raspberry Pi-patched packages

- `libc6:arm64 2.41-12+rpt1+deb13u3`
- `libssl3t64:arm64 3.5.6-1~deb13u2+rpt1`

The verified current Raspberry Pi package index advertises newer packages; do **not** substitute them. No authenticated historical Raspberry Pi `InRelease` plus matching `Packages` index for those two exact versions has been established. A direct `.deb` archive URL or a coincidentally matching file hash without signed archive metadata is **not sufficient** for the chosen release authenticity policy. This is an explicit external historical provenance blocker.

## Implementation and deterministic security tests

`deploy/rolling-thunder-signed-apt-closure.py` is an offline **read-only** APT evidence validator. It takes an explicitly pinned public keyring digest, a clearsigned `InRelease`, an uncompressed ARM64 package index, a fixed exact version map, and a private .deb archive root. It:

1. Checks the supplied keyring matches a separately trusted SHA256, then requires `gpgv` to verify the signed release. **A partial or failed multi-signature verification is refused**; the Debian key set was completed rather than ignoring its initial nonzero exit.
2. Requires exactly one `SHA256` entry binding the expected component/architecture `Packages` index, including exact byte length.
3. Requires exactly one matching package name, installed version, architecture, canonical archive path, package SHA256 and archive byte length; refuses missing, duplicate, unpinned, symlink-escaped or modified contents.
4. Returns proof only of the **selected archive sample**, with `complete_os_runtime_closure_proven=false`, `loaded_python_bytes_independently_proven=false`, `root_owned_release_installed=false`, `production_ready=false`, `release_decision=NO_GO`.

`tests/test_stab07k_signed_apt_closure.py` generates a disposable Ed25519 public/private GPG fixture only in temporary test directories and tests real signed metadata, modified `.deb`, tampered `Packages` or `InRelease`, missing/wrong keys, changed version, path escapes, symlink escape, false metadata and oversized package selection. Test keys are ephemeral, not added to Git or the Pi.

## Offline nonbootable extraction evidence

A separate private Forge directory contains extracted files from the **14 already verified archive bytes**, using `dpkg-deb --extract` only: no package postinstall scripts, no setup of system libraries, no replacement of the existing emulator, no systemd unit and no real device access. Each `.deb` was rehashed and size checked against the signed manifest immediately before extraction.

Comparison against the Pi's **52 sampled native file hashes** found:
- **17/52 exact SHA256 matches**, including `/usr/bin/python3.13`;
- **35/52 files absent** from this intentionally incomplete 14-package overlay;
- **0 differing hashes among the 17 present sampled files**.

This demonstrates matching actual native bytes for the included files, **not** a bootable/complete image, full `lib-dynload` and dynamic-linker closure, or trusted process identity. Not all OS packages needed by the dashboard are in the 16-package sample. Full closure discovery and a complete signed dependency manifest remain mandatory.

Verified release files, public keys, exact `.deb` archives, per-snapshot
reports, temporary extraction, and signature-check logs were held in private,
nonproduction scratch and are not published here.
No binary .deb, GPG key or large package index is checked into Rolling Thunder Git. The small manifest and verifier/test source are committed.

## Repeatable check and release decision

After independently supplying the exact archive files, signed release/index,
and pinned public keyring into a **private** Forge workspace, the verifier
supports the following invocation (substitute private workspace paths):

```bash
cd "$RT_STAB07K_WORKSPACE"
python deploy/rolling-thunder-signed-apt-closure.py \
  --release "$RT_STAB07K_RELEASE" \
  --package-index "$RT_STAB07K_PACKAGES" \
  --keyring "$RT_STAB07K_KEYRING" \
  --keyring-sha256 c042cf3ba41a234f709a6f50053ce3c23031d2d4f109a563ffc1193403b26895 \
  --archive-root "$RT_STAB07K_ARCHIVE_ROOT" \
  --required-json "$RT_STAB07K_REQUIRED_PACKAGES"
```

The output documents **six source-authenticated Python archives**, never a production-ready runtime. The two other verified groups use the corresponding current Debian and August historical files.

**Completion prerequisites:** Obtain authenticated Raspberry Pi historical package indexes/signatures for the two missing versions; acquire and verify their exact archives; expand the verified package set to the *complete* OS dynamic/stdlib/native dependency closure rather than only 16 sampled packages; reconstruct a fresh isolated image with exact package hashes and no host writes; repeat STAB-07G–I native import/Tk/full mock-dashboard tests in that image; separately sign complete release provenance and establish an owner-controlled root-owned launch/rollback and authentic process identity. No automatic updates, unapproved package replacements or production RF.

This milestone does **not** complete the exact image objective. No GitHub PR merge, systemd launch or Pi change is authorized. Any later host/network change affecting 192.168.9.0/24, 192.168.10.0/24 or OPNsense must have configuration paths, integrations, jobs, validation, rollback and change history documented and committed to `spifford3472/ki5vnb-qth-infrastructure` before completion.

**Change history and rollback (2026-11-14):** Built and tested strict signed APT source-to-archive verifier, independently verified three Debian repository vintages plus current Raspberry Pi metadata, recovered 14 exact packages and nonexecuting matching interpreter files, and recorded the remaining historical provenance blocker. Roll back by abandoning this draft and deleting only separately reviewed private Forge scratch artifacts; there is no production rollback to perform. **Release NO GO.**

## STAB-07L quarantine qualification (2026-11-14)

Both exact Raspberry Pi-patched libc6 and OpenSSL archive *bytes* were recovered by HTTPS and match five additional installed Pi ELF SHA samples. Their historical signed InRelease → Packages → archive hash linkage was not established, so these two .deb files are quarantined, not part of the 14 authenticated archive inputs. The combined partial extracted samples show 22/52 matching Pi files, 30 missing, and **no production-equivalent runtime**. See `stab07l-rpi-historical-package-quarantine.md`.
