# USB and recovery reliability audit — 2026-11-16

## Scope and evidence labels

This is a source-backed review of the current repository `main` snapshot
`3cfad7bc20a83a951617b0d45080af0064b85080` plus the open #478/#479 review
state observed on 2026-11-16. It does not describe the installed Pi as currently
operating. The 2026-11-15 `/dev/ttyUSB*` assignments and C-Media topology below
are historical host observations; the 2026-11-16 successful contact-sync field
test is owner-reported and is not USB, controller, GPS, or FT8 hardware
acceptance. The 12–13 November hub/audio incident remains cause-unresolved in
[`usb-ft8-incident-2026-11-13.md`](usb-ft8-incident-2026-11-13.md).

**Evidence key:** confirmed means directly established by source/tests; plausible
means the source boundary permits the scenario but there is no demonstrated
production occurrence; ruled out means the reviewed code/tests enforce the
specific property within the stated boundary. Likelihood and severity describe
risk under the scenario, not certainty that it occurred.

## Lifecycle map

1. **Composition and selection.** `ApplicationRuntime.from_config` builds one
   radio and GPS adapter from configured absolute device paths
   (`application_runtime.py:365-388`; `config.py:93-130`). Configuration validates
   absolute paths but does not require `/dev/serial/by-id`, verify USB serial
   identity, detect duplicate selection, or bind a physical function to a
   descriptor. Radio and GPS use distinct owner objects.
2. **Startup.** `ApplicationRuntime.start` synchronously starts radio polling,
   then FT8 receive, then calls GPS polling start
   (`application_runtime.py:1667-1710`). GPS polling opens and initializes the
   receiver in the caller before scheduling callbacks
   (`gps_polling.py:63-77`). The UI calls runtime startup before constructing the
   physical-control source/Tk loop (`ui_main.py:460, 786-792`). A slow GPS stream
   can therefore delay UI startup. Controller source open failure is printed and
   the application continues without physical controls.
3. **Normal I/O.** CAT uses one `Ft891Radio` owner and an `RLock`
   (`ft891_radio.py:104`); pyserial read and write timeouts are set from the
   configured timeout (`pyserial_cat_transport.py:42-52, 112-137`). GPS is
   read-only and scans at most the configured sentence count (default 32) with
   per-read timeout default 2 seconds and configurable upper limit 60 seconds
   (`config.py:75-77`, `serial_gps.py:265-290, 360-433`). Legacy controller
   reads are nonblocking and byte/event bounded (`serial_control_source.py:43-53,
   130-171`). Explicit `serial_v2` uses one worker as serial owner and health,
   retry, and expiring event-session state (`recovering_control_source.py:70-75,
   157-203, 223-330`). FT8 audio capture uses an ALSA subprocess and reader
   thread; audio errors publish degraded status and retry after a delay
   (`ft8/audio.py:76-150, 300-334`; `ft8/receive.py:255-287`).
4. **Disconnect/recovery.** GPS serial read errors close the failed handle; the
   polling service reports an error and retries connection on later polls
   (`serial_gps.py:360-383`; `gps_polling.py:87-124`). Radio polling owns CAT
   reconnect behavior. The versioned controller worker retries serial failures;
   legacy serial control drops its port after read error and has no reconnect
   loop (`serial_control_source.py:130-180`). FT8 capture reports degraded state,
   stops the failed subprocess, and retries; stop terminates, waits, then kills
   after bounded waits (`ft8/receive.py:266-287`; `ft8/audio.py:270-298`).
5. **Shutdown.** Runtime closes FT8 QSO/transmit services, stops radio polling,
   restores FT8 band settings, and disconnects the radio before the rest of
   services (`application_runtime.py:1805-1817`). It later stops GPS polling and
   disconnects GPS (`application_runtime.py:1872-1877`). On current `main`, the
   GPS poll cancellation is not an I/O quiescence barrier: `ThreadScheduledPoll`
   joins for a fixed short interval but does not report a still-live callback
   (`threading_scheduler.py:23-31`), while GPS stop returns after cancel
   (`gps_polling.py:79-101`). A still-blocked `readline` can overlap
   `SerialGPSReceiver.disconnect()` closing the same port (`serial_gps.py:335-354`).
6. **Operator recovery and physical boundary.** The software exposes controller
   health only for the versioned source and has bounded process-local recovery
   gates; none of these observations proves physical PTT release. FT8 release
   command success / `transmitting=False` is not physical de-key evidence. The
   owner’s operator override and restart-clears-process-lockout requirement
   remain documented in the parked REL-01 packet and STAB-05/FT8 recovery guides.
   No added USB behavior changes transmit authority.

## Candidate issue register

| Candidate and evidence | Scenario and impact | Likelihood / severity | Status | Deterministic offline regression design |
| --- | --- | --- | --- | --- |
| GPS poll cancellation is not a quiescence barrier; runtime unconditionally disconnects afterward. Evidence: `gps_polling.py:79-101`, `threading_scheduler.py:23-31`, `application_runtime.py:1872-1877`, `serial_gps.py:335-354, 360-383`; existing test `test_gps_stop_cancels_future_polls_but_not_a_blocked_inflight_read` explicitly allows the in-flight read to remain. | With a slow/blocked serial read, stop may close the descriptor concurrently with `readline`; error/state corruption and uncertain cleanup. Does not grant radio transmit authority. | Medium / Medium | Confirmed source race; no production occurrence established | Fake receiver blocks `refresh_state` on an event; invoke stop, verify it cannot claim quiescence; runtime fake asserts `disconnect` is not called while read owns the receiver; release the event and verify orderly close. A focused local fix and tests are prepared separately on `fix/gps-poll-shutdown-race` at `2dc53b6`; it is not merged and does not alter current `main`. |
| Configured serial paths may use volatile tty numbering and there is no identity/duplicate guard. Evidence: `config.py:93-111`; the 2026-11-15 installed-state snapshot observed radio CP2105 ttyUSB1, physical controls CP2102 ttyUSB0, GPS CP2102N ttyUSB3; those are historical only. Operator guides recommend stable by-id paths. | Enumeration order changes or simultaneous adapters can make a configured path absent or resolve to a different device. Startup/read failures are likely; wrong-device binding cannot be excluded by path validation alone. | Medium / High | Plausible | Fake udev/sysfs inventory with reordered tty numbers, stable serial/interface links, absent serial, and duplicate identities; assert preflight rejects ambiguous mapping and selects only exact expected interface. Never open real serial. |
| Initial GPS connect runs synchronously and can scan 32 sentences, each read using the configured timeout (2s default; max 60s). Evidence: `application_runtime.py:1667-1710`; `gps_polling.py:63-77`; `config.py:75-77`; `serial_gps.py:360-433`. | A slow/intermittent or mixed stream can delay dashboard startup before Tk is built; worst-case configured read budget can be long. No incident evidence establishes that this occurred. | Low to Medium / Medium | Plausible | Fake serial emits delayed unrelated sentences/no supported GGA; assert current startup bound and a future total-deadline/async-start contract. Also test empty reads and eventual valid GGA. No hardware. |
| Legacy physical-control serial source does not reconnect after read failure, and an open failure is only printed at startup. Evidence: `serial_control_source.py:100-113, 130-180`; `ui_main.py:786-793`. | A controller unplug/re-enumeration leaves physical controls unavailable until app restart; display may not provide ongoing health for this legacy mode. | Medium / Low to Medium | Confirmed behavior; operational defect plausible | Fake serial raises `SerialException` after open; assert port closes, buffer clears, no event dispatch, and status communicates unavailable. For a later reconnect design, simulate path reappearance and ensure no stale queued command replays. |
| CAT I/O has finite configured read/write timeout and shared operation lock, but both can be configured to 60s. Evidence: `config.py:73-74`, `pyserial_cat_transport.py:42-52, 112-137`, `ft891_radio.py:104`. | A slow CAT response can hold the owner lock and delay shutdown/recovery; current lock prevents concurrent device operations. Tests should verify waiting and timeout boundaries at supported configured values. | Low / Medium | Overlap ruled out by shared lock; long bounded delay remains plausible | Fake transport blocks then times out; start poll and shutdown/command concurrently; assert transport has one active operation, disconnect waits on owner, and all waits respect an explicit test deadline. Do not issue CAT. |
| FT8 C-Media/ALSA endpoint is configured by ALSA device string; device loss is retried, but host re-enumeration can invalidate a card name. Evidence: `ft8/audio.py:76-127, 270-334`; `ft8/receive.py:255-287`; historical USB incident reports C-Media errors `-28`, `-19`, and hub `-71`. | Audio capture/playback may degrade or restart after USB topology changes; exact causal relationship in the incident is not proven. Software audio state is not physical PTT confirmation. | Medium / Medium to High | Plausible topology/configuration risk; incident cause unresolved | Mock `Popen`, stdout EOF/EIO, `arecord` exit, and stop timeout/kill. Assert bounded cleanup, degraded state, retry policy and no QSO readiness while capture is absent. Playback fake must fail closed; no ALSA or RF. |
| MeshCore removal does not apply to current `main`. The live source tree still contains MeshCore components; PR #479 is a separate open draft. `meshcore_ohgo_panel.py` fetches OHGO from Forge; #479 proposal extracts/retains Forge-backed OHGO but does not itself stop/uninstall user services or remove data. | Treating the draft as deployed could leave independent MeshCore services/data running; current OHGO screen is still coupled in presentation naming, while its source data is Forge API. | Certain state distinction / low direct USB risk | Confirmed repository/PR state; no defect implied | Review tests/source on #479 exact head for OHGO HTTP endpoint, credentials and no MeshCore dependency; retain independent Forge endpoint contract. Avoid host/service operations. |

### Ruled-out properties in reviewed paths

- CAT query/write operations are serialized through the radio’s operation lock;
  transport configures both read and write timeouts, and reply parsing has a byte
  ceiling. This rules out concurrent CAT calls at that owner boundary, not OS
  driver stalls beyond pyserial’s configured behavior.
- Serial GPS parsing scans a finite number of lines, physical-control drains cap
  reads/events, and FT8 process stop has terminate/wait/kill and bounded thread
  joins. These local bounds do not prove the whole application shutdown is
  within one global deadline.
- OHGO obtains incident data through Forge API and remains independent of the
  MeshCore observation database; PR #479 is not current main or deployed state.

## Documentation drift and minimal reconciliation

- The REL-01 packet is titled with its 2026-11-15 preparation date and retains
  that dated baseline. Its opening now points to current main `3cfad7b`, PR #480’s
  Forge-only deployment, and the owner-reported 2026-11-16 test without changing
  the full Pi NO GO verdict. Historical 15-failure observations remain dated;
  the later resolution is stated once in the packet.
- The screenshot supports displayed CQ 4 / ITU 8 and displayed Ohio / EM79XM;
  it does not establish saved city/grid/state values. This remains explicit.
- PR #478 head `69b0b52` and CI run #4032 were checked before local reconciliation;
  #478 still needs rebase/update onto current main. #479 remains separate draft;
  its proposed MeshCore removal is not treated as current or deployed. The
  historical USB assignments are not promoted to current mappings.
- The FT-891 integration guide’s old ttyUSB2 observation is retained as dated
  evidence. Stable `/dev/serial/by-id` paths remain the configured operator
  guidance. No source index entry is needed because no modules were added on
  this documentation branch. The GPS shutdown fix branch separately updates the
  relevant GPS, ownership, contract, operator, and test-index documents.

## Prioritized remediation and acceptance

1. **P0 — GPS polling shutdown ownership.** Review and merge the separate narrow
   fix only after exact-head Ruff, strict MyPy, full pytest, inventory/local-link
   checks, and diff checks pass in CI. Accept only if a blocked fake read prevents
   receiver disconnect, stop reports non-quiescence, and later release allows
   cleanup. The current local fix passes targeted tests and static/documentation
   gates; its local full pytest is blocked by unrelated sandbox permission/key
   failures (see PR report), so it is not release-ready evidence.
2. **P1 — stable serial identity preflight.** Add a nonmutating diagnostic that
   records expected USB VID/PID, serial/interface identity and resolved path for
   radio, controls, GPS, and audio; fail closed on missing/duplicate/ambiguous
   matches. Acceptance uses reordered fake device inventories and confirms no
   device opens occur during preflight.
3. **P2 — startup and legacy controller visibility.** Bound GPS initialization
   by a total deadline or move it behind a clear UI startup boundary; expose
   controller loss/recovery for legacy mode or retire it only through a separately
   reviewed compatibility change. Test delayed GPS and unplug/replug using fakes.
4. **P3 — parked hardware evidence.** After separately approved exact-SHA
   production planning, perform receive-only GPS/controller/FT8 audio acceptance
   and document device identity, readiness, loss, recovery, and shutdown. Do not
   infer physical de-key from software state. No RF test is included here.

## Review boundary

This audit and the GPS code candidate are offline repository work only. No
production deployment or restart, service cutover, database mutation, physical
USB operation, CAT/PTT command, or RF transmission was performed.
