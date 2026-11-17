# STAB-07J — Pi native provenance sampling and protected release readiness

**2026-11-14 baseline; 2026-11-16 read-only follow-up — Production NO GO.**

STAB-07J compared the installed Raspberry Pi ARM64 runtime with an isolated
Forge ARM64 test image. It did not upgrade, stage, or restart the Pi, install a
privileged signer, verify loaded Python module bytes, or accept a release.

## Native runtime evidence and limits

Read-only inspection identified a Debian 13 ARM64 system using CPython 3.13.5
and Raspberry Pi-patched native libraries. The sampled runtime differed from
the Forge test image: 27 of 52 sampled native files matched, 10 differed, and
15 were absent; 6 of 16 sampled package revisions matched, 9 differed, and 1
was absent. These are bounded sample results, not a complete dependency
closure. Exact host-specific executable/library hashes and the raw per-host
observation were removed from this public repository; no production paths,
process identifiers, or digests are needed to preserve these conclusions.

The 14 authenticated package revisions and the two quarantined
Raspberry Pi-patched revisions are detailed in
[`stab07k-authenticated-exact-arm64-os-reconstruction.md`](stab07k-authenticated-exact-arm64-os-reconstruction.md)
and [`stab07l-rpi-historical-package-quarantine.md`](stab07l-rpi-historical-package-quarantine.md).
The buildinfo signature results do not yet authenticate the signing key to an
authoritative Raspberry Pi trust source. No executable Pi-equivalent image or
full native OS closure exists.

`deploy/rolling-thunder-native-runtime-compare.py` remains a bounded offline
comparator. It validates a caller-supplied read-only observation and compares
sampled resolved files/package revisions with a sysroot without executing
native code or changing production. To reproduce a comparison, supply the
separately authorized private observation and isolated sysroot as inputs; raw
production measurements are intentionally not stored in this public source
repository.

`tests/test_stab07j_native_runtime_compare.py` covers matching-but-
nonauthorizing samples, changed and missing files, package-version mismatch,
forged approval flags, traversal, symlink escape, and missing dependencies. A
sample match still does not prove a complete runtime closure, distribution
signature, production readiness, or loaded Python bytes.

## Protected release and running-code identity

1. `deploy/rolling-thunder-release-build.py` binds a deterministic source
   archive to Git blobs, but does not include the package/wheel toolchain or
   native interpreter/OS; its source manifest is not independently signed.
2. STAB-07E wheel locking and STAB-07F staging validate hashed wheels and
   immutable private Forge scratch staging. They do not provide a root-owned
   Pi deployment or complete Pi-native OS image.
3. `deploy/rolling-thunder-launch-witness.py` verifies signatures on future
   trusted observer reports bound to boot/process-instance fields. No
   independently trusted installed observer and signer are deployed. A signed
   process observation does not prove imported Python bytes.
4. `deploy/rolling-thunder-runtime-identity.py` checks a protected release
   path and process/cgroup binding, but sets
   `loaded_python_bytes_independently_proven=false`. Its tests correctly refuse
   to treat the mutable checkout, argv, file hashes, startup heartbeat, or
   signed JSON as proof of Python module bytes in memory.
5. The live release lacks an owner-approved root-owned immutable release,
   independently signed complete source/wheel/OS manifest, trusted constrained
   launch path, process-bound readiness, and accepted data-preserving rollback.

**Minimum follow-up:** authenticate every required native package through
signed Debian/Raspberry Pi repository metadata or a separately reviewed
publisher-signed equivalent; expand the dependency closure, including
interpreter, standard library, extension modules, and delayed native loads;
then reconstruct and test an isolated ARM64 runtime. Bind a signed complete
runtime manifest to the reviewed Git SHA and use a root-controlled constrained
launch path. A future process witness should establish immutable release and
process-instance binding without claiming arbitrary in-memory Python bytes are
independently measured. Installation, key provisioning, parked service/data
acceptance, and physical receive/PTT checks remain separately authorized.

No key, unit, wrapper, drop-in, sudo permission, database, OPNsense
configuration, or network was changed by STAB-07J. **Release remains NO GO.**
