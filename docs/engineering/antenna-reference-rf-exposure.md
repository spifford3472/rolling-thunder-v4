# Antenna Reference and RF Exposure v1

## Implemented scope and authority

This feature is an offline, non-actuating, strictly read-only reference subsystem.
Its sole runtime data authority is the manually maintained YAML named by
`antenna_reference.data_file`. Operators edit that file off-car and restart Rolling
Thunder; the application does not periodically reload it and no dashboard,
keyboard, mouse, touchscreen, encoder, button, radio, or future voice path may
mutate antenna, installation, mode, scenario, or calculation inputs.

`antenna_reference.enabled` defaults false. When false, the ANTENNAS context,
configuration source, background controller, widgets, and shortcut are not
constructed and the established navigation order is unchanged. When true,
`data_file` is required, ANTENNAS follows SETTINGS, and bench shortcut `a` selects
the context. Encoder movement changes only the currently viewed immutable card.
Encoder activation, Back, and all context buttons do nothing. There is no setup or
edit gate.

The feature does not read a radio, issue CAT, key PTT, set output power, create an
interlock, use GPS, contact Forge, or grant voice mutation authority. Any future
voice-edit design requires a separate approval and contract change.

Implemented modules:

- `antenna_reference_domain.py` — immutable validated catalog, installation,
  band, gain, loss, mode-profile, distance-kind, provenance, and scenario models;
- `antenna_reference_config.py` — strict schema-1 YAML document, reference
  validation, actionable file/parse/validation errors, and atomic snapshots;
- `rf_exposure_calculator.py` — pure calculation version
  `rf-exposure-plane-wave-v1`;
- `antenna_reference_service.py` — read-only source/calculation boundary;
- `antenna_reference_panel.py` — one-worker load/calculation and immutable card
  publication;
- `antenna_reference_commands.py` — view-only encoder navigation;
- `antenna_reference_ui.py` — read-only Tk presentation;
- `antenna_reference_repository.py` and schema 21 — dormant legacy storage from
  the earlier PR revision, not composed into the dashboard and not authoritative.

## Configuration lifecycle

The application YAML enables the optional screen and names the separate authority:

```yaml
antenna_reference:
  enabled: false
  data_file: antenna-reference.yaml
```

Relative paths resolve beside the active application YAML. The checked-in
`config/antenna-reference.example.yaml` is valid and intentionally empty. It
contains a commented field-shape reference but no active unverified antenna,
gain, loss, duty, power, transmit fraction, reflection, or distance value.

`config/antenna-reference.mobile-example.yaml` is a separate, valid, manually
editable example that records operator-provided claims dated 2026-10-13. It is not
production configuration and is not selected automatically. Its cable types,
lengths, and CF-4160J devices have no invented attenuation or insertion-loss
values: each contribution is explicitly unknown and every installation keeps
`losses_complete: false`. Consequently the actual regulatory advisory remains incomplete, but a separate
zero-loss far-field screening can be presented with prominent non-compliance caveats.

The mobile example retains explicit ATAS-120A band associations for 40, 20,
15, 10 and 6 metres. No 30, 17 or 12 metre association is inferred.
Six metres is VHF and only its SSB scenario is configured (6m FT8 unsupported).
The verified Comet antenna is **SBB-224**, with manufacturer-reported 2m
gain of 2.15 dBi. The separate generic dual-band antenna is assigned to
70cm at nominal 3.5 dBi pending datasheet verification.

The owner measured driver distances of 90 inches ATAS, 64 inches SBB-224
and 84 inches 70cm generic. The owner reports the front passenger position is
occupied by a monitor and the rear seating by POTA equipment. The 6ft
(1.8288 m) public distance is an actively monitored operating goal, **not a
measured/guaranteed roadway clearance**. Driver and public scenarios are
distinct; there are 11 of each. All remain advisory only, not a compliance verdict.

SSB has owner-confirmed heavy speech processing and uses ARRL's 0.5 RF
envelope duty factor, separately from a 0.5 transmit/receive time fraction.
FT8 and FM have 1.0 RF envelope duty while transmitting and separate
0.5 transmit fractions. SSB references 100W, HF FT8 70W, and both IC-2730A
2m/70cm FM references 15W. These are manually configured **reference**
values, not live radio readings, setpoints, transmission interlocks, or
automatic power controls.

The ATAS-120A feedline is ONLY 6.5 ft RG316; the previously recorded additional
2 ft RG8X segment was erroneous and is removed. The 2 m Comet SSB224 chain is
6.5 ft RG316, Comet CF-4160J duplexer, then 2 ft RG8X. The generic dual-band
antenna's 70 cm chain is 6 ft RG58, Comet CF-4160J duplexer, then 2 ft RG8X.
Cable attenuation, connector loss, and duplexer insertion loss remain `null` /
unknown, and every installation remains `losses_complete: false`. No third-party
certification or loss value is implied.

When enabled, one bounded background worker reads and validates the whole data file
once at dashboard startup, calculates every configured scenario with the pure
calculator, and atomically replaces the published snapshot only after all work
finishes. Tk reads only the published snapshot. A missing, unreadable, malformed,
or invalid file publishes an explicit read-only error; it never becomes an empty
or apparently safe calculation. There is no periodic or in-app reload. After a
manual off-car update, restart Rolling Thunder through the normal approved
operational procedure.

Schema 1 rejects extra fields and validates unique aggregate UUIDs, catalog /
installation / mode / scenario references, and installation band ownership.
Band-assignment `active` and every scenario's distance, verification, distance kind,
and reflection model must be written explicitly rather than inherited from domain
defaults.
Domain validation preserves frequency bounds, numeric limits, 6 m classification,
and source text. Calculator-level incompleteness remains visible for valid documents
whose sourced data is insufficient for a numerical estimate.

## Domain contract

Catalog antennas and physical installations are separate records with independent
stable UUIDs. A catalog antenna can have multiple explicit band associations and
frequency-bounded gain records. An installation references one catalog antenna and
separately records frequency-bounded loss contributions, loss-inventory
completeness, active band assignments, location, and provenance.

Gain retains its original `dBi` or `dBd` unit and source. Calculator v1 converts
`dBd + 2.15` to dBi. It selects gain only when exactly one segment contains the
requested frequency; it never interpolates or extends a segment. HF never implies
6 m. A six-metre association must be an independently sourced VHF association.

Mode RF-envelope duty and controlled/uncontrolled scenario TX fractions are
separate YAML inputs with separate provenance. Controlled and uncontrolled
fractions apply to different 6- and 30-minute averaging windows. No live frequency,
power, mode, or duty value is inferred.

Distance semantics are typed:

- `hypothetical_six_foot` is exactly 1.8288 m and must remain unverified;
- `front_seat_measured` must be explicitly measured/verified;
- `public_measured` must be explicitly measured/verified.

Each scenario also owns an explicit reflection model and source. The screen shows
the configured inputs and result; it offers no what-if controls.

## Dormant SQLite schema 21

Schema 21 remains additive and transactional to preserve databases already opened
by the earlier branch revision. Its antenna tables and repository tests remain for
rollback/preservation compatibility, but the dashboard does not construct the
repository, read those rows, copy YAML into SQLite, treat SQLite as a cache, or
write them. YAML is the sole authority.

The dormant schema predates `distance_kind`; it must not be reactivated as an
authority without a separately reviewed migration and conflict policy. An older
binary still correctly refuses a schema-21 database. Operational rollback therefore
requires the matching pre-migration database backup. No tables or user rows are
removed by this correction.

## Calculator equations

With forward output `Ptx`, applicable installation loss `L` in dB, and gain `G` in
dBi:

```text
Pantenna_peak = Ptx * 10^(-L/10)
EIRP_peak     = Pantenna_peak * 10^(G/10)
ERP_peak      = EIRP_peak / 10^(2.15/10)
EIRP_average_controlled   = EIRP_peak * mode_RF_envelope_duty * controlled_6min_TX_fraction
EIRP_average_uncontrolled = EIRP_peak * mode_RF_envelope_duty * uncontrolled_30min_TX_fraction
```

Unknown gain, no or ambiguous gain segment, incomplete losses, no applicable loss,
or an applicable unknown loss makes output incomplete. Zero loss is accepted only
as an explicit sourced `0.0 dB` value.

For distance `r`, calculator v1 uses:

```text
S(W/m²) = EIRP_average * reflection_factor / (4*pi*r²)
r_required = sqrt(EIRP_average * reflection_factor / (4*pi*MPE(W/m²)))
```

Free space uses factor 1.0; the selectable ARRL typical-ground approximation uses
2.56. Neither is a vehicle-specific electromagnetic model.

## FCC MPE table

Calculator v1 implements the power-density column and averaging windows in
47 CFR 1.1310(e)(1), Table 1, checked 2026-10-12. `f` is MHz and density is
mW/cm².

| Frequency | Controlled (6 min) | Uncontrolled (30 min) |
| --- | ---: | ---: |
| 0.3–1.34 MHz | 100 | 100 |
| >1.34–3 MHz | 100 | 180/f² |
| >3–30 MHz | 900/f² | 180/f² |
| >30–300 MHz | 1.0 | 0.2 |
| >300–1500 MHz | f/300 | f/1500 |
| >1500–100000 MHz | 5.0 | 1.0 |

The result always presents both environments and never labels an estimate
compliant, noncompliant, safe, or unsafe.

References: [47 CFR 1.1310](https://www.ecfr.gov/current/title-47/chapter-I/subchapter-A/part-1/subpart-I/section-1.1310),
[ARRL RF Exposure Calculator](https://www.arrl.org/rf-exposure-calculator), and
[ARRL instructions](https://www.arrl.org/rf-exposure-calc-instructions).

## Mandatory limits and remaining acceptance

This plane-wave result is not a compliance finding, safety finding, engineering
certification, or substitute for a station evaluation. A verified driver distance
is only one input and does not verify any passenger or public distance. Near-field
coupling, vehicle roof/body/glass, feedline, occupants, nearby metal, antenna
pattern, ground/mounting geometry, simultaneous sources, and directionality can
materially change exposure. ARRL identifies special near-field limitations,
including antennas less than 20 cm from a person.

Before operational reliance, the owner must supply and review real catalog,
installation, loss, gain, mode, scenario, front-seat, and public-distance records;
compare results with the current ARRL reference using identical inputs; investigate
differences; evaluate near-field/vehicle geometry and aggregate sources; and perform
installed 1280x720 readability acceptance. No live RF test is required or
authorized by this subsystem. No Forge, hardware, deployment, service restart, or
production change is part of this work. For the mobile example specifically, the
owner must still confirm whether 30, 17, or 12 m should be supported; retain a
datasheet that maps the generic antenna's stated gain to 70 cm; establish applicable
feedline, connector, and duplexer losses; measure/verify passenger and public
geometry; evaluate aggregate/multiantenna exposure; and review the actual mounting
position.


### October 13 owner update: occupancy, public distance, and CF-4160J
Rolling Thunder normally operates with only the driver: the front-passenger seat holds the monitor and the rear holds POTA equipment; no passenger has ridden in it over the past three years. This is an operational practice, not a guaranteed exclusion of people.

The owner proposes an **actively monitored minimum public separation of 6 ft (1.8288 m) from the radiating antenna**, particularly while parked. The 12-ft width of a traffic lane is not proof of a six-foot antenna-to-person clearance, and a public member closer than 6 ft invalidates that operating condition. The mobile example has separate hypothetical/unverified 6-ft public exposure scenarios alongside the verified 90-in/64-in/84-in driver-distance cases. A six-foot operating boundary is NOT a finding of FCC compliance. An RF assessment must still satisfy the general-population/uncontrolled limits, reflect radiating near-field behavior where relevant, and account for other transmitters if operated simultaneously.

Operator-reported Comet CF-4160J nominal specifications: low-pass 1.3–170 MHz, max insertion loss 0.1 dB; claimed typical 0.07 dB at 52 MHz and 0.14 dB at 148 MHz (**apparent conflict** with the stated 0.1 dB maximum). High-pass 350–540 MHz, max insertion loss 0.2 dB; claimed typical ~0.14 dB at 420–450 MHz. A maximum insertion loss cannot be subtracted as guaranteed minimum attenuation in a conservative exposure evaluation. Both duplexer segments remain unknown (loss_db: null), as do all coax losses. Do not mark losses_complete: true without validated data.


### Read-only conservative screening display (pre-deployment)
When the authoritative cable/duplexer loss inventory is missing or incomplete, the
pure application service may publish an additional explicitly labeled *zero-loss
screening estimate* using 0 dB on every listed passive segment. It never mutates
the manual YAML or the actual incomplete regulatory advisory. A screen is produced
only when all other required gain, band, and source references are valid. This
simple far-field result is not a safety verdict, near-field assessment or proof
of FCC compliance. Missing loss data remain visible and the normal result remains
INCOMPLETE. No radio power/CAT/PTT authority is added.


### Display wording refinement
For available zero-loss screening results the read-only screen uses **BASED ON
ARRL RF EXPOSURE CALCULATOR** and displays the estimated distance and MPE
percentage with an explicit 0 dB cable/duplexer-loss assumption and
non-certification caveat. The underlying actual result remains
`inputs_complete=False`, and scenarios without valid screening estimates still
show incomplete/missing-input diagnostics.
