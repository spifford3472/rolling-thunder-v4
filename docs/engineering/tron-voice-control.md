# Tron voice control — issue #374

## Scope and current implementation

This initial foundation is **not a deployable voice feature**. The pure
`tron_commands.py` module supplies a bounded, offline, non-actuating command
grammar and exact-match intent parser. No audio device, recognizer, UI command
dispatcher, or production configuration is wired. It cannot change radio state.

Commands require the explicit word "Tron" and support help, status, current
screen, and navigation requests. Screen labels are logical intents; integration
must resolve them through the existing approved application controller, not
direct widget mutation. Unknown, ambiguous, unprefixed, and transmitting/logging
phrases are rejected.

## Second implementation slice

`tron_recognition.py` now consumes externally supplied bounded 16 kHz mono
S16_LE PCM, passes a constrained grammar to an injected Vosk-compatible
recognizer, and returns a parsed intent or no command. It never opens a
microphone, dispatches navigation, or grants RF authority. Fake-recognizer
tests cover chunking, limits, malformed results, and failure isolation.

## Third implementation slice

`tron_audio_gate.py` provides an exclusive microphone ownership contract with
callsign-request priority. A callsign request blocks new Tron acquisition, but
an active Tron capture must still be cancelled and joined by its future worker
before callsign capture can acquire audio. No actual cancellation or live audio
ownership is wired yet. Tests verify exclusive claims and wrong-owner release.

## Next integration gates

1. Inspect callsign physical-button ownership, `LiveCallsignCaptureController`,
   `VoskCallsignRecognizer`, and all control consumers/tests.
2. Add one microphone arbitration owner; physical callsign capture takes
   priority and cannot be entered through Tron voice. Never capture concurrently.
3. Implement bounded asynchronous recognition and UI-thread-safe publication.
   Keep Tron disabled by default until hardware validation.
4. Validate Vosk memory and CPU on the Pi 4 (2 GiB), FT8 period deadlines,
   and UI responsiveness; test microphone disconnect, timeout, shutdown,
   repeated button presses, and callsign capture during Tron activity.
5. Add operator-visible mode/error feedback and update the operator guide
   when behavior becomes available.

## Safety, validation and rollback

No FT8 authorization, PTT, CAT, contact commit, or unattended RF path is
granted by this parser. This branch has no runtime integration, so rollback is
simply not merging it. When future integration is added, disable its typed
feature gate before reverting the deployment through the approved wrapper.
Run `ruff check .`, `mypy src/rolling_thunder`, `pytest`, and
`git diff --check`; require Pi hardware acceptance before merge/deploy.
