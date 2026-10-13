# Antenna Reference and RF Exposure v1

## Implemented scope

This feature is an offline, non-actuating reference subsystem. It does not read a
radio, issue CAT commands, key PTT, set output power, create an interlock, contact
Forge, or participate in dashboard/runtime composition.

Implemented modules:

- `antenna_reference_domain.py` — immutable validated catalog, installation,
  band, gain, loss, mode-profile, band-assignment, provenance, and scenario models;
- `rf_exposure_calculator.py` — pure calculation version
  `rf-exposure-plane-wave-v1`;
- `antenna_reference_repository.py` — local SQLite aggregate persistence;
- `antenna_reference_service.py` — typed application boundary for future voice,
  button, CLI, or presentation consumers; it exposes no radio authority;
- `storage.py` schema 21 — additive tables for the preceding records.

No dashboard screen or standalone UI is composed in v1. This is deliberate: the
high-coupling runtime/UI roots do not yet have measured installation data or an
approved low-distraction editing workflow. A future screen must remain gated off by
default and must render immutable service output without SQLite work on the UI
thread.

## Domain and persistence contract

Catalog antennas and physical installations are different records with independent
stable UUIDs. A catalog antenna can have multiple explicit band associations and
multiple frequency-bounded gain records. An installation references one catalog
antenna and separately records:

- frequency-bounded loss contributions, including an explicit `unknown` (`NULL`)
  value;
- whether the loss inventory has been verified complete;
- explicit active/inactive assignments to that antenna's band associations;
- physical-location notes and provenance.

Gain is stored with its original `dBi` or `dBd` unit and source. Calculator v1 uses
`dBi = dBd + 2.15`. It selects a gain only when exactly one gain segment contains
the requested frequency. It never interpolates a gain, extends a nearby segment, or
assumes that an HF association includes 6 m. A `6 m` association must be VHF.

Mode RF-envelope duty and scenario transmit fractions are separate persisted inputs.
Controlled and uncontrolled transmit fractions are recorded independently because
they apply over different 6- and 30-minute averaging windows.
Reference profiles returned by `standard_mode_profiles()` are not inserted into the
database automatically:

| Reference profile | RF-envelope duty |
| --- | ---: |
| FT8 | 1.00 |
| SSB, unprocessed | 0.20 |
| SSB, heavily processed | 0.50 |
| 6 m FM | 1.00 |

Each transmit fraction is scenario- and averaging-window-specific. FT8 does not
imply a 0.50 transmit fraction in either window.

Schema 21 is additive and transactional. Existing tables are not rebuilt. An older
binary correctly refuses a schema-21 database rather than attempting a downgrade;
operational rollback therefore requires restoring the pre-migration database backup
with the matching older code. The migration test proves a failed schema-21
transaction leaves schema 20 and existing data intact. The repository seeds no
antenna, installation, gain, loss, mode, or scenario rows.

## Calculator equations

With forward transmitter output `Ptx`, summed applicable installation loss `L` in
dB, and applicable gain `G` in dBi:

```text
Pantenna_peak = Ptx * 10^(-L/10)
EIRP_peak     = Pantenna_peak * 10^(G/10)
ERP_peak      = EIRP_peak / 10^(2.15/10)
EIRP_average_controlled   = EIRP_peak * mode_RF_envelope_duty * controlled_6min_TX_fraction
EIRP_average_uncontrolled = EIRP_peak * mode_RF_envelope_duty * uncontrolled_30min_TX_fraction
```

Unknown gain, no applicable gain segment, ambiguous gain segments, an incomplete
loss inventory, no applicable explicit loss record, or any applicable unknown loss
makes power/exposure output incomplete. Zero loss is accepted only as an explicit
sourced `0.0 dB` record; absence is not silently treated as zero.

For distance `r`, calculator v1 uses the plane-wave/far-field estimate:

```text
S(W/m²) = EIRP_average * reflection_factor / (4*pi*r²)
r_required = sqrt(EIRP_average * reflection_factor / (4*pi*MPE(W/m²)))
```

The free-space reflection factor is 1.0. The selectable ARRL typical-ground
approximation is 2.56. The chosen assumption is part of each scenario. It is not a
vehicle-specific electromagnetic model.

## FCC MPE table implemented

Calculator v1 implements the power-density column and averaging windows in
47 CFR 1.1310(e)(1), Table 1, verified in eCFR on 2026-10-12. `f` is MHz and power
density is mW/cm².

| Frequency | Controlled (6 min) | Uncontrolled (30 min) |
| --- | ---: | ---: |
| 0.3–1.34 MHz | 100 | 100 |
| >1.34–3 MHz | 100 | 180/f² |
| >3–30 MHz | 900/f² | 180/f² |
| >30–300 MHz | 1.0 | 0.2 |
| >300–1500 MHz | f/300 | f/1500 |
| >1500–100000 MHz | 5.0 | 1.0 |

Tests cover the requested 1.34, 3, 30, 50, 54, 146, and 440 MHz boundaries and
points. The result always presents both environments and never labels a numerical
estimate compliant, noncompliant, safe, or unsafe.

References:

- [47 CFR 1.1310](https://www.ecfr.gov/current/title-47/chapter-I/subchapter-A/part-1/subpart-I/section-1.1310)
- [ARRL RF Exposure Calculator](https://www.arrl.org/rf-exposure-calculator)
- [ARRL RF Exposure Calculator Instructions](https://www.arrl.org/rf-exposure-calc-instructions)

## Mandatory interpretation limits

The numerical result is a reference/advisory estimate only. It is not a compliance
finding, safety finding, engineering certification, or substitute for a station
evaluation. In particular:

- near-field coupling can invalidate the plane-wave estimate;
- the vehicle roof/body, glass, feedline, occupants, nearby metal, antenna pattern,
  ground, and mounting geometry can materially change fields;
- simultaneous sources require an aggregate-exposure evaluation;
- directional antennas may require evaluation in multiple directions;
- unknown occupant/bystander geometry requires further evaluation;
- ARRL warns that its calculator is not for an antenna less than 20 cm from a
  person and identifies special near-field concerns for some antenna types.

The scenario distance defaults to exactly 6 ft (1.8288 m), with
`occupant_distance_verified=false`. It is not a measured driver, front-passenger,
rear-passenger, pedestrian, or bystander clearance.

## Tomorrow data-entry and acceptance tasks

Before any operational use:

1. record actual antenna manufacturer, model, serial/asset identity, and source
   documents;
2. enter each supported band explicitly, including a separate 6 m VHF association
   only where the manufacturer or measurement supports it;
3. enter sourced gain and original unit for every evaluated frequency segment;
4. measure or document every connector, feedline, switch, duplexer, tuner, and
   other path loss by frequency, and mark `losses_complete` only after review;
5. measure straight-line distance from every radiating antenna part to driver,
   front passenger, rear passengers, and plausible bystanders—do not reuse the
   6 ft placeholder;
6. record antenna orientation, vehicle-metal/ground assumptions, maximum forward
   PEP, mode envelope duty, and actual transmit fraction over both applicable
   averaging windows;
7. compare controlled and uncontrolled results with the current ARRL calculator
   using the same antenna watts, gain, frequency, duty, transmit fraction, and
   reflection assumption;
8. investigate every discrepancy and retain the calculation inputs/version and
   reference output;
9. obtain measurement/modeling assistance where near-field or vehicle geometry
   makes the simple model unsuitable; and
10. separately evaluate aggregate exposure from all RF sources that can operate at
    the same time.

Full-screen/operator acceptance is deferred because no UI is implemented. No live
RF transmission is required or authorized by this subsystem's automated tests.

## Remaining work

- owner-supplied antenna and installation records;
- bench validation against the ARRL reference calculation;
- vehicle-specific geometry/near-field assessment;
- multi-source aggregation model;
- reviewed import/edit workflow with audit history;
- disabled-by-default, low-distraction presentation and physical-control design;
- installed full-screen acceptance if that UI is later approved.

## Validation for this implementation

Run from the isolated feature worktree with the existing development virtual
environment and `PYTHONPATH=src`:

- `ruff check .` — passed;
- `mypy src/rolling_thunder` — passed, 335 source files checked;
- `pytest -q` — passed, 3343 passed and 7 skipped; the suite's three loopback-HTTP
  acceptance tests were run with ephemeral localhost socket permission;
- `git diff --check` — passed.

There were no test failures in the finished state. No live hardware, production
database, production service, deployment, Forge scheduler, SSH, or RF transmission
was used. Bench comparison, real vehicle measurements, full-screen acceptance, and
live RF acceptance remain intentionally not performed.
