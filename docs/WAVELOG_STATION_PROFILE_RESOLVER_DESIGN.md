# Future Wavelog station-profile resolver design

**Status:** design only; not implemented, configured, deployed, or authorized.

## Decision

Rolling Thunder will treat Wavelog station locations as the authoritative
Wavelog-side operating identity for a QSO. A future resolver may select an existing,
operator-approved station location, but it must not create, patch, rename, activate,
link, or delete Wavelog station locations or logbooks automatically.

The current integration release does not add this resolver. It preserves the
mainline contact-sync implementation and local six-character QSO grid. This document
defines the supported direction for a later, separately approved change.

## Official semantics audit

The audit was performed against Wavelog's published API documentation on
2026-10-08:

- The [Station API](https://docs.wavelog.org/developer/api-v2/station/) defines a
  station location as the callsign, Maidenhead grid, DXCC, zones, subdivisions, and
  related operating details against which a QSO is logged. Station operations are
  owner-scoped. The list can be filtered by the user's active-logbook preference,
  while direct lookup by a known owned ID remains available.
- The [QSO API](https://docs.wavelog.org/developer/api-v2/qso/) requires an owned
  `station_profile_id` for QSO creation. Its documented QSO PATCH fields can move a
  QSO to another station location, but do not expose a per-QSO `my_gridsquare`
  override. This supports the maintainer decision that station-location data is the
  Wavelog-side source for the operator's location.
- The [Logbook API](https://docs.wavelog.org/developer/api-v2/logbook/) defines a
  logbook as a named set of station locations rather than a QSO owner. Updating
  `station_ids` replaces the complete membership list, so an automated additive
  link operation would require a race-safe read/modify/verify transaction.
- Station creation leaves external-service credentials and policies such as QRZ,
  HRDLog, ClubLog, OQRS, webADIF, and eQSL at provider defaults because those fields
  are not exposed by the Station API. Automatic creation therefore cannot faithfully
  inherit an operator's complete QSL/upload policy.
- Deleting a station location deletes its QSOs and associated confirmation data.
  The resolver must never receive station-delete authority.

The official
[Docker installation guide](https://docs.wavelog.org/getting-started/installation/docker/)
uses `ghcr.io/wavelog/wavelog`. Production rollback must select a reviewed immutable
digest of that upstream image; this repository does not identify or pull a production
digest automatically.

## Required future contract

The resolver input is the immutable QSO-local routing snapshot:

- full six-character `Contact.my_grid6`;
- normalized state/subdivision;
- CQ and ITU zones;
- configured station callsign and DXCC identity.

The resolver output is either:

1. one fully verified, already-existing station location and its approved logbook
   membership; or
2. an explicit unresolved result that leaves the local contact queued.

It must never return a best guess, silently fall back to a home profile, truncate the
grid, or mutate Wavelog to make a candidate fit.

## Operator-provisioned registry

A future deployment should use a reviewed Forge-local registry whose entries bind
the complete routing identity to immutable provider identity:

```yaml
station_profiles:
  - my_grid6: EM79aa
    state: OH
    cq_zone: 4
    itu_zone: 8
    station_id: 42
    station_uuid: 01234567-89ab-cdef-0123-456789abcdef
    station_name: Mobile - EM79AA - OH
    logbook_name: KI5VNB Main
```

The example is a schema sketch, not deployable configuration. The operator creates
and configures each profile in Wavelog, including all QSL and external-upload policy,
then records the verified ID/UUID. Secrets remain outside the registry.

## Resolution algorithm

1. Validate the immutable six-character grid and jurisdiction fields without
   deriving them from current GPS or later provider data.
2. Require exactly one registry entry matching the complete routing identity.
3. Read the station directly by configured ID and verify owner access, UUID, exact
   name, callsign, full six-character grid, DXCC, state, CQ zone, and ITU zone.
4. Read the configured logbook and require the station ID to be an existing member.
5. Return the verified station target without any provider write.
6. On absence, ambiguity, hidden/changed identity, membership mismatch, or provider
   failure, fail closed before the UUID upload claim and keep the local contact
   retryable.

List discovery may support an administrative audit, but runtime resolution should
use the reviewed ID/UUID binding because the station list can be filtered by the
active-logbook preference. Health checks remain read-only.

## API authority and lifecycle

The runtime token should need only `station:read`, `logbook:read`, and the existing
QSO scopes. It must not receive `station:write`, `station:delete`, or
`logbook:write` merely to resolve a target. Profile provisioning and logbook
membership remain deliberate operator actions in Wavelog.

Registry changes require review, a provider-free configuration check, read-only
preflight against Wavelog, and one controlled QSO acceptance. They must not occur on
the Pi UI thread or inside a QSO retry loop.

## Migration and acceptance

A future implementation must be a separate change with:

- typed configuration and immutable resolver results;
- deterministic fakes for exact match, ambiguity, changed UUID, hidden-list direct
  lookup, membership mismatch, and provider failure;
- proof that resolution performs no station/logbook writes;
- compatibility and rollback tests for the existing UUID ledger;
- operator documentation for manual profile provisioning;
- live read-only preflight followed by one explicitly authorized controlled upload.

Until that work is approved, no resolver described here is active and no station
profile should be created automatically.
