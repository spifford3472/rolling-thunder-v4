# STAB-07L — Raspberry Pi historical archives: byte recovery without signed release provenance

2026-11-14 baseline; 2026-11-16 read-only follow-up — **OFFLINE / PRODUCTION NO GO**.

STAB-07L continued the exact ARM64 Pi reconstruction from STAB-07K (14/16 exact archive versions authenticated). The final two Raspberry Pi-patched .deb archives were located on the official Raspberry Pi HTTP(S) pool, downloaded into a new private Forge quarantine, and compared read-only against the previously captured Pi native-file SHA256 sample. Their historical signed package-index provenance was **not** established. The archives therefore remain **untrusted content candidates**, not authenticated release inputs.

## Quarantined exact-version archive bytes

| Pi installed package revision | Untrusted .deb SHA256 | Matching Pi ELF files |
| --- | --- | --- |
| libc6:arm64 2.41-12+rpt1+deb13u3 | 6f23ea0769d9545710f7d690fd26d47539d2729b74a413704790f93483425656 | libc.so.6, libm.so.6, ld-linux-aarch64.so.1 |
| libssl3t64:arm64 3.5.6-1~deb13u2+rpt1 | 31a008c2abe0f1f8ac2c8775ed1ee5ec9e1d4485d21cd25351f8c5604828c786 | libcrypto.so.3, libssl.so.3 |

Original repository-pool paths, for discovery only (not release authorization):

- https://archive.raspberrypi.com/debian/pool/main/g/glibc/libc6_2.41-12+rpt1+deb13u3_arm64.deb
- https://archive.raspberrypi.com/debian/pool/main/o/openssl/libssl3t64_3.5.6-1~deb13u2+rpt1_arm64.deb

dpkg-deb --field showed expected package names, architecture arm64 and installed versions, but these fields are self-reported by the downloaded archives. SHA256 pinning records **the captured untrusted candidate bytes**; it does not authenticate publisher release intent. dpkg-deb --extract was run only inside the separate private quarantine. No maintainer scripts, native binary or application runtime were executed from it.

Comparing the previous read-only AnvilMobile 52-native-file SHA sample against independent extracts:

| Origin | Exact Pi SHA256 file matches |
| --- | ---: |
| STAB-07K 14 authenticated archive extraction | 17 |
| Quarantined libc6 (UNTRUSTED) | 3 |
| Quarantined libssl3t64 (UNTRUSTED) | 2 |
| Missing in these partial extracts | 30 |
| Total sampled | 52 |

All 22 present files match their Pi SHA256 samples; there were zero observed divergent hashes. This is **only on-disk content equivalence**, not a complete native/stdlib/dlopen dependency closure, installed package authenticity, independent loaded-code identity or an executable Pi-equivalent environment.

## Historical release authenticity remains blocked

The independently verified current Raspberry Pi trixie InRelease and matching Packages index do not list these older versions. A September 1, 2026 historical InRelease was recovered from a September 2 Internet Archive capture and verifies under the pinned Raspberry Pi archive key, but the corresponding arm64 `Packages`, `Packages.gz`, `Packages.xz`, and `Packages.lz4` captures were absent. It therefore does not link the candidate versions to archive hashes.

A stronger alternate record was found on the official Raspberry Pi archive's `buildinfo-pool` (base URL `https://archive.raspberrypi.com/debian/`):

| Signed build record | Record SHA256 | Target package SHA256 | Size |
| --- | --- | --- | ---: |
| `buildinfo-pool/g/glibc/glibc_2.41-12+rpt1+deb13u3_arm64.buildinfo` | `1a570c67f0f54e127d1a3eb5672698db3126084ebe6775fba7bf56f159638006` | `libc6_2.41-12+rpt1+deb13u3_arm64.deb`: `6f23ea0769d9545710f7d690fd26d47539d2729b74a413704790f93483425656` | 5,186,294 |
| `buildinfo-pool/o/openssl/openssl_3.5.6-1~deb13u2+rpt1_arm64.buildinfo` | `2fc90bedd7470c95cf6c6ff9a1fa3ef8469e91f44af9d3b4ef4801e6bb9b048b` | `libssl3t64_3.5.6-1~deb13u2+rpt1_arm64.deb`: `31a008c2abe0f1f8ac2c8775ed1ee5ec9e1d4485d21cd25351f8c5604828c786` | 3,436,456 |

Both clear-signatures verify cryptographically with primary-key fingerprint `480203C910DA290C44F704D6A41C82885484A525`; the key's self-asserted UID is `Serge Schneider <serge@raspberrypi.com>`. The public key was obtained from an Ubuntu keyserver because it is absent from the pinned Raspberry Pi archive-key bundle available for this investigation. No independently signed official key publication or other trust-chain binding for this maintainer key was recovered. The signatures and exact SHA256/size matches are strong build-output evidence, but the unverified key binding means this review does **not** accept the records as authenticated publisher provenance yet. An independent reviewer must authenticate the key through an authoritative Raspberry Pi trust source before treating this alternate record as equivalent to the missing signed Packages index.

Required publisher provenance remains either a matching signed SHA256/size-linked arm64 Packages index or a separately reviewed publisher-signed build record whose signing key is independently authenticated. The captured historical InRelease alone and the current `.buildinfo` signatures do not satisfy that condition yet.

**Authenticated installed-package count remains 14 of 16.** Do not modify the STAB-07K signed evidence manifest to claim 16/16, and do not mix quarantined libc6/OpenSSL files into the working STAB-07G/I emulator or protected release.

## Fail-closed verification and tests

- deploy/rolling-thunder-rpi-quarantine-compare.py compares pinned *candidate* archive hashes against the private quarantine, prior Pi sample and independent 14-package signed extract; it refuses changed/oversized files, path traversal, symlinks including symlinked parent directories, duplicate origins and forged sample authority.
- deploy/locks/stab07l-untrusted-rpi-archive-pins.json pins the candidate archive bytes **without certifying a publisher signature**.
- tests/test_stab07l_rpi_quarantine_compare.py tests matching data, missing files, archive alteration, mismatched native content, symlink escapes, path traversal, duplicate origins, invalid SHA256 and false approval.
- All successful reports explicitly contain rpi_historical_signed_index_verified=false, archive_release_authenticity_proven=false, debs_authorized_for_execution=false, complete_os_runtime_closure_proven=false, loaded_python_bytes_independently_proven=false, production_ready=false and release_decision=NO_GO.

The candidate archives, extracted libraries, public keys, and reports were held
in private nonproduction scratch and are not checked into the repository. Their
host-specific paths are intentionally omitted from this public record.

## Remaining work and rollback

First independently authenticate fingerprint `480203C910DA290C44F704D6A41C82885484A525` through an authoritative Raspberry Pi trust source, or recover the exact signed arm64 Packages index. Then bind each exact archive hash and size to the accepted record and update the signed evidence manifest through review; until then the authenticated count stays 14/16. Independently expand the installed runtime sample beyond the original 16 packages and 52 files, including interpreter/stdlib, lib-dynload, C-extension and delayed native-load dependencies. Only after every required OS input is trusted should a newly constructed isolated executable ARM64 runtime undergo native-import, Tk, and full mock-dashboard tests. Protected release signing, trusted process-instance evidence, SQLite/WAL rollback and physical receive/PTT remain separate owner-authorized gates.

Rollback: abandon the unmerged draft; explicitly delete only reviewed private Forge quarantine scratch if desired. No AnvilMobile writes, service restart, QSO database access, CAT/PTT, RF, installation, network or OPNsense changes occurred. Any later infrastructure change involving 192.168.9.0/24, 192.168.10.0/24 or OPNsense requires configuration paths, integrations, jobs, verification, rollback and change-history documentation committed in spifford3472/ki5vnb-qth-infrastructure.

Change history: 2026-11-14 — recovered two exact but unsigned-index-unauthenticated Raspberry Pi archive candidates, confirmed five additional Pi file SHA matches, added bounded read-only quarantine/refusal tests, preserved the 14/16 publisher-authenticated gate and declared PRODUCTION NO GO. 2026-11-16 — recovered a signed historical InRelease without its Packages index and two matching maintainer-signed buildinfo records; signature validity is established, signer-key trust is not, so the 14/16 count and PRODUCTION NO GO remain unchanged.
