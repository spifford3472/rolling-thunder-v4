# Propagation integration and Wavelog cleanup review

## Verdict

**PASS FOR CODE AND STAGED ROLLOUT REVIEW; NOT AUTHORIZED FOR COMMIT, MERGE,
INSTALLATION, PROVIDER ACCESS, PRODUCTION CHANGE, OR ACTIVATION.**

The integration branch preserves the local six-character QSO grid and the separately
developed HamQSL/KC2G collector, completed-QSO/VOACAP worker, PSK Reporter
orchestration, and safe Forge propagation deployment proposal.

Following the upstream maintainer decision, the staged Wavelog installed-version
API, durable upgrade latch, remote-upload guard, Pi polling/warning, separate watcher
credential/configuration, documentation, and tests were removed. The affected
contact-sync, Pi runtime, UI, and secret/config files now match their mainline
versions exactly. No custom Wavelog patch or version watch is part of this release.

The required Wavelog target is an unmodified official
`ghcr.io/wavelog/wavelog` image pinned by reviewed immutable digest. The running
patched image was not inspected again, restarted, replaced, or otherwise touched.

No commit, push, merge, deployment, production configuration change, service
restart, Wavelog write, station-profile creation, provider request, or radio action
was performed.

## Integrated scope retained

- Disabled-by-default, independently supervised HamQSL and KC2G environmental
  collection with durable provider cadence/backoff/health and provider-I/O-free
  status.
- A separate double-gated, undeployed completed-QSO inbox and bounded VOACAP worker
  with stable-UUID replay validation, leases, retry/dead-letter state, and isolated
  status publication.
- Production-inactive PSK Reporter orchestration with confirmed FT8
  contact/terminal-attempt matching, exact request-window identity, durable
  cross-process 300-second pacing, bounded batches, and single-copy raw provider
  archives.
- Propagation-only deployment assets using a dedicated no-login identity, separate
  application/config/state paths, an exact-40-SHA component hook, and no authority
  over contact sync, Wavelog, the Pi, spots, or radio services.
- Local six-character `Contact.my_grid` / `my_grid6` and derived
  `my_grid4` behavior already present in the mainline branch baseline.

## Wavelog cleanup

### Restored exactly to mainline

- `config/forge-contact-sync.example.yaml`
- `deploy/systemd/forge-contact-sync.env.example`
- `src/rolling_thunder/application_runtime.py`
- `src/rolling_thunder/application_secrets.py`
- `src/rolling_thunder/forge_contact_sync.py`
- `src/rolling_thunder/forge_contact_sync_api.py`
- `src/rolling_thunder/forge_contact_sync_config.py`
- `src/rolling_thunder/forge_contact_sync_main.py`
- `src/rolling_thunder/ui_main.py`
- `tests/test_application_runtime_forge.py`
- `tests/test_application_secrets.py`
- `tests/test_forge_contact_sync.py`
- `tests/test_forge_contact_sync_api.py`
- `tests/test_forge_contact_sync_config.py`
- `tests/test_home_platform_runtime.py`

### Removed untracked watcher-only files

- `src/rolling_thunder/forge_wavelog_version.py`
- `src/rolling_thunder/pi_wavelog_version.py`
- `src/rolling_thunder/wavelog_version.py`
- `tests/test_forge_contact_sync_main.py`
- `tests/test_forge_wavelog_version.py`
- `tests/test_pi_wavelog_version.py`
- `tests/test_wavelog_version.py`

Watcher-only sections were also removed from the contact-sync, operator, engineering,
configuration, deployment-test, source-index, and test-index documentation.

Repository search after cleanup finds no runtime/config/test reference to
`version_watch`, `/wavelog-version`,
`ROLLING_THUNDER_WAVELOG_VERSION_API_KEY`, `prior_known_version`, or
`accept-version`.

## Official station-profile semantics audit

`docs/WAVELOG_STATION_PROFILE_RESOLVER_DESIGN.md` records the official API audit
and a future supported design. The reviewed upstream contracts establish that:

- a QSO is logged against an owner-scoped station location selected by
  `station_profile_id`;
- the station location carries callsign, grid, DXCC, zone, and subdivision context;
- the QSO PATCH contract does not expose a per-QSO `my_gridsquare` override;
- logbook `station_ids` updates replace full membership rather than appending;
- station creation cannot inherit external-service credential/policy fields through
  the Station API; and
- station deletion also deletes associated QSOs.

The future proposal is therefore read-only and operator-provisioned: it resolves one
pre-existing station by reviewed ID/UUID and exact six-character routing identity,
verifies logbook membership, and fails closed if absent or ambiguous. It performs no
automatic create, patch, link, activation, rename, or deletion. It is design-only
and is not implemented by this release.

## Propagation safety assessment

- The Phase 1 collector remains disabled and has no listener, radio path,
  contact-sync path, Wavelog path, QSO producer, or activation side effect.
- Its production template rejects enabled VOACAP, weather enrichment, or PSK
  Reporter controls and uses a dedicated database.
- HamQSL/KC2G calls are sequential, timeout-bounded, independently retried, and
  subject to a one-hour minimum cadence.
- The QSO worker has separate disabled configuration, inbox, history, and status
  paths. It has no deployed service unit or producer.
- PSK Reporter has no process, scheduler, authenticated ingestion transport, or
  production configuration. Provider attempts are globally paced and bounded.
- Completed-QSO replay is exact and UUID-idempotent; changed immutable payload under
  one UUID is rejected.
- The propagation deployment hook accepts only an exact 40-character lowercase SHA,
  uses fixed paths/service identity, and can restart only the propagation unit when
  it was already active.
- The separately inspected root dispatcher accepts `<component> <40hex>`, fetches
  through `run_as_geoff`, and validates pushed origin commits. The staged adaptation
  adds only an early propagation exit before its legacy shared-service state path;
  privileged review, installation, and deployment remain unperformed.

## Verification evidence

- Focused deployment-asset regression set: **35 passed**.
- Full pytest in the environment permitting the existing loopback HTTP test:
  **2985 passed, 7 skipped in 23.37 seconds**.
- Sandboxed full pytest: **2984 passed, 7 skipped, 1 environmental failure** because
  the sandbox denied an existing test permission to bind `127.0.0.1`.
- Ruff: **passed**.
- Strict MyPy: **passed for 281 source files**.
- Pre-commit over all files: **not rerun for this dispatcher adaptation**.
- `git diff --check`: **passed**.
- Bash syntax for both propagation rollout/deploy helpers: **passed**.
- Production-template provider-free preflight remains covered by automated tests;
  no live provider request was made.

The worktree virtualenv still points its editable `rolling_thunder` import at a
different worktree. Every valid test/build invocation used `PYTHONPATH=src`; this is
an environment-isolation limitation, not a source regression.

## Rebuilt immutable release candidate

- Artifact:
  `release-candidate/20261008/rolling_thunder-4.4.0-py3-none-any.whl`
- SHA-256:
  `1193bafd24c0220755e8a20d712a61d2997f4696a6d311f7410a4eb25ac14dac`
- Size: **6,951,866 bytes**
- Mode: **0444**
- Base commit: `28f798ada0f81e2638797f3a56ebc7c172bb4ea4`
- Reproducibility: three isolated builds with
  `SOURCE_DATE_EPOCH=1791421691` were byte-identical.

Archive-to-source comparisons matched the completed-QSO worker, PSK orchestration,
and restored contact-sync module. The wheel includes both propagation entry points
and contains no Wavelog-version watcher module. A disposable `--no-deps` install
successfully imported contact sync, the QSO worker, and PSK orchestration and proved
all three removed watcher module names are unresolved. This is an immutable review
artifact from an uncommitted worktree, not an exact-commit production artifact and
not eligible for the exact-SHA deployment helper.

## Full rollout checklist — not performed

### Release preparation

1. Review this file, the complete diff, the resolver design, the Wavelog restoration
   checklist, and the propagation deployment integration runbook.
2. Obtain repository-owner authorization for a focused commit. Do not alter reviewed
   content while committing.
3. Re-run Ruff, strict MyPy, full pytest, pre-commit, shell syntax, and
   `git diff --check` against the exact commit.
4. Rebuild from that commit using its commit epoch; create a complete reviewed offline
   dependency wheelhouse and checksum every wheel exactly once.
5. Compare the installed root dispatcher with the inspected transcription, then
   apply only the reviewed early propagation insertion and scoped hook.

### Unmodified Wavelog restoration

1. Follow `docs/WAVELOG_UPSTREAM_RESTORE_PLAN.md` under a separate explicit
   maintenance authorization.
2. Back up and test-restore MariaDB plus uploads, userdata, config, Compose files, and
   current image metadata before changing anything.
3. Resolve and pin a reviewed immutable digest for the official
   `ghcr.io/wavelog/wavelog` image. Do not use a locally patched image.
4. Hold only remote uploads, recreate only `wavelog-main`, preserve all durable
   volumes, and validate existing profiles/QSL policy before resuming contact sync.
5. Perform one controlled upload using an operator-reviewed existing station target.
   Do not automatically create a profile during rollback acceptance.
6. Do not install any Wavelog version watcher, watcher credential, custom
   `MY_GRIDSQUARE` patch, upgrade latch, upload guard, or Pi warning.

### Propagation Phase 1

1. Keep Wavelog restoration and propagation rollout as separate approvals and
   rollback domains.
2. Stage only the exact committed propagation artifact and dependency wheelhouse.
3. Install the dedicated user/unit/config without enabling it; run provider-free
   preflight/status and verify contact sync, Wavelog, spots, Pi, and radio services
   were untouched.
4. After separate authorization, run one bounded HamQSL/KC2G smoke cycle while the
   service remains stopped.
5. Activate only after another explicit authorization and complete one supervised
   scheduled-cycle acceptance.
6. Keep VOACAP, weather enrichment, PSK Reporter, the completed-QSO producer, and
   authenticated ingestion disabled.

## Rollback

- Code rollback point: `28f798ada0f81e2638797f3a56ebc7c172bb4ea4`.
- Propagation rollback is verified stop/disable plus restoration of its independently
  recorded artifact/unit/config; retain its dedicated database for investigation.
- Wavelog rollback uses the exact preserved Compose/image plus the matching tested
  database and volume backup if any migration occurred. Never pair an older
  application image with an incompatible migrated database.
- Never delete the local QSO store, retry metadata, Forge UUID ledger, station
  bindings, propagation history, or Wavelog volumes as a rollback shortcut.
- Never automatically create, rotate, patch, link, or delete Wavelog station profiles
  during rollback.

## Remaining blockers and readiness

- No installed Pi, Forge, Wavelog, systemd, full-screen, provider, radio, or hardware
  acceptance was performed.
- The running patched Wavelog image still requires the separately authorized manual
  upstream-image restoration checklist.
- The root-owned Forge dispatcher remains untouched. Its transcribed interface is now
  reflected in a reviewable insertion fragment; an authorized operator must compare
  the installed source before applying it.
- The staged wheel is built from uncommitted content; an owner-authorized exact commit
  and exact-commit rebuild are required.
- A provisional Linux x86_64 / CPython 3.12 offline wheelhouse now exists at `release-candidate/20261008/wheelhouse/`: 10 wheels (approximately 25 MB), including the uncommitted project wheel. All 10 entries in its `SHA256SUMS` passed `sha256sum -c` on 2026-10-08 at 16:54 EDT. This is NOT an exact-commit deployment artifact; rebuild and revalidate from the approved immutable commit before installation.
- Propagation live-provider smoke and supervised scheduled-cycle acceptance remain
  outstanding.
- Repository-owner authorization is still required before commit, merge, deployment,
  Wavelog maintenance, or service activation.

Within those limits, the cleaned code and immutable review artifact are ready for
owner review.

## Exact final working-tree file manifest

Modified tracked files:

- `config/forge-propagation.example.yaml`
- `docs/FORGE_CONTACT_SYNC.md`
- `docs/PROPAGATION_HISTORY.md`
- `docs/ROLLING_THUNDER_OPERATORS_GUIDE.md`
- `docs/engineering/forge-services.md`
- `docs/engineering/index.md`
- `docs/engineering/ownership-and-dependencies.md`
- `docs/engineering/shared-component-consumers.md`
- `docs/engineering/shared-component-contracts.md`
- `docs/engineering/source-file-index.md`
- `docs/engineering/system-architecture.md`
- `docs/engineering/test-index.md`
- `pyproject.toml`
- `src/rolling_thunder/forge_propagation_collectors.py`
- `src/rolling_thunder/forge_propagation_config.py`
- `src/rolling_thunder/forge_propagation_history.py`
- `src/rolling_thunder/forge_propagation_main.py`
- `src/rolling_thunder/forge_pskreporter.py`
- `tests/test_forge_deployment_assets.py`
- `tests/test_forge_propagation_history.py`
- `tests/test_forge_propagation_repository.py`
- `tests/test_forge_pskreporter.py`

New untracked files:

- `INTEGRATION_REVIEW.md`
- `config/forge-propagation-qso-worker.example.yaml`
- `config/forge-propagation.production.example.yaml`
- `deploy/forge-propagation-rollout`
- `deploy/prepare-forge-propagation-stage`
- `deploy/rolling-thunder-forge-deploy-propagation`
- `deploy/rolling-thunder-forge-deploy-propagation-dispatch.example`
- `deploy/systemd/rolling-thunder-forge-propagation.service`
- `deploy/sysusers.d/rolling-thunder-forge-propagation.conf`
- `docs/FORGE_PROPAGATION_DEPLOYMENT_PROPOSAL.md`
- `docs/WAVELOG_STATION_PROFILE_RESOLVER_DESIGN.md`
- `docs/WAVELOG_UPSTREAM_RESTORE_PLAN.md`
- `release-candidate/20261008/AUTONOMOUS_CONTINUATION.md`
- `release-candidate/20261008/RELEASE_CANDIDATE.md`
- `release-candidate/20261008/SHA256SUMS`
- `release-candidate/20261008/rolling_thunder-4.4.0-py3-none-any.whl`
- `src/rolling_thunder/forge_propagation_qso_ingestion.py`
- `src/rolling_thunder/forge_propagation_qso_worker.py`
- `src/rolling_thunder/forge_propagation_qso_worker_config.py`
- `src/rolling_thunder/forge_propagation_qso_worker_main.py`
- `src/rolling_thunder/forge_propagation_runtime.py`
- `src/rolling_thunder/forge_pskreporter_orchestration.py`
- `tests/test_forge_propagation_qso_ingestion.py`
- `tests/test_forge_propagation_qso_worker.py`
- `tests/test_forge_pskreporter_orchestration.py`

There are no remaining tracked diffs in the restored contact-sync/Pi watcher files
listed under “Restored exactly to mainline,” and no watcher-only source/test files
remain.
