# Audio and Voice Setup

Rolling Thunder uses ALSA capture and offline Vosk speech recognition for
push-to-listen callsign entry.

## ReSpeaker XVF3800

The vehicle installation uses a Seeed Studio ReSpeaker XVF3800 USB
4-Mic Array.

Validated settings:

```yaml
speech:
  enabled: true
  audio_device: plughw:CARD=Array,DEV=0
  model_path: /home/geoff/.local/share/rolling-thunder/models/vosk-model-small-en-us-0.15
  capture_duration_seconds: 5
  sample_rate: 16000
  channels: 2
```

The XVF3800 requires 16-bit little-endian, 16 kHz, two-channel capture.
Rolling Thunder captures both interleaved channels and averages each
audio frame to mono before passing the samples to Vosk.

The ALSA card name `Array` is preferred over a numeric card index because
USB card numbers can change when devices are added or removed.

## Hardware Validation

List available capture devices:

```bash
arecord -l
```

Record a five-second XVF3800 test:

```bash
arecord \
  --device=hw:CARD=Array,DEV=0 \
  --format=S16_LE \
  --rate=16000 \
  --channels=2 \
  --duration=5 \
  /tmp/respeaker-test.wav
```

A successful five-second recording is approximately 313 KB.

## USB Extension Compatibility

USB enumeration does not prove that an extension cable can carry
continuous USB audio.

During installation testing, one 16-foot active USB 2.0 repeater cable
allowed the XVF3800 to enumerate but caused recording to fail with an
input/output error. The resulting WAV file contained only its 44-byte
header.

A different extension cable completed the same recording successfully.
Any permanent USB extension must therefore be validated with an actual
audio recording before installation.

## Failure Handling

Missing audio devices, ALSA failures, capture timeouts, empty recordings,
and incomplete multichannel frames produce explicit speech-recognition
errors. Speech recognition does not create radio transmit authority.
