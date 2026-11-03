# Tron offline voice control — issue #374

## Status

Tron now has a production-shaped, offline microphone worker and a Tk-owned
command dispatch path. The feature is disabled by default and is not accepted
for production use until the anvilmobile hardware checklist below is completed.
No resource measurements or live-microphone observations are claimed by this
source change.

## Architecture and ownership

- `tron_commands.py` defines the exact wake-prefixed command grammar and
  non-actuating intent model.
- `audio_capture.py` starts one `arecord` process per bounded recording,
  polls its pipe, caps bytes from duration/rate/channel settings, and terminates
  and reaps its process group on cancellation or every exceptional path.
- `speech_recognition.py` owns callsign recognition and a shared lazy Vosk
  model provider. The Vosk Python module and model load only when a worker first
  needs recognition, never on the Tk thread. Each utterance gets its own
  recognizer while sharing the model.
- `tron_microphone.py` owns one background capture/recognition loop, a bounded
  event queue, retry backoff, and callsign priority adapter.
- `tron_audio_gate.py` and `tron_capture_coordinator.py` provide exclusive
  ownership. A physical callsign request reserves priority, signals Tron
  cancellation, and starts callsign capture only after the Tron callback exits
  and its recorder has been reaped. The callsign controller releases ownership
  from its completion callback after its own capture returns.
- `ui_main.py` owns only composition, countdown presentation, bounded event
  draining, and Tk-thread dispatch. It processes physical controls before Tron
  events and drops stale generations after preemption. Recognized commands use
  the existing context navigation and active-panel controller.

No voice intent can transmit, press PTT, change RF power, start an FT8 QSO,
commit a contact, or edit configuration.

## Microphone and model configuration

The deployed speech configuration observed during issue work selects the
reSpeaker XVF3800 capture device as `plughw:CARD=Array,DEV=0`, 16 kHz stereo;
the Vosk adapter downmixes to mono signed 16-bit PCM. The existing callsign
capture uses this same input. FT8 capture is configured on the separate C-Media
device `plughw:CARD=Device,DEV=0`. These assignments were read from the
anvilmobile configuration and ALSA device list; no live capture test was run.

The model path is:

```text
/home/geoff/.local/share/rolling-thunder/models/vosk-model-small-en-us-0.15
```

Example opt-in configuration:

```yaml
speech:
  enabled: true
  audio_device: plughw:CARD=Array,DEV=0
  model_path: /home/geoff/.local/share/rolling-thunder/models/vosk-model-small-en-us-0.15
  capture_duration_seconds: 8
  sample_rate: 16000
  channels: 2
tron:
  enabled: true
  capture_duration_seconds: 5
```

`tron.enabled` defaults to false and requires enabled speech configuration at
16 kHz. Even when enabled, the worker does not start automatically. Press F12
in the dashboard to begin a manual acceptance session or stop listening. A
visible 30-second preparation countdown begins first; the shared Vosk model
warms on a background worker during this interval without opening the
microphone. After countdown and model preparation, say the displayed expected
command, `Tron status`. Pressing F12 during countdown cancels it. A callsign
button press also cancels the countdown; callsign audio may start while the
model worker finishes because Tron has released microphone ownership. F12 does
not initiate a transmission.

## Supported commands

Every command requires the exact wake word `Tron`. The bounded Vosk grammar
accepts these navigation and read-only phrases:

- Tron help, status, or current screen
- Tron show POTA, DX, Browse, FT8, Weather, Repeaters, DMR, log, or settings
- Tron next / next station and previous / previous station
- Tron first station and last station
- Tron select station / choose station

Movement is routed through the existing active-panel controller. Station-edge
movement is bounded to 64 UI selection steps; if the list exceeds that bound,
feedback reports that movement stopped before the edge. In weather, next/previous scrolls
the existing alert viewport. Commands do not tune Browse, change settings,
configure a repeater, or activate a selected spot. Selecting a station only
highlights it; on FT8 it never calls `activate_selection()` or the QSO
authorization callback. The existing physical controls remain responsible for
approving or rejecting a QSO. Unsupported, unprefixed, or expanded phrases fail
closed.

## Callsign priority and shutdown

The physical callsign button goes through the existing operator command and
capture workflow. When Tron owns the microphone, its cancellation event is set
immediately. Audio polling notices cancellation within approximately 50 ms,
then terminates/reaps `arecord`; callsign capture begins only after ownership
is promoted. Callsign recognition and Tron recognition never run at the same
time. Repeated callsign presses are rejected while a request or capture is
already active. If Tron has not yielded within two seconds, the status bar
reports that callsign is waiting; the reservation stays held and no overlapping
capture starts. Shutdown signals and joins callsign and Tron workers from the
background cleanup thread, not Tk.

If ALSA is unavailable, the service reports a concise microphone status and
retries after a bounded delay. It does not retain PCM between attempts. A worker
exception fails closed and the next capture may retry. Cancellation or shutdown
does not start another recognizer until the active recorder exits.

## FT8 terminal return

The FT8 lifecycle remains the authority for terminal state and contact logging.
After `COMPLETED`, `ABORTED`, `RETRY_EXHAUSTED`, or `ERROR`, the terminal
result remains available for three seconds. The UI then calls the existing
`return_to_browser()` lifecycle once, even when another context is selected.
It does not change context, repeat contact logging, reset an active QSO, or
change transmit authorization. Existing manual return controls remain available.

## Automated validation

Hardware-free tests cover exact grammar, offline recognizer boundaries,
bounded PCM and process reaping, event queue saturation/current-generation
dispatch, callsign cancellation and priority, microphone disconnect handling,
shutdown, feature configuration, and the FT8 terminal timer. The repository
suite and CI results must be recorded against the final candidate SHA.

## Hardware acceptance and resource measurements

A controlled session on anvilmobile is still required. Before each live audio
test, the operator must see the full 30-second countdown and expected command.
Do not start a live session remotely over SSH. Test, without transmitting:

1. Tron status and Tron help.
2. Tron show FT8, Tron show POTA, and Tron show DX.
3. Callsign-button interruption while Tron is recording, followed by callsign
   recognition and safe listener resumption.
4. Microphone disconnect and recovery.
5. Normal physical-controller operation.
6. Continuous FT8 receive/decode while checking refresh p95/max and physical
   control latency.
7. Terminal return for completed, failed, retry-exhausted, aborted, and error
   QSO states using simulation or existing test hooks; do not transmit solely
   for acceptance.
8. Application shutdown during recording.

Record Pi CPU and RSS for Vosk, process/thread counts, swap change, arecord
cleanup, UI refresh p95/max, physical-control latency, FT8 period scheduling,
and decode continuity. These measurements have not yet been collected; the
feature must remain disabled until they pass the operator's limits.

## Deployment and rollback

Follow `docs/engineering/codex-deployment-workflow.md`. Merge and deploy only
after the exact final candidate has green CI, diff and documentation review,
production health/current-SHA and rollback verification, and the required
hardware safety gates. Deploy the verified merged 40-character SHA through the
approved `rolling-thunder-deploy` wrapper; never copy source files to
anvilmobile. Verify the running SHA and service health. The wrapper performs
health validation and rollback on failure; confirm its recorded rollback target
before deployment and report the actual resulting SHA/status.

## Known limitations

- Pi 4 CPU/memory impact and full-screen acceptance are unmeasured.
- The feature currently requires a configured 16 kHz speech input and Vosk
  model; it does not probe or select among audio devices automatically.
- F12 manual acceptance requires the Tron feature flag to be enabled by
  configuration. Continuous listening never starts at application startup.
- Status feedback uses the shared status bar and can be replaced by higher
  priority station alerts.
- Speech recognition accuracy, microphone placement, and recovery on the
  installed reSpeaker remain to be validated on anvilmobile.
