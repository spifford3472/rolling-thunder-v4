# FT8 Decoder Bake-Off — Checkpoint 3

Status: in progress  
Date started: 2026-09-29  
Rolling Thunder base: `3e4640c8f76b7fa69473660809f796b8c40cc57c`

## Safety boundary

This checkpoint is saved/reference-WAV receive decoding only.

It does not open the DigiRig audio device, compose an FT8 production worker,
control CAT transmit, key PTT/MOX/RTS/DTR/HID, generate transmit audio, transmit
RF, execute a real QSO, or log a successful FT8 contact.

## Candidate identity

Do not confuse the similarly named projects below.

| Role | Project | Revision used for initial evaluation | License | Notes |
| --- | --- | --- | --- | --- |
| candidate | `kgoba/ft8_lib` | `9fec6ca39886edbf96f4f5e71edc76da5074e871` | MIT | C decoder/encoder; example `decode_ft8` accepts WAV input |
| candidate | `rtmrtmrtmrtm/ft8mon` | `1b36a1336255a140516d32f4665b6e006eb82157` | MIT | C++/FFTW receive decoder; `-file` accepts WAV input |
| oracle | official WSJT-X | 3.0.2, released 2026-06-18 | GPL | comparison/reference only |

The separate PyPI project named `ft8lib` is not the `kgoba/ft8_lib`
candidate and must not be substituted without a fresh licensing review.

## Project-owned decoder contract

Checkpoint 3 adds `FT8PcmPeriod` and `FT8Decoder`.

`FT8PcmPeriod` contains an explicit existing `FT8Period`, a mono PCM sample
rate, and signed 16-bit PCM samples. Candidate-specific paths, process objects,
output records, FFT buffers, or native types do not escape the adapters.

Every successful result is an existing project-owned `FT8Decode`. Because the
Checkpoint 2 model requires SNR, DT, and positive audio frequency, a backend
must provide values that can be normalized to those fields. The model is not
weakened to accommodate a decoder.

## Initial adapters

- `Ft8monDecoder` serializes the project-owned PCM period to a temporary WAV,
  invokes `ft8mon -file`, and normalizes decoder lines.
- `Ft8LibDecoder` serializes the same PCM period to a temporary WAV, invokes
  `decode_ft8`, and normalizes its WSJT-X-like example output.
- subprocess failure, start failure, and timeout become `FT8DecoderError`.
- unrecognized lines are ignored rather than escaping backend-specific state.
- partially understood FT8 text is retained as `FT8MessageKind.OTHER`.

These adapters are not composed into `ApplicationRuntime`.

## Reference corpus

The corpus is not yet committed. Before adding binary WAV fixtures, confirm the
redistribution rights. If redistribution is unclear, retain only scripts,
checksums, expected decode manifests, and reproducible acquisition/generation
instructions.

Each sample must be associated with an explicit `FT8Period`; the WAV filename
or decoder timestamp must not become a second parity authority.

## Benchmark matrix

For every corpus period record decoded messages, missed oracle messages,
additional messages, elapsed decode time, CPU, peak/approximate RSS,
malformed/error behavior, and decoder parameters for WSJT-X, kgoba/ft8_lib,
and ft8mon.

Backend selection remains pending until the same saved/reference WAV workload is
measured on `anvilmobile`.

## Raspberry Pi experiment isolation

The Pi benchmark must use an experimental worktree/venv and must not repoint or
modify `rolling-thunder.service`.

Before installing a native package or Python dependency on the Pi, add the exact
package, location, purpose, and removal command to `docs/V4.3_ROLLBACK.md`.

No live ALSA/PipeWire/DigiRig capture is permitted in Checkpoint 3.


## Raspberry Pi build result

On `anvilmobile` (aarch64, Debian 13), both pinned candidates built successfully.

- `kgoba/ft8_lib` at `9fec6ca39886edbf96f4f5e71edc76da5074e871`
  built its `decode_ft8` executable and completed its bundled encode/decode
  test suite successfully.
- `rtmrtmrtmrtm/ft8mon` at
  `1b36a1336255a140516d32f4665b6e006eb82157` built an ARM64 executable
  successfully with the stock Makefile against FFTW, libsndfile, PortAudio,
  libstdc++, and libc.

The production service remained active and pointed at
`/home/geoff/projects/rolling-thunder-v4`. No live audio device, CAT/PTT
operation, or RF transmission was used during either build.

The pinned `ft8_lib` repository also contains recorded WAV fixtures paired
with text result files. These are suitable for the first same-input candidate
comparison; their text files are treated as repository-provided reference
results, not as a substitute for the later independent WSJT-X oracle.


## Preliminary saved-WAV smoke result

A first direct Pi smoke test used
`test/wav/191111_110115.wav` from the pinned `kgoba/ft8_lib` checkout.

The paired repository result file contains the expected message
`GJ0KYZ RK9AX MO05`.

Observed on `anvilmobile`:

- pinned `kgoba/ft8_lib/decode_ft8`: completed successfully but decoded zero
  messages;
- pinned `ft8mon`: decoded the expected `GJ0KYZ RK9AX MO05` message and one
  additional hashed/partial message.

The `ft8_lib` repository's own `utils/run_tests.py` invokes
`./decode_ft8 WAV` with the same basic command form, so the zero-decode result
is not explained by an obvious missing command-line option.

The actual pinned `ft8mon` output format includes an additional
`correct_bits` column between SNR and DT and uses fractional audio frequency.
The Rolling Thunder adapter was updated to normalize that pinned output rather
than relying on the older README example format.

This is preliminary evidence only. Backend selection remains pending a broader
same-WAV corpus and independent WSJT-X comparison.


### First measured Pi smoke timing

On the same `191111_110115.wav` fixture:

- `kgoba/ft8_lib/decode_ft8` returned zero decodes in about 0.051 seconds.
- `ft8mon` returned two decodes in about 5.49 seconds, including the expected
  `GJ0KYZ RK9AX MO05` message.

This illustrates the expected tradeoff that Checkpoint 3 is intended to measure:
the lightweight decoder is dramatically faster on this sample, while the
heavier decoder recovered the known signal. One sample is not sufficient for a
backend decision; the broader corpus and independent WSJT-X oracle remain
required.


## Round 1 same-WAV comparison

Five saved WAV periods from the pinned `kgoba/ft8_lib` repository were decoded
by both candidates on `anvilmobile`. Across the paired repository text files
there were 79 reference messages.

| Backend | Reference matches | Missed | Unmatched decodes | Recall vs repository text | Total wall time |
| --- | ---: | ---: | ---: | ---: | ---: |
| `kgoba/ft8_lib` | 55 | 24 | 8 | 69.6% | 0.4584 s |
| `ft8mon` | 61 | 18 | 21 | 77.2% | 27.0298 s |

On this five-period sample, `ft8mon` matched 6 additional reference messages
(7.6 percentage points more recall) but required about 59 times the aggregate
wall-clock time.

The unmatched-decode counts are **not** treated as false-positive counts. The
paired text files come from the `ft8_lib` repository and are useful for a
reproducible same-input comparison, but they are not an independent truth set.
The exact same WAV periods must be compared with the pinned/current WSJT-X
reference before classifying misses or extras as decoder errors.

Production remained active from
`/home/geoff/projects/rolling-thunder-v4`; this round used saved WAV files
only and did not open live audio or issue CAT/PTT/RF actions.


## WSJT-X 3.0.2 oracle smoke test

The official WSJT-X 3.0.2 ARM64 AppImage was extracted in the experimental
tools directory and its bundled standalone `jt9` decoder was run in FT8 deep
mode against `test/wav/191111_110115.wav`.

Observed:

- WSJT-X 3.0.2 `jt9 -8 -d 3`: decoded
  `GJ0KYZ RK9AX MO05` at 1234 Hz, matching the repository reference message;
  wall time was about 8.84 seconds.
- `ft8mon`: decoded the same expected message plus one additional
  partial/hashed message.
- `kgoba/ft8_lib`: decoded zero messages on this period.

This establishes that the first `ft8_lib` miss is a real miss relative to the
independent WSJT-X oracle, while the additional `ft8mon` message remains
unconfirmed and must not yet be labeled a false positive.

The oracle run used saved WAV input only. WSJT-X GUI, live audio, CAT/PTT, and
RF were not used.


## Three-way WSJT-X oracle comparison

The same five saved WAV periods were decoded on `anvilmobile` by both
candidate backends and by the official WSJT-X 3.0.2 standalone `jt9`
decoder in FT8 deep mode.

Across those five periods, WSJT-X decoded 88 distinct message texts.

| Backend | Matches vs WSJT-X | Missed vs WSJT-X | Extra vs WSJT-X | Recall vs WSJT-X | Total wall time |
| --- | ---: | ---: | ---: | ---: | ---: |
| `kgoba/ft8_lib` | 62 | 26 | 1 | 70.5% | 0.4617 s |
| `ft8mon` | 70 | 18 | 12 | 79.5% | 26.8744 s |
| WSJT-X 3.0.2 oracle | 88 | — | — | 100% reference | 69.2605 s |

On this corpus, `ft8mon` recovered 8 more WSJT-X messages than
`kgoba/ft8_lib`, a 9.0 percentage-point recall advantage, while taking about
58 times longer in aggregate.

The candidate "extra vs WSJT-X" counts are disagreements with this specific
WSJT-X deep-decoder run, not proven RF false positives. Several `ft8mon`
extras are alternate hashed/partial renderings of messages that WSJT-X rendered
with `<...>`; those require semantic normalization before treating them as
independent false detections.

### Interpretation

- `kgoba/ft8_lib` has a very large latency/resource advantage and a clean,
  simple standalone saved-WAV path, but on this corpus it misses materially more
  WSJT-X decodes.
- `ft8mon` is substantially more sensitive on this corpus, but its roughly
  5.2-5.5 second per-period runtime is a significant Raspberry Pi budget and its
  output needs normalization for its `correct_bits` field and hashed callsign
  representations.
- WSJT-X 3.0.2 remains the reference/oracle, not the intended embedded backend.

The final primary-backend decision must weigh this measured sensitivity gap
against real-time period budget, CPU/memory measurements, integration
complexity, licensing, and maintainability. Decode count alone is not the
selection criterion.


## Final Pi performance measurements

The five-period corpus was rerun with per-process resource accounting after the
project-owned PCM boundary was changed to compact immutable S16LE bytes.

| Backend | Total wall | Total CPU | Peak RSS |
| --- | ---: | ---: | ---: |
| `kgoba/ft8_lib` | 0.4364 s | 0.4304 s | 7,952 KB |
| `ft8mon` | 26.8534 s | 86.3105 s | 31,376 KB |
| WSJT-X 3.0.2 oracle | 68.6970 s | 68.6755 s | 71,936 KB |

On the individual periods, `ft8_lib` completed in roughly 0.06-0.10 seconds.
`ft8mon` required roughly 5.2-5.5 seconds of wall time and about 16.5-17.8
CPU-seconds per period, demonstrating significant multi-core CPU demand on the
Pi. WSJT-X deep decoding was intentionally used only as an oracle.

## Checkpoint 3 backend selection

**Initial primary backend: `kgoba/ft8_lib`.**

This selection is based on the complete Checkpoint 3 criteria rather than
decode count alone:

- it has substantially lower latency, CPU demand, and memory footprint;
- its saved-WAV interface is deterministic and simple to isolate;
- it is MIT licensed and small enough to understand/vendor or build
  reproducibly;
- it normalizes cleanly into the project-owned `FT8Decode` boundary;
- its sub-second Pi decode time leaves substantially more timing margin for the
  future slot-driven QSO state machine and for the rest of Rolling Thunder's
  map, radio, GPS, networking, and UI workload.

The selection has an explicit sensitivity limitation: on the five-period
WSJT-X 3.0.2 oracle corpus, `ft8_lib` matched 62/88 oracle messages (70.5%),
while `ft8mon` matched 70/88 (79.5%). The project therefore retains
`ft8mon` as the higher-sensitivity comparison/fallback candidate for later
experimentation.

This is an **initial integration choice**, not a claim that `ft8_lib` is the
most sensitive FT8 decoder. Checkpoint 4 live-receive testing may revisit the
choice if real DigiRig audio demonstrates that the sensitivity gap materially
harms the operating workflow or if a different backend can meet both
sensitivity and slot-latency requirements.

WSJT-X remains reference/oracle only and is not selected as a Rolling Thunder
runtime dependency.

### Selection caveats

- The corpus is small: five recorded periods and 88 WSJT-X message texts.
- WSJT-X text output is treated as the comparison oracle, not metaphysical RF
  truth; candidate-only decodes are disagreements, not automatically proven
  false positives.
- `ft8_lib`'s example decoder SNR is an approximation and must not be treated
  as directly calibrated to WSJT-X SNR.
- No conclusion from Checkpoint 3 authorizes live audio, QSO execution,
  transmission, CAT keying, PTT, or RF.
