# Phase C5.1 — safe scheduled readiness inventory (candidate, NOT deployed)

C5.1 adds the provider-free `rolling-thunder-forge-ft8-readiness` CLI, an isolated
systemd oneshot/timer **template**, and conservative read-only C4 storage inspection.
It does not run the C4 sampler or subscribe to new FT8 events. It does not generate
or apply advisory watts, contact a provider, or control a radio.

The CLI can be invoked with `--policy <YAML> --c4-db <SQLite>`; it prints one
machine-readable JSON status to the journal. Only `off` and `collecting` or
`degraded` states are emitted: even an apparently enormous number of forecast
rows does not prove prospective as-of validity, calibrated holdout quality,
independence, or statistical noninferiority. A real evidence adapter that verifies
C3/C4 source identities, signed/immutable C5 pairing and chronological evaluation
must be implemented and reviewed before any future readiness promotion. No
operator-facing 20 W behavior changes.

**Important:** YAML 1.1 parses unquoted `off` as boolean false. Quote `mode: "off"`
or `mode: "armed_when_ready"`; invalid policy produces degraded, no-advice status.

The supplied systemd files are candidate packaging, **not** a production install
recipe. They require a read-only group-access audit for the dynamic service identity, verified C4 database pathname,
an immutable package release and a new privileged component-scoped deployment
helper. Neither the pre-existing Forge generic deployment wrapper (contact-sync,
callsign-info, spots only) nor the C3 QSO worker permits installing this component
without new release/rollback engineering. Review and harden exact read-only ACLs,
service identity, journal collection, health alerts, copied-DB acceptance, restore
tests, exact-SHA artifact provenance and rollback before requesting service
activation. C4 sampling remains separately approval-gated and disabled.

Acceptance on an isolated test database: missing C4 store, C4 monthly-response
dedup, config off, armed with abundant rows still collecting, invalid policy
degraded; all result in null suggested power and no transmit authority. No
production SQLite modifications or provider calls.

## C5.1 operational status persistence

The optional `--status-path` writes the most recent fail-closed JSON snapshot
by same-directory atomic rename and fsync with 0600 permissions. State/reason
changes emit a privacy-safe digest and transition summary to the systemd journal.
It does not mutate C3/C4 databases or store callsigns and GPS coordinates.
The timer template uses `StateDirectory=` under its own dynamic service identity
and denies all IP connectivity. Live group ACLs and symlink/visibility checks
must pass before enabling it.

This candidate deliberately cannot report `ELIGIBLE_FOR_FUTURE_ACTUATION`
because no production-reviewed pre-choice/heldout calibration adapter exists.
Do not interpret the presence of the timer as an automatic power automation
system. The C5 readiness policy engine itself is already testable independently;
its calibrated evidence source and scientific validation still need implementation.

## Prospective evidence acceptance gap discovered during code audit

The current `FT8AttemptEvent` v1 has `started_at_utc`, `ended_at_utc`
and terminal `source_event_created_utc`, but **no separately frozen
`choice_at_utc`**. It is not scientifically valid to assume the attempt start,
first TX, or Forge ingestion receipt equals the instant the operator chose the
remote CQ. As-of pairing must remain unqualified until the source event and
outbox include a durable, explicitly captured selection instant, or an
independently reviewed conservative time-bound proves each forecast was
available beforehand. This is a *data contract* requirement, not something
that an arbitrary count of C4 forecasts can solve.

C4's frozen plans contain model/SSN versions and fixed regional target grids,
and its request hashes can identify duplicated monthly VOACAP calculations.
The C5.1 inventory does **not** certify that these modeled region/time cells
match an individual station's decision or independently measured conditions.
The C5 readiness pipeline must verify distinct model-input families,
audited field provenance, UTC availability cutoffs, target-grid uncertainty,
heldout model quality, and noninferiority to the current 20 W baseline before
automatically advancing beyond collecting. Nothing in this PR bypasses those
checks.

### Required pre-activation checklist (no automatic power control)

1. Review C5.1's immutable release packaging, dedicated read-only Forge
   service access, boot timer, persisted status path, journald retention,
   readiness alerts and rollback in a disposable full-stack rehearsal.
2. Add a versioned explicit FT8 target-choice timestamp to the immutable event
   owner, prove compatibility with historical events, and preserve mobile
   logging and offline outbox behavior. Missing timestamps stay excluded.
3. Activate C4's independent sampling under a *separate* explicitly budgeted
   provider pilot and monitor forecast input deduplication and provenance.
4. Build C5's approved prospective feature/label reader and independently
   forward-held-out scientific calibration producer; prohibit unknown,
   synthetic, late, retrospective or censored rows from satisfying readiness.
5. Verify the requested 20,000/2,000/100/30-day/200-sample thresholds *and*
   model version, freshness, statistical quality, drift and heldout
   noninferiority. No deterministic automation should promote on totals alone.
6. Only after separate hardware-control authorization may a future Pi adapter
   act on advice; this Forge component has no CAT/PTT power output.

Do not present this as a self-activating learned-power system until steps
2–5 have demonstrably passed. The status and timer may safely operate in
`off` / `collecting` mode without those later components.
