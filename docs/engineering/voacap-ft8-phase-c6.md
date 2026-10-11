# C6: Forge C4 bounded production sampler — staged only

A new one-shot `rolling-thunder-forge-voacap-baseline` entry point composes the
C4 `BaselineRepository` and `BaselineService` with a loopback-only provider
adapter. Its three activation gates default false, and an absent plan or SSN
snapshot is not synthesized. A valid immutable `BaselinePlan` and a fresh,
source-identified `EnvironmentSnapshot` (captured within 24h) must be
supplied explicitly; stale solar evidence fails closed.

The worker idempotently schedules 00/06/12/18 UTC slots from the frozen plan,
one to three days forward, and invokes the existing bounded lease, replay,
retry and per-day/provider-call/storage budgets. The provider adapter maps
the canonical C4 request to the VOACAP summary API, keeping immutable model
and service version identity. Provider calls are **zero** unless all three
gates are enabled, and localhost is the only permitted endpoint.

The proposed systemd service uses the dedicated C4 owner account and
restricts network to loopback. A six-hour timer is staged as a candidate,
NOT installed or enabled. Activation additionally requires separate approval
of provider budget, exact target inventory/model version, verified as-of
solar provenance and the operator-approved installer/rollback.

**Important:** disabled provider mode does not schedule any slots. A real pilot
must use a new, audited plan and approved provider gates before scheduling.
No baseline data are training eligible by virtue of being present.

C5.4 readiness timer and Pi 20-W radio operation are unaffected. No TX,
CAT/PTT, Pi deployment, service restart or real provider HTTP call performed.
