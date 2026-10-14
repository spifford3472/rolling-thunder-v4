# Rolling Thunder mobile antenna: zero-loss RF exposure screening (2026-10-13)

**This is NOT a finding of FCC compliance, nor a minimum safe distance.**
The antenna reference YAML remains the sole manually edited authority and is not changed by this screening. No power automation, transmission interlock, runtime/UI modification, deployment, or source-data mutation results.

## Screening assumptions and limits

- Input: config/antenna-reference.mobile-example.yaml at commit 60b85aa.
- Source: pure calculator math in src/rolling_thunder/rf_exposure_calculator.py, FCC MPE uncontrolled limits in 47 CFR 1.1310(e)(1), Table 1; frequency-specific, 30-minute general-population basis.
- **Zero dB attenuation** through all feedline and duplexer parts, as a deliberately conservative numerical screening bound when positive, passive component attenuation is unknown. This is not a measured or guaranteed component property. It does not account for feedline radiation or other emitters.
- Operator-supplied maximum forward powers: ATAS SSB 100 W and FT8 70 W; other mobile FM 50 W. All TX fractions are set to 0.5 over the time window. SSB RF-envelope factor is conservatively set to 1.0 while keyed; FT8 and FM 1.0.
- Antenna gain dBi as supplied: ATAS -10 (40m), -5 (20/15/10m), 0 (6m); dual-band generic 3.5 on 70cm (unconfirmed model-specific gain); Comet SSB224 2m gain is not supplied and **cannot be screened from this data**.
- Ground-reflection power-density multiplication 2.56, as configured in the engineering calculator. This is an assumption, not a vehicle-specific measurement.
- Public comparison uses an **operator-monitored six-foot antenna-to-person distance**, not a clearance guaranteed by traffic-lane widths. Driver is evaluated separately at measured ATAS 90 in, Comet 64 in, generic dual-band 84 in.
- No conclusion about near field, vehicle coupling, realistic radiation patterns, mobile use in traffic, combined simultaneous RF sources, or persons who enter the six-foot exclusion boundary.

## Model-derived uncontrolled exposure at hypothetical six feet

| Mode and band | No-loss model required distance | Model power density as proportion of FCC uncontrolled MPE |
|---|---:|---:|
| ATAS 40 m SSB / FT8 | 0.56 / 0.47 ft | 0.01 / 0.01 |
| ATAS 20 m SSB / FT8 | 1.97 / 1.65 ft | 0.11 / 0.08 |
| ATAS 15 m SSB / FT8 | 2.95 / 2.46 ft | 0.24 / 0.17 |
| ATAS 10 m SSB / FT8 | 4.00 / 3.35 ft | 0.45 / 0.31 |
| **ATAS 6 m SSB / FT8** | **7.40 / 6.19 ft** | **1.52 / 1.07** |
| Comet SSB224 2 m FM | **Not determined (gain unknown)** | **Not determined** |
| **Generic 70 cm FM** | **6.51 ft** | **1.18** |

Values greater than 1 are *model exceedances* under the stated assumptions; these are not regulatory determinations.

## Measured driver screening

At 7.5 ft from the ATAS, the most constraining given mode is **6 m SSB** at about 0.97 of the uncontrolled plane-wave limit. At 7 ft from the generic 70cm antenna, 70cm FM is about 0.86 of that limit. At 64 inches from the Comet SSB224, its unknown gain prevents even a numerical screening ratio. These comparisons use the **uncontrolled** limits to avoid assuming that the driver automatically qualifies for the occupational/controlled standards.

## Next required evidence and precautions

1. Confirm Comet SSB224 manufacturer gain at 144–148 MHz, explicitly dBi vs dBd. Do not invent.
2. Obtain verified cable attenuation data for specific RG316/RG58/RG8X manufacturer and construction, lengths, frequencies, connectors, and duplexer; **maximum** insertion loss must not be subtracted as guaranteed attenuation.
3. Verify that the antenna-to-person distance is measured from the closest part of the radiating structure and that six feet can actually be maintained in accessible locations.
4. Validate RF exposure with the appropriate near-field/mobile-antenna method or measurement if this simple far-field approximation is inadequate. Consider aggregate simultaneous transmitters separately.
5. Until a complete evaluation supports the proposed separation, do not rely on six feet at 6m 100W SSB, 6m 70W FT8, or 70cm 50W FM. Lower power or extend separation only under a properly validated evaluation.

Regulatory sources: https://www.ecfr.gov/current/title-47/section-1.1310 and https://www.ecfr.gov/current/title-47/section-97.13
