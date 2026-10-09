# Phase 2 Forge production rollout — gated deployment

Status: preparation only. Do not run the Phase 2 services or enable provider egress
until source-side delivery composition, exact-SHA application builds, and the
independent acceptance requirements below have been verified.

## Current production boundary

Phase 1 HamQSL/KC2G runs under
`rolling-thunder-forge-propagation.service`, and Forge contact sync is independent.
Do not modify either unit, its configuration, its database or its deployment hook.
PSK Reporter and VOACAP QSO services are distinct new processes; installing
their unit templates must not enable them.

## Preflight blockers

1. The source-side producer, authenticated transports, and scheduler are composed
   but remain explicitly disabled by default. Before activation, install two
   independent Pi bearer values in the protected environment file and complete
   provider-free ingestion acceptance against the exact deployed receiver SHA.
2. Distinct private ingress addresses and ports are documented: VOACAP/QSO
   `192.168.9.170:8790`; PSK Reporter `192.168.9.170:8789`. Verify
   address ownership, route, firewall, and that only approved private peers
   can reach them. Do not expose bearer credentials over untrusted plaintext.
3. Both units now point to isolated immutable release trees. Build a review artifact
   with `deploy/prepare-forge-phase2-worker-stage`, review and separately promote it
   to the matching root-owned component staging path, then have an authorized Forge
   administrator run `deploy/rolling-thunder-forge-deploy-phase2-worker` for the
   same exact pushed SHA. The selector never enables a unit and restores the prior
   symlink if restart of an already-active unit fails.
4. Verify both units' `WorkingDirectory`, `ExecStart`, runtime identities,
   `StateDirectory`, `InaccessiblePaths` and configuration ownership as one coupled
   review. VOACAP uses `rolling-thunder-propagation-qso`; PSK uses
   `rolling-thunder-pskreporter`; both are separate no-login identities and neither
   shares the Phase 1 release or state tree.
5. Produce two **independent** random high-entropy ingest secrets on Forge,
   held only in root-protected environment files, and provision matching
   credentials on the approved producer endpoint through the private transport.
   Do not paste real secrets in logs, chats, shell history or Git.
6. Confirm durable local contact **and** successful terminal FT8 attempt
   persistence before source-side enqueue. Delivery is separate, bounded and
   retryable; no DNS, HTTP or provider call in FT8 terminal handling.
7. Preserve the 300-second minimum PSK Reporter latency and the globally
   durable 300-second minimum provider attempt spacing. Do not poll on every
   QSO or on every worker scheduler tick.

## Suggested validation sequence

A. Review the combined source, focused regression suites, and independently
   authored rollout asset checks. Verify `--check-config` on both services
   with every gate off. Avoid provider/network access in this phase.
B. Install system identities, config directories, and private environment
   files while both units remain uninstalled or `disabled`/`inactive`.
   Use exact checksums, root-owned backups, owner-approved sudo and separate
   operator confirmation.
C. Build each artifact from the exact pushed origin SHA, verify its wheel checksum
   manifest and component marker, then install its immutable application environment
   at the final SHA path. Validate the actual launcher as the runtime account.
D. Install unit files, `daemon-reload`, verify `disabled`/`inactive`.
   Recheck Phase 1 and contact-sync health.
E. Enable ingestion **without provider egress** in one service at a time.
   Exercise authenticated acceptance, invalid credentials, UUID replay,
   changed payload rejection, restart recovery, and independent source retry.
   Verify no real contact or logbook was touched by test fixtures.
F. Enable provider gates only after a separately reviewed, bounded network
   test. Validate VOACAP service version/summary availability and PSK
   etiquette, terminal latency and persistent last-attempt state.
G. Observe scheduled cycles, durable health, error/retry status, and service
   restart behavior before treating production rollout as complete.

## Backout and retention

Stop and disable only the affected Phase 2 service, restore its saved
disabled configuration and preserve all its SQLite state for diagnosis.
Disable producer delivery independently; do not delete the source outbox.
Do not roll back or restart Phase 1, contact sync, Wavelog, Pi/FT8 or radios.
