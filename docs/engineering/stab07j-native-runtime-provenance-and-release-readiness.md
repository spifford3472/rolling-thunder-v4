# STAB-07J — Pi native provenance sampling and protected release readiness

**2026-11-14 — Read-only AnvilMobile inspection + offline Forge validation. Production NO GO.**

STAB-07J makes the divergence between the live Pi's actual installed Debian ARM64 native runtime and the Forge emulated Debian ARM64 test image explicit and testable. It does **not** upgrade, stage or restart the Pi, install a privileged signer, verify loaded Python bytes, or accept a release.

## Exact Pi observations, source and evidence limitations

AnvilMobile read-only systemd inspection still reported `rolling-thunder.service` active with MainPID `60400`. The operating system is Debian 13 / AArch64. `/usr/bin/python3.13 -I -B` reports CPython 3.13.5, SOABI `cpython-313-aarch64-linux-gnu`, glibc 2.41, SQLite 3.46.1 and OpenSSL 3.5.6. System Python and Tk/native extensions were resolved from their actual installed paths without opening serial or radio devices.

Selected installed **Debian package revisions** include:

| Component | Read-only installed revision |
| --- | --- |
| python3.13 / libpython3.13 family / python3.13-tk | `3.13.5-2+deb13u4` |
| libc6:arm64 | `2.41-12+rpt1+deb13u3` |
| libssl3t64:arm64 | `3.5.6-1~deb13u2+rpt1` |
| libsqlite3-0:arm64 | `3.46.1-7+deb13u1` |
| libtcl8.6:arm64 | `8.6.16+dfsg-1` |
| libtk8.6:arm64 | `8.6.16-1` |
| libexpat1:arm64 | `2.7.1-2` |
| libffi8:arm64 | `3.4.8-2` |

Actual Pi SHA256: interpreter `bd241b38381974ae27d7d5098a6d0e6dda0a744b5e9fdd6fe3a1ae632588961e`; `libc.so.6` `9d465df210ffba519f96fef9477749896b3f67601b5b38c67c1b024b891617b5`; `libssl.so.3` `b72505343068b27ab23e56c9887d2d71b184378067a5eef796b70ced9c621ef8`. `apt-cache policy` showed available newer interpreter and Raspberry Pi-specific OpenSSL package versions. **No upgrade or other package mutation was authorized or performed.**

A bounded read-only Python probe used `dpkg-query`, `importlib.util.find_spec`, `ldd` on selected *installed* system ELF files, and SHA256 of resolved dependencies. The exact **52 observed native file digests, 16 package records, sample method flags and zero unresolved sampled links** are preserved in `deploy/locks/stab07j-anvilmobile-native-observed.json`. It includes no credentials, QSO data or private user files. This is **an operator-collected observation**, not cryptographically authenticated OS package provenance, a complete file inventory, a proof that the running service uses those bytes, or a complete `dlopen` closure. The live application virtual environment may resolve additional modules beyond this sample.

## Exact comparison with existing isolated ARM64 test image

The previously constructed Forge QEMU image from STAB-07G has Debian Python package `3.13.5-2+deb13u5`, rather than Pi's `deb13u4`, and upstream Debian rather than some Raspberry Pi-patched library variants. It was assembled from **55 pinned Debian .deb archives** whose hashes are in `deploy/locks/stab07g-debian-arm64-sysroot.json`; its Debian Release/InRelease **GPG signature was not independently verified**.

`deploy/rolling-thunder-native-runtime-compare.py` validates the Pi snapshot schema and safety flags, rejects missing interpreter evidence, invalid hashes, traversal, unsafe filesystem roots and symlink escape, then compares each observed **resolved** Pi file SHA256 and package revision against the private sysroot without executing native code or changing files. Its sample is restricted: no new production authority, no privilege changes and no available install/restart action.

| Compared Pi sample against Forge test image | Match | Different | Absent |
| --- | ---: | ---: | ---: |
| Native file SHA256 (52) | **27** | **10** | **15** |
| Debian package revisions (16) | **6** | **9** | **1** |

The actual verification returned **exit status 75** and `sampled_disk_parity=false`, `production_ready=false`, `complete_runtime_closure_proven=false`, `distribution_signature_verified=false`, `loaded_python_bytes_independently_proven=false`, `release_decision=NO_GO`. A matching *sample* would still set all latter safety flags false. Thus STAB-07G–I proved useful ARM64 compatibility and isolated mock dashboard behavior, **not exact installed Pi OS-library parity**. Do not invent or substitute the newer `deb13u5` bytes for the live Pi's `deb13u4`.

Offline reproduction, using only existing private scratch evidence:

```bash
cd /home/rt-remote/workspaces/rt-stab07j
python deploy/rolling-thunder-native-runtime-compare.py \
  --observation deploy/locks/stab07j-anvilmobile-native-observed.json \
  --sysroot /home/rt-remote/workspaces/rt-stab07g-sandbox/sysroot \
  --sysroot-manifest deploy/locks/stab07g-debian-arm64-sysroot.json
# Expected: JSON NO_GO and exit 75 because sampled revisions do not match.
```

`tests/test_stab07j_native_runtime_compare.py` covers matched-but-nonauthorizing samples, changed and missing ELF bytes, mismatched package versions, forged approval flags, traversal, symlink escape and missing dependencies. CI is x86; this comparator is offline and independently validated against the captured Pi evidence.

## Protected-release and trusted launch security review

Current unmerged architecture candidates remain separate, incomplete trust boundaries:

1. `deploy/rolling-thunder-release-build.py` binds a deterministic **source** tar to Git blobs. The package/wheel toolchain and native interpreter/OS are not included in this evidence, and the source manifest is not signed.
2. STAB-07E's 26-wheel AArch64 lock and STAB-07F staging can validate hashed wheels, installed `RECORD` checks, immutable **private Forge scratch staging**, and no-overwrite semantics. They are not a root-owned Pi deployment or a complete Pi-native OS image; the Debian and Raspberry Pi archive authenticity chains and build-toolchain reproducibility remain incomplete.
3. `deploy/rolling-thunder-launch-witness.py` verifies Ed25519 signatures on *future trusted observer* reports (boot ID, PID, start ticks, host, service, SHA), but **there is no independently trusted installed launch observer and signer**. A signed observation does not prove what Python imported.
4. `deploy/rolling-thunder-runtime-identity.py` proposes exact protected release paths and file hashes with process/cgroup checks, but explicitly reports `loaded_python_bytes_independently_proven=false`. Running mutable-checkout HEAD, process argv, protected file hashes, startup heartbeat and root-signed JSON must **not** be silently upgraded into in-memory loaded-code identity.
5. STAB-07B's signed approval verifier is not a deployed owner-authenticated issuer, and root-owned wrapper `/usr/local/sbin/rolling-thunder-deploy` and protected FT8 drop-in contents/hashes remain unverified with available permissions. Do not broaden sudo or read protected data via an unapproved bypass.
6. The live release has no owner-approved root-owned immutable `/opt/rolling-thunder/releases/<SHA>` installation, independently signed complete bill-of-materials and trusted exec handoff, or tested in-place replay-safe rollback, SQLite/WAL/QSO preservation and physically observed FT-891 receive/PTT confirmation.

**Minimum recommended follow-up:** before an install design is accepted, obtain *signed* Debian and Raspberry Pi apt repository metadata matching the Pi's exact installed package versions (or a trusted archived snapshot), independently verify all relevant .deb hashes, enumerate full interpreter/lib-dynload/venv and late-`dlopen` dependencies, and reconstruct those exact bytes in an isolated rootless ARM64 environment. Bind the completed source+wheel+OS runtime manifest to the reviewed Git SHA with independent release signing and a root-controlled, constrained launch path. Separately design/prove launch-time/process-instance attestation that does not claim unknowable Python in-memory bytes. Then request explicit owner permission for any parked service, data or physical radio checks.

No key, systemd unit, wrapper, drop-in, sudo permission, QSO, OPNsense configuration or network was changed. If future work affects 192.168.9.0/24, 192.168.10.0/24 or OPNsense, document and commit configuration paths, integrations, jobs, validation, rollback and change history in `spifford3472/ki5vnb-qth-infrastructure` before completion.

**Rollback / change history:** 2026-11-14 added a read-only native sample and strict offline comparison candidate, recorded exact incompatibilities and reviewed the remaining security gates. Abandon draft PR and dispose only of separately reviewed Forge scratch if reverting; AnvilMobile production requires no rollback. **Release NO GO.**

## STAB-07K authenticated historical package recovery (2026-11-14)

Read-only original Pi package sources and independently downloaded/pinned public keys allowed verifying current Debian/Raspberry Pi metadata and Debian snapshots on Forge. 14/16 exact installed package revisions are now fully authenticated down to the downloaded .deb SHA256 and size, including all six exact `python3.13`/`libpython3.13` `deb13u4` packages via signed `trixie-updates` snapshot 2026-07-20. The two missing Raspberry Pi-patched libc6/OpenSSL revisions lack established signed historical repository metadata. An incomplete offline extracted overlay matches 17/52 Pi sampled native files (including Python interpreter) and lacks 35; **no executable production-equivalent image or full native OS closure exists**. See `stab07k-authenticated-exact-arm64-os-reconstruction.md`.
