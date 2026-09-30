# FT8 Offline Encoder Reference — Checkpoint 5

Status: validation complete  
Date: 2026-09-29  
Backend: `kgoba/ft8_lib`  
Pinned revision: `9fec6ca39886edbf96f4f5e71edc76da5074e871`

## Safety boundary

Checkpoint 5 is offline-only. Validation does not open an ALSA device, serial
port, CAT session, PTT mechanism, or RF path. The encoder produces temporary
reference WAV data that Rolling Thunder immediately reads into immutable
in-memory PCM.

## Verified waveform properties

Observed and independently checked against the pinned implementation:

- 79 FT8 channel symbols
- 0.160 second symbol duration
- 6.25 Hz tone spacing
- 12.64 seconds occupied modulation
- 12 kHz sample rate
- mono signed 16-bit PCM
- 180,000 samples per padded 15-second slot
- 360,000 PCM bytes per slot

The pinned `gen_ft8` output reached signed-16-bit peaks of -32766 / +32767 in
the Raspberry Pi reference run. That is the encoder's current digital
normalization only; it is not a calibrated radio transmit level.

## Raspberry Pi reference run

Host: `anvilmobile`

All repository quality checks passed before the vector run:

- Ruff: passed
- MyPy: passed
- pytest: 2218 passed, 1 skipped
- `git diff --check`: passed

The following real `gen_ft8` outputs round-tripped through the pinned
`decode_ft8` backend exactly:

| Message | Packed payload | PCM SHA-256 | Encode + waveform | Decode |
| --- | --- | --- | ---: | ---: |
| `K1ABC KI5VNB EM79` | `09bde354baee568847c8` | `6b4701d3e353f12b9927c6a254379d33baaeae1b2a2b2692d6f3c020f4f784b3` | 21.382 ms | 59.670 ms |
| `K1ABC KI5VNB -10` | `09bde354baee569faa48` | `84a8853e2636c41c420372954340761cb743f34817439bfa4b140d0c1af2444e` | 12.663 ms | 41.967 ms |
| `K1ABC KI5VNB R-10` | `09bde354baee56bfaa48` | `b0fcd4f7a5163f14c7a8ef4277d9f6a11fb7889f29a9651cd0b3c42556371461` | 20.837 ms | 46.207 ms |
| `K1ABC KI5VNB RRR` | `09bde354baee569fa488` | `c8a077aaafe853da80fc03f283d8b9718892484d45bd9a936dee18d9389d0862` | 11.344 ms | 59.371 ms |
| `K1ABC KI5VNB RR73` | `09bde354baee569fa4c8` | `2232c04332476af898a68343f10ac9e985e56cd6757ec844aafa7548414e8800` | 11.608 ms | 56.580 ms |
| `K1ABC KI5VNB 73` | `09bde354baee569fa508` | `05bf11b382786a927ccf9ba4d82fa14773309fdb4aee22f78ceb6bd57bf0af55` | 21.998 ms | 53.050 ms |

Every message produced 79 tones, 180,000 samples, and 360,000 PCM bytes. Every
message decoded back to the exact original protocol text.

## Permanent vector test

`tests/test_ft8_encoder.py` contains the observed packed payload, 79-tone
sequence, and PCM SHA-256 for each message above. The real-backend vector test
is opt-in because CI does not install the native third-party executable.

To run it against the isolated pinned backend:

```bash
ROLLING_THUNDER_FT8_GEN_FT8=/home/geoff/projects/rolling-thunder-v4-cp3-tools/ft8_lib/gen_ft8 \
PYTHONPATH=src \
/home/geoff/projects/rolling-thunder-v4/.venv/bin/python \
    -m pytest -q tests/test_ft8_encoder.py
```

## Repeated-run performance and memory

A final 50-iteration Raspberry Pi run encoded `K1ABC KI5VNB R-10` at a 1500 Hz
audio base frequency. All 50 generated PCM waveforms had the same SHA-256:

`b0fcd4f7a5163f14c7a8ef4277d9f6a11fb7889f29a9651cd0b3c42556371461`

Observed encode + waveform latency:

- minimum: 10.905 ms
- median: 12.573 ms
- mean: 13.465 ms
- p95: 19.252 ms
- maximum: 21.003 ms

Observed output remained 180,000 samples / 360,000 PCM bytes on every iteration.

Approximate maximum resident set size reported by Python `resource.getrusage` was
30,036 KiB for both the Python process and child-process accounting in this run.
That figure is suitable as a coarse Raspberry Pi process-memory observation, not
as a precise per-component allocation measurement.

The opt-in pinned reference-vector test also passed all 21 encoder tests in
0.84 seconds, and `git diff --check` passed.

Checkpoint 5 performance acceptance is complete.
