# Trusted GPS UTC

## Purpose

Checkpoint #158 extends the existing read-only GPS path so Rolling Thunder can expose receiver-provided UTC independently of the Raspberry Pi wall clock. This checkpoint does **not** set or adjust Linux system time; clock synchronization remains Checkpoint #159.

## Proven sentence source

The installed GPS stream already used by Rolling Thunder contains `GNRMC` and `GNGGA` sentences. Checkpoint #158 therefore uses checksummed RMC as the UTC/date source. ZDA is intentionally not treated as trusted until installed hardware observation proves it is needed and emitted reliably.

RMC provides:

- UTC time
- UTC date
- active/void navigation status
- speed and course already consumed by the serial adapter

GGA remains the authoritative current-position/fix sentence.

## Typed observation

`GPSState.utc` is a `GPSUTCObservation` with:

- `value`: receiver-provided timezone-aware UTC, or no value when unavailable
- `source`: currently `RMC`
- `valid`: the UTC came from a supported checksum-valid sentence and parsed calendar value
- `fix_valid`: both the RMC status and the current GGA fix are valid
- `advancing`: the receiver has emitted a later UTC sample than the previous accepted sample
- `fresh`: the latest advancing UTC sample is inside the bounded monotonic age window
- `age_s`: sample age measured from a monotonic clock
- `trusted`: derived true only when valid, fix-valid, advancing, and fresh are all true

No trust decision compares GPS UTC with `datetime.now()` or with the Raspberry Pi wall clock.

## Trust rules

The default maximum UTC sample age is five seconds.

A first valid RMC sample is **not trusted** because advancement has not yet been demonstrated. A subsequent later RMC sample establishes advancement.

Repeated duplicate UTC values do not refresh the monotonic receipt time. This prevents a receiver stuck on one timestamp from remaining falsely fresh.

A backward UTC sample clears the advancing criterion and does not replace the newest accepted UTC value. A later sample must move beyond the newest accepted value before trust can recover.

A void RMC status or a GGA no-fix state makes `fix_valid` false. Disconnect and error states clear the exposed UTC observation.

## Threading and authority

Serial/NMEA work remains in the existing GPS receiver and polling path. No Tkinter code performs serial work and no new network dependency is introduced.

This checkpoint has no authority to:

- write Linux system time
- change NTP configuration
- access Forge
- change radio state
- transmit

## Validation

Automated validation covers:

- valid RMC UTC/date parsing including fractional seconds
- void RMC handling
- malformed calendar/time rejection
- first-sample-not-trusted behavior
- advancement to trusted state
- duplicate timestamp freshness protection
- stale timeout using an injected monotonic clock
- backward timestamp rejection from the advancing sequence
- GGA no-fix trust rejection
- existing position, movement, disconnect, reconnect, polling, and recovery regressions

## `anvilmobile` acceptance

Before Checkpoint #158 is approved, inspect a short live NMEA sample from the installed GPS without changing receiver configuration.

Confirm that:

1. the receiver emits `GNRMC` or `GPRMC` with valid UTC/date fields;
2. UTC samples advance normally across consecutive sentences;
3. the corresponding GGA stream has an active fix;
4. Rolling Thunder reports a trusted UTC observation after the second advancing sample;
5. disconnect/reconnect clears trust and re-establishes it only after advancement is demonstrated again.

Record the installed result on the pull request. Do not merge without explicit repository-owner authorization for that exact PR.
