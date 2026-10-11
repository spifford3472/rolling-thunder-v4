# C5.3 Operational commissioning gate — full runtime requires actual evidence

PR #311 and #313 are merged. C5.3 adds a separate, provider-free
`rolling-thunder-forge-ft8-readiness-preflight` program that checks all three
SQLite source stores through read-only handles with `PRAGMA query_only=ON`,
`PRAGMA quick_check`, and required C3/C4 table identities. It makes no calls
to radio, network or the provider. It exits nonzero on missing, unreadable,
corrupt or incompatible sources. The timer fails closed when these sources
are unavailable, and records the specific operational reason.

This is **a preflight component**, not an exception to the existing
owner-reviewed Forge deployment path. The current approved generic Forge
wrapper does not install the readiness timer. Do not use a direct
`systemctl enable`, unapproved helper, or copy into /opt to bypass it.

## Production evidence path discovery

Forge's existing QSO worker reads a protected config under
`/etc/rolling-thunder-forge-propagation-qso-worker/worker.yaml`. The
`/var/lib/rolling-thunder-forge-propagation-qso` directory is owned by
its dedicated account and not traversable by the development user. Therefore
source SQLite paths cannot safely be inferred from `find` as geoff.
An authorized operator must use the component-scoped administration workflow
to resolve the actual three sources, validate path ACLs, test readonly SQLite
WAL access, and record their names in the root-owned
`/etc/rolling-thunder-forge-ft8-readiness/paths.env`. Never write/migrate
the C3/C4 sources from a readiness service.

## Real production cutover requirements

1. Review the exact release SHA, approved deployment helper and immutable
   wheel, service UID/group ACL, rollback/restore and 30–90-day Pi uptime.
2. Verify all C3/C4 source paths and run the preflight under the actual
   future systemd dynamic service identity. Any failure blocks activation.
3. Stage the service with `mode: "off"`, enable the timer only after signed
   systemd unit review, check boot/start/stop/restart and data-source outage.
4. Change to `mode: shadow` only with explicit owner permission. It can
   collect/assess audited evidence but is not authorized to command RF.
5. Separately approve C4 provider research budget, cadence and legal/etiquette
   egress before enabling sampling. Offline and provider errors must not
   interrupt ordinary FT8 operation.
6. Build the **actual statistical qualification producer**, not just
   audit source counts. It must produce a frozen, signed/hashed
   `QualificationCertificate` from independently verified as-of
   forecast features and pre-registered 20 W control-vs-low-power randomized
   trials, and must reject any model/data drift, stale holdouts and invalid
   confidence bounds. Until then, the service must remain collecting.
7. A separately approved operator-visible Pi power controller may use a
   qualifying certificate, always honoring cancel/test indicator, CAT
   readback, operator cap and 20 W fallback. No additional PTT authority.

**A year of passive 20 W attempts alone cannot establish the
counterfactual that 15 W would work.** That can be established only with
approved real control/test interventions. For that reason the feature cannot
honestly self-activate optimized RF power until real experiments are
authorized and collected; this is a scientific and safety constraint,
not a deferred software toggle.

Issue #312 is the durable work tracker for this roadmap.
