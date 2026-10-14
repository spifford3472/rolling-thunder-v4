# Rolling Thunder mobile ARRL-style exposure screening — revised October 13, 2026

**Not a determination of FCC compliance or a legally established minimum separation distance.** This documents a pure far-field/plane-wave screening calculation only. No CAT/PTT/power changes, runtime UI changes, production config, merge or deployment.

Input: `config/antenna-reference.mobile-example.yaml` at commit `320247a`; computation uses the same FCC MPE functions and `arrl_typical_ground` reflection factor (2.56) as `rf_exposure_calculator.py`. No cable or duplexer loss credit (0 dB screening assumption). General public/uncontrolled FCC limit and 30-minute fraction is used for *both* the proposed six-foot public boundary and driver screening, without presuming occupational/controlled eligibility. Mode RF duty: heavily processed SSB 0.5, FT8 1.0, FM 1.0. Operator transmit-time fraction: 0.5 for every mode. Powers: 100W SSB, 70W HF FT8, 50W 2m FM, 15W 70cm FM. Gain: user-supplied ATAS -10/-5/0 dBi, confirmed manufacturer Comet SBB-224 2.15 dBi (2m), nominal 70cm 3.5 dBi (datasheet mapping pending). 6m FT8 is unsupported and excluded.

## Six-foot hypothetical public exposure screening

| Mode | W | Estimated uncontrolled MPE distance, ft | Ratio at 6 ft |
|---|---:|---:|---:|
| 40m SSB | 100 | 0.39 | 0.0043 |
| 40m FT8 | 70 | 0.47 | 0.0061 |
| 20m SSB | 100 | 1.39 | 0.0538 |
| 20m FT8 | 70 | 1.65 | 0.0753 |
| 15m SSB | 100 | 2.08 | 0.1205 |
| 15m FT8 | 70 | 2.46 | 0.1687 |
| 10m SSB | 100 | 2.83 | 0.2227 |
| 10m FT8 | 70 | 3.35 | 0.3117 |
| 6m SSB | 100 | 5.24 | 0.7614 |
| **2m FM** | **50** | **6.71** | **1.2491** |
| 70cm FM | 15 | 3.56 | 0.3527 |

## Driver geometry (actual measured distances)

| Antenna | Measured separation | Most constraining modeled band/mode | Uncontrolled MPE ratio |
|---|---:|---|---:|
| ATAS-120A | 90 in (7.5 ft) | 6m SSB, 100W | 0.4873 |
| Comet SBB-224 | 64 in (5.333 ft) | 2m FM, 50W | **1.5809** |
| Generic 70cm | 84 in (7 ft) | 70cm FM, 15W | 0.2591 |

### Practical interpretation

- Under these assumptions, **2m FM at 50W is above the modeled uncontrolled power-density limit both at six-foot public separation and at the driver's measured 64 inches**.
- Since the modeled ratio scales linearly with transmitter watts, the **mathematical breakpoint at the driver** is `50 W / 1.5809 = 31.63 W`, whereas the six-foot public breakpoint is `50 W / 1.2491 = 40.03 W`. Neither breakpoint is a certified safe transmitter setting. **25 W** yields estimated driver fraction ~0.790 and public fraction ~0.625; **20 W** yields ~0.632 and ~0.500 respectively. These are screening-only options, not changes to current radio power.
- The configuration remains incomplete because feedline/duplexer losses are not established. Known positive passive insertion loss would generally reduce feedpoint power, but only actual verified data should be relied on.
- The six-foot public boundary is to be actively observed from the antenna to the closest member of public. Road-lane width does not guarantee this clearance. Normal occupancy is driver only, monitor in passenger position and POTA equipment in the rear.
- Distances estimated using far-field plane-wave geometry **may be invalid for close mobile antennas**, particularly at 2m/70cm. The vehicle body, mounting, ground plane and nearby people can alter fields. Potential aggregate RF exposure from any simultaneous transmissions is separate.
- Do not treat a modeled ratio below 1 as legal certification; FCC exposure compliance may require an installation-specific near-field assessment or measurement.

Reference links: https://www.ecfr.gov/current/title-47/section-1.1310 ; https://www.arrl.org/rf-exposure-calculator


## Operator-selected uniform 15W IC-2730A profile (2026-10-13)

Both 2m FM and 70cm FM evaluation scenarios now use **15W MED**, selected to minimize the risk of operator power-setting error. This is an RF reference configuration change, not a power control or interlock. The tables ABOVE are historical 50W 2m results and are **superseded for 2m** by the figures below.

Using the same 50%-transmit-time, 100%-FM-envelope, ground-reflection-factor 2.56, Comet SBB-224 2.15 dBi gain and **zero feedline/duplexer loss** screening assumptions:

- 2m FM 15W, six-foot hypothetical public boundary: uncontrolled MPE ratio **0.3747** (37.5%); modeled required distance **3.67 ft**.
- 2m FM 15W, measured 64-inch driver distance: uncontrolled MPE ratio **0.4743** (47.4%); modeled required distance **3.67 ft**.
- 70cm FM 15W unchanged: public six-foot ratio **0.3527** (35.3%), and driver 84-inch ratio **0.2591** (25.9%).

These are ARRL-style far-field estimates, NOT compliance or safety findings; close mobile antennas require review of near-field, vehicle coupling and total RF source exposure. Six feet must be maintained from the antenna to members of the public.
