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
