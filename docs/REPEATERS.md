# Six-Meter Repeater Data

Issue #166 establishes the local six-meter repeater data/domain boundary before any repeater panel or FT-891 CAT work.

## Approved local source

The currently inspected deployment file is:

```text
data/repeaters/6m_repeaters.csv
```

It is intentionally **not committed to Git**. `data/` is already ignored by the repository, and the source provenance/redistribution license has not been established well enough to justify publishing the rows with Rolling Thunder.

The approved file inspected for checkpoint #166 has:

- SHA-256: `4fd61730528c264b0157447b78603aa478e905b3e409fcb861ee6631e91bcba1`
- 65 data rows
- exact headers, in order:
  - `Channel Name`
  - `Channel Type`
  - `Rx Frequency`
  - `Tx Frequency`
  - `Bandwidth (kHz)`
  - `RX Tone`
  - `TX Tone`
  - `Latitude`
  - `Longitude`
  - `Band`
  - `Active`
- all current rows are `Analogue`, 25 kHz, band `6`, and source `Active=Yes`
- RX frequencies span 51.620 through 53.970 MHz
- TX frequencies span 50.620 through 53.700 MHz
- RX and TX tones may be blank; a blank tone is represented as typed `None`

The local-source acceptance test verifies the exact SHA and row/schema facts when the file is present. CI skips only that deployment-file acceptance test because the source file is deliberately absent from Git.

### KB3AWQ source correction

The originally inspected 66-row file contained two records with the same stable identity for `KB3AWQ Williamsp` on 53.050 MHz receive / 52.050 MHz transmit. One row used TX tone 131.8 Hz and the other used TX tone 151.4 Hz.

The operator-maintained KB3AWQ/W3AHS repeater site documents the 53.050 MHz repeater as PL 131.8 and states that the PL tone is used on both receive and transmit. Based on that operator source, the 151.4-Hz duplicate was removed from the local deployment CSV. The surviving record is:

```text
KB3AWQ Williamsp,Analogue,53.05,52.05,25,131.8,131.8,41.217507,-76.9118507,6,Yes
```

Reference used for that correction:

```text
https://sites.google.com/site/kb3awq/W3AHS
```

The parser continues to reject duplicate stable identities rather than silently choosing between conflicting source rows.

## Parsing contract

`repeater_csv.py` reads the file without modifying it and fails closed on malformed or ambiguous action-critical values.

The parser:

- requires the exact approved header list and order;
- rejects extra CSV fields;
- converts MHz values exactly to integer hertz;
- requires RX and TX frequencies to resolve to the supported six-meter band;
- parses blank tones as `None` and nonblank tones as positive decimal values;
- validates latitude and longitude ranges;
- accepts only `Band=6`;
- accepts `Active` only as Yes/No (case-insensitive);
- accepts only the currently supplied analogue channel type;
- rejects duplicate stable repeater identities.

A loaded catalog retains the source filename and SHA-256 fingerprint for provenance diagnostics.

## Stable identity

Repeater identity never depends on CSV row position. It is derived from:

```text
normalized channel name + integer RX frequency
```

The serialized key is:

```text
6m:<RX_FREQUENCY_HZ>:<case-folded normalized channel name>
```

Whitespace and display-case differences therefore do not create a different identity. A real source change to the name or RX frequency does.

Catalog ordering is deterministic by RX frequency, normalized channel name, then stable identity.

## Typed repeater state

Each `RepeaterRecord` contains:

- stable identity;
- normalized channel name;
- callsign token from the first channel-name field token;
- analogue channel type;
- integer-hertz RX frequency;
- integer-hertz TX frequency;
- positive decimal bandwidth;
- optional RX tone;
- optional TX tone;
- validated fixed latitude/longitude;
- six-meter band marker;
- immutable source Active default.

Shift direction and offset are derived rather than duplicated:

- TX below RX -> `minus`;
- TX above RX -> `plus`;
- TX equal to RX -> `simplex`;
- offset is the absolute RX/TX difference in integer hertz.

No radio capability is inferred from these fields. Checkpoint #168 separately owns proving which FT-891 FM/repeater CAT capabilities actually exist.

## Active overrides

The source CSV remains immutable. Operator choices are stored in the normal Pi application SQLite database in:

```text
repeater_active_overrides
```

Schema version 11 keys each row by serialized stable repeater identity and stores only the explicit boolean Active override plus update time.

Effective Active is always:

```text
stored override, when present
otherwise source Active default
```

Clearing an override restores source-default behavior without rewriting the CSV.

## Nearby filtering

`RepeaterNearbyService` consumes an already-published immutable `GPSState`; it performs no serial I/O and owns no GPS polling.

A GPS fix is usable only when:

- the receiver is connected;
- a position exists;
- fix state is not `NO_FIX`;
- latitude and longitude are present;
- the fix timestamp is not older than the configured stale threshold.

The default stale threshold is 10 seconds, matching the current live-map GPS freshness policy.

With current GPS, great-circle distance is calculated using the Haversine formula. Repeaters at or within 50 statute miles are eligible. Repeaters outside 50 miles are excluded.

The returned nearby list includes both effective-active and effective-inactive repeaters. Each result carries `effective_active`; checkpoint #167 can therefore implement active-only versus all display without re-reading the source file.

Ordering is deterministic by:

1. distance;
2. RX frequency;
3. stable identity.

Missing or invalid GPS produces explicit `gps_unavailable` state. A fix older than the stale threshold produces explicit `gps_stale` state. Neither condition returns guessed distances or a last-known nearby list as current.

## Safety boundary

Checkpoint #166 adds no:

- Tkinter/UI work;
- encoder or physical-control routing;
- network access;
- CAT commands;
- radio mode/frequency changes;
- PTT, MOX, keying, tuner, power, or transmit authority.

The output of this checkpoint is local immutable typed data plus explicit persistence/filtering state for later checkpoints to consume.
