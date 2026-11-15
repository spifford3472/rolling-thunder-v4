# REL-01 — one controlled parked deployment and rollback acceptance

Status: **BLOCKED; procedure staged, not executed**. This is not approval to
restart AnvilMobile or energize/transmit with the FT-891. Review exact current
`main` and all active maintenance PRs before considering a release.

This checklist predates the STAB-06C–F offline candidates. The 2026-11-14 STAB-07
integration review adds specific journal, authenticated reconciliation,
QSO-preservation, privileged helper staging and exact runtime-SHA gates.
See `stab07-integration-and-parked-release-plan.md`; no privileged STAB-06
component has been installed or demonstrated safe on AnvilMobile.

## Safety and approval gate (all required)

1. Owner explicitly confirms AnvilMobile **parked**, no driving or operational
   QSO/FT8, stable power and local operator available to recover the Pi/radio.
   Never assume location or inactivity from date or a green GitHub check.
2. STAB-04's blocked non-radio cleanup gate either has a reviewed bounded
   critical-path fix, or an explicit, owner-approved conditional operating
   limitation and safe recovery procedure. A current strict xfail must not be
   reported as safety acceptance.
3. STAB-05 CAT lock/TX0 failure cannot prove physical de-keying. A stuck lock
   or failed release is **PTT state unverified**, requires operator-controlled
   receive/power confirmation. No new CAT writers or unsafe forced release.
4. STAB-06 verifies installed system-level service scope, MainPID/cgroup,
   current launcher identity and deployment wrapper, protected drop-ins,
   duplicate prevention, and real UI readiness. Failed or unverified checks
   block the deployment.
5. Exact candidate SHA is merged to `main`, reviewed, CI green at that SHA;
   `ruff check .`, strict MyPy, pytest and `git diff --check` evidence recorded.
   Record skipped/xfail count and their safety relevance.
6. Record exact currently deployed SHA, repository/venv/config paths,
   installed service and drop-in identities, database schema and backup location,
   disk free space, emergency recovery and rollback owner.
7. Explicit separate owner authorization is required for any real RF transmit
   test; a powered-on radio test does not authorize unattended transmission.

## Controlled deployment (after gates, not run now)

Use only the root-owned, approved exact-SHA wrapper through the established
restricted `rollingdeploy` SSH identity. Never bypass the wrapper, modify sudoers,
replace database files from Git, or copy checkout files directly to production.

Document all operator-approved commands and wrapper return code, exact target
SHA and previous SHA. Validate wrapper's serialized invocation behavior
*before* a mutable release; it was previously recorded as lacking a
deployment mutex. Refuse concurrent deploys.

After wrapper completion, independently check:
- `systemctl show rolling-thunder.service` from the **system** manager:
  unit loaded/active, MainPID, cgroup, restart counter and drop-ins;
- one and only one dashboard process in expected cgroup, exact on-disk checkout
  SHA and expected executable/config identity;
- actual UI health/readiness, not just `systemctl is-active` after 3 seconds;
- persisted QSO database/schema/foreign keys, GPS, controller and local logging;
- appropriate stopped/started journal markers `RT_SHUTDOWN`,
  `RT_RUNTIME_SHUTDOWN`, and `RT_PTT_RELEASE` if relevant;
- elapsed cleanup measured against installed `TimeoutStopSec=20`, with no
  missing safety-essential end markers; do not interpret absence of a
  `RT_PTT_RELEASE` event as PTT-safe if no PTT action occurred.

## Rollback and failure disposition

Use the existing wrapper's permitted rollback route **only after verifying**
database/schema compatibility and preserving all newly committed data.
Record prior deployed exact SHA, expected post-rollback service identity,
backup artifact and SQLite integrity evidence.

If rollback refuses due to a schema change, readiness fails, duplicate UI is
found, shutdown hangs, or PTT cannot be confirmed deasserted, stop the release
and use owner-controlled recovery. Do not report an active service or software
TX flag as proof of RF safety. A forced SIGKILL is not a proven de-keying
procedure. Never silently delete contacts, retries or durable observations.

## Acceptance record (fill only from actual observations)

- Parked/operator confirmation: **not obtained**
- Candidate exact merged SHA: **not selected**
- Previous installed exact SHA at release: **not inspected**
- Backup path and integrity checks: **not obtained**
- Wrapper serialization and readiness checks: **not validated**
- Actual UI, MainPID/cgroup and peripheral checks: **not performed**
- Shutdown stop timing/FT8 PTT behavior: **not performed**
- Rollback verified/restored exact SHA: **not performed**
- Release decision: **NO GO until blockers resolved**

## Change history

2026-11-14: Added nonexecuted exact-SHA production acceptance/rollback
checklist. No runtime, services, QTH infrastructure, network, credentials,
AnvilMobile host files or RF behavior modified. Roll back by reverting this
documentation-only change.
