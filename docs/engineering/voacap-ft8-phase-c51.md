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
recipe. They assume a dedicated service identity, verified C4 database pathname,
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
