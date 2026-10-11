# FT8-P1 — safety ceilings and recommendation-only advisor

Initial slice adds a configuration-backed per-band power ceiling and a read-only empirical recommendation engine. Adaptive CAT power changes are NOT implemented or enabled; no PSK Reporter network calls are added.

- Baseline 20 W; configured automatic ceilings 10m 30 W, 12m 40 W and 15m 40 W.
- Live CQ selection and inbound response attempt seeds are clamped to band-specific policy before radio preparation.
- Strong observations from three distinct receivers on the same UTC day, at verified matching TX power, permit an advisory 5 W reduction. Weak or missing evidence never automatically increases power.
- Existing per-attempt telemetry records target/start/end/max configured power, but **not independently verified per-15-second transmission power**. That detailed transmission log and reception-time attribution is the next dependency before trustworthy model training.
- The radio CAT interface does not reliably identify physical-control overrides; automated adjustment remains disallowed until manual override behavior is explicitly verified.
- Other-band default ceiling remains 70 W as a legacy compatibility setting, configurable in policy. The first-session 20 W rule applies to the advisor, not the existing distance-based initial-power algorithm on bands outside the specified new ceilings.
- RF exposure limits depend on antenna/vehicle configuration. Do not interpret an advisor output as an RF compliance assessment.

No production deployments or raw XML cleanup in this checkpoint.

## P1.3 local durability checkpoint

For physical FT8 QSO transmissions the executor now reads configured CAT power before keying, records exact UTC keyed intervals, and appends each completed period to `ft8_transmit_period` in the Pi's existing SQLite storage database. Each QSO may contain multiple distinct emission rows. A readback failure is stored as unknown rather than guessed from an RF meter; the value is a *CAT configured setting*, not a calibrated wattage measurement. This is written after PTT release, is local only, and the existing per-QSO bounded in-memory records remain available.

**Still missing:** Crash-proof recording of an emission whose process dies before unkey, explicit operator physical-control override detection, reliable attachment of PSK Reporter observations to a specific emitted period, transfer of individual period records to Forge, and receiver-path calibration. These are rollout blockers for any adaptive power control. No live radio/Forge deployment is authorized by this checkpoint.

## P1.3 second slice — Forge persistence and correlation primitives

The independent `ForgeFT8PeriodRepository` stores individually sequenced emission records, returning an idempotent replay acknowledgement and rejecting changed replays. This is a storage contract and is **not yet connected** to the Forge HTTP endpoint or the Pi sync schedule. The read-only time/frequency attribution function requires an explicitly dial-aligned reception frequency, a unique bounded time match and verified CAT power. Real PSK Reporter records commonly report RF signal frequency rather than dial frequency, so frequency normalization and uncertainty analysis are required before production association. No quantitative reception percentages or automatic power changes are authorized by these primitives.

## P1.3 third slice — opt-in Pi-to-Forge emission delivery (development only)

The FT8 period repository now tracks per-emission acknowledgements independently of source records. An unacknowledged emission remains eligible for retry after connectivity loss or process restart. The existing FT8 performance sync scheduler invokes a bounded period upload pass. Each record uses a stable (QSO UUID, emission sequence) identity and receives an explicit accepted/already_exists response before marking local delivery complete.

The contact-sync application exposes POST /ft8-period and stores immutable observations in the separate Forge emission repository. It validates a bounded strict JSON envelope and idempotency key; mismatched or changed replays are rejected. **The route inherits the existing private-network Forge contact service's access assumptions; it does not implement new bearer-token authentication.** Do not expose this route on a public listener. Upgrade and smoke-test Forge first, then anvilmobile, as older Forge releases do not recognize /ft8-period.

Known rollout gates: review endpoint authentication and access controls; extend network integration tests; ensure persistent pre-key intention / crash-aborted emission state; test physical override and final RF safety boundary; validate PSK frequency attribution (provider RF frequency is not FT8 dial frequency); acceptance test on anvilmobile without transmitting. Adaptive CAT power remains disabled.

## P1.5 — upload credential hardening

The FT8 emission upload route now **fails closed** unless `ROLLING_THUNDER_FT8_PERIOD_TOKEN` is explicitly supplied to the Forge contact-sync process. It rejects missing or incorrect bearer credentials using timing-safe comparison. The Pi client also refuses to send until the token is present in its own environment. **The same dedicated high-entropy token must be provisioned separately to both isolated processes through their protected runtime secrets**, not checked into Git. Ordinary contact and terminal-attempt routes retain their current behavior. This is an application credential in addition to network isolation, not a replacement for WireGuard/firewall controls. No production configuration has been changed.

Safety gates still open: verify environment-variable injection via restricted systemd secrets without exposing tokens to logs; handle abrupt process crash with a durable pre-key intent/outcome; normalize reported PSK RF frequency with known audio offset before receiver correlation; review physical operator override and full transmit-boundary checks. Keep the PR in draft and auto power disabled.

## P1.6 — crash uncertainty and explicit RF frequency normalization

A durable `ft8_transmit_intent` entry is committed immediately before QSO PTT keying. If writing this entry fails, PTT is not requested. Once the executor completes and its emission history is appended, the intent is marked completed. Process crashes or PTT failures leave an *uncertain* intent across restarts; uncertain records are not counted as successful on-air transmissions. These intent records are Pi-local and are not currently sent to Forge. A sudden power failure during PTT still requires independent radio watchdog/timeout safeguards: database intent is forensic evidence, not RF shutoff.

Reception matching now optionally accepts an explicitly identified RF signal frequency plus a trusted audio offset, computing dial frequency = signal frequency - audio offset for USB FT8. Without the verified offset it refuses attribution; no inference from nearby band or approximate frequency is made. This is a primitive awaiting integration with the source data fields and source provenance review, not live PSK Reporter correlation. Existing read-only advisor and automatic power policy remain disabled for adaptive changes.

## P1.6 follow-up — atomic completion and executor cleanup

The Pi runtime now completes an intent and inserts its corresponding emission within one SQLite transaction, validating the immutable QSO, dial frequency, and CAT power setting. A failed insert or mismatch preserves the unresolved intent rather than falsely recording completion. The bounded executor clears its active flag even when release or persistence raises; a failed release does **not** create a confirmed emission. The separate legacy append API remains available for migration compatibility and tests. Physical RF watchdog and real hardware failure recovery remain separate acceptance gates; no production deployment is authorized.

## P1.7 — hardware-fake fault injection and encoder frequency audit

Hardware-free regression coverage now includes failure to commit pre-PTT intent (must not key), PTT key exception (intent stays unresolved), and SQLite completion failure (executor must recover for subsequent authorized attempts). These tests simulate ordinary process exceptions, **not** abrupt process death, power loss, independent radio PTT latch failure, or watchdog timing on real hardware.

The QSO session calls `encoder.encode(..., base_frequency_hz=context.target_audio_frequency_hz)` and the immutable `FT8Waveform` retains `base_frequency_hz`. The per-period SQLite schema, Forge upload contract, and `FT8TransmitPeriodTelemetry` currently retain **dial frequency only**, not this transmitted audio offset. Therefore a reception carrying PSK Reporter absolute RF signal frequency cannot yet be reliably attributed to one emitted waveform. The correlation helper's optional audio offset is caller-supplied and must **not** be populated from the received station's audio frequency or guessed band defaults. Verify transmit-side provenance, USB configuration, and provider-reported signal frequency semantics before enabling live attribution or ML training.

## P1.8 — optional transmitted audio offset throughout the evidence pipeline

New QSO emission telemetry takes the immutable `FT8Waveform.base_frequency_hz` from the encoder's TX waveform (not from received station audio), persists it as nullable `transmit_audio_offset_hz` in Pi and Forge SQLite, and sends it over the authenticated per-period upload. Existing databases use additive nullable-column migrations; old recordings remain unknown. Forge accepts older payloads omitting the field and retains legacy digest semantics for identical replays with unknown offsets. The offset is the waveform's **base tone frequency**, not a calibrated RF center nor guaranteed receiver frequency. No live PSK Reporter attribution or adaptive power control is enabled by this checkpoint; matching still requires verified RF frequency semantics, sideband, and time provenance.

## P1.9 — conservative RF reception matching (offline primitive only)

PSK Reporter documents the `frequency` field in hertz and `flowStartSeconds` as sender transmission time (Unix seconds), not provider query time. The reporting library may use communication center frequency when available, or fallback radio frequency; not every receiver has a guaranteed precise RF center. Offline attribution therefore uses the persisted transmit waveform base-tone offset on the emission side (`dial + offset` for compatible USB), with a bounded 10 Hz RF tolerance and 3 s timing window by default. Unknown TX offsets, unverified CAT power, or multiple matching emissions cannot be positive training examples. Caller-supplied reception audio offsets are refused for RF reports. This does not yet confirm radio sideband, receiver clock accuracy, record provenance, or provider sample timing in production. No live provider join, auto CAT changes, or RF operation enabled.

## P1.10 — immutable band safety maximums

The 10 m (30 W), 12 m (40 W), and 15 m (40 W) upper bounds are enforced by `FT8PowerPolicy.limit_for` even when the operator configuration omits a band key or supplies a higher value. Lower configured limits remain effective. The unknown-band advice path uses the strictest fixed ceiling. This hardens policy enforcement in the existing preparation and attempt-seed paths; it does **not** activate adaptive CAT power, discover physical front-panel overrides, or authorize direct legacy QSO fallback transmit paths. The 100 W restore-on-exit behavior remains separately documented and unchanged pending operator review.

## P1.11 — production legacy-authorization fallback guard

Both selected-CQ and inbound-response `ApplicationRuntime` entry points now refuse their legacy direct-QSO fallback when the radio adapter is the real `Ft891Radio` and the supervised `ft8_qso_start` preparation controller is absent. Injected test adapters retain the former fallback for hardware-free tests. The guard prevents bypassing the power/frequency safety ceiling due to missing runtime composition, but does not replace the required front-panel override audit. The existing 100 W voice restore on FT8 exit is unchanged and remains an explicit operator-review item.

## P1.12 — final CAT readback gate before PTT

The production-wired FT-891 hardware executor now receives the configured power policy and, after radio state verification and immediately before durable intent/PTT, requires a valid CAT configured-power readback. It rejects an unreadable/unknown setting, unsupported band, or a configured power above the band-specific policy ceiling without keying. This detects some front-panel overrides that raise configured power above the ceiling; it cannot detect a permitted-range front-panel adjustment or prove RF output watts, and it must not silently reset operator settings. Injection-only hardware-free executors retain compatibility without the optional policy. All such checks occur before PTT; no new automated power-changing code is enabled. The 100 W voice-mode restore on FT8 exit remains unchanged and requires separate operator acceptance. Watchdog release during physical radio fault or sudden host failure still requires a dedicated hardware acceptance gate.

## CP3 bounded automatic retry-power pilot

The first QSO attempt starts at configured initial power (20 W by default)
instead of distance-based initial-power thresholds. Every new attempt begins
with this conservative baseline, including the first attempt each local day.

When ft8.power.adaptive_enabled is true, the existing authorized QSO executor
may raise power in 5 W increments between repeated, identical grid-bearing
call messages. Report and 73 phases never trigger an increase. CAT readback
must confirm every power change before PTT. Manual power changes suspend
automation for the rest of the QSO, and all existing band caps and abort
protections remain in force. Default adaptive_enabled remains false pending
supervised operator-authorized configuration.

Evidence caveat: the DX ranking currently consumes Forge directional PSK
reports, but this pilot power controller does not yet consume directional PSK
measurements for calibrated target-specific wattage. Initial tuning is based
on unanswered repeated calls, not a contact probability. Gather several QSOs
and verified per-period power records to evaluate performance before enabling
broader power intelligence.
