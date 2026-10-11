# Rolling Thunder FT8 Operator Guide

Status: CP9.1 feature-branch operating guide source. This document is intended to become the basis for a printable in-vehicle operator guide after final production acceptance.

## CQ Browser Eligibility

The FT8 CQ browser is not a general decoded-station list.

A callsign appears only when:
- Rolling Thunder has decoded that station calling CQ; and
- the station remains inside the current CQ activity retention window.

Non-CQ traffic from a station that has never appeared as a CQ candidate does not create a browser row.

Once a station has entered the CQ browser, later non-CQ traffic may update
informational fields but does not extend CQ eligibility. Ages 0 through 5 are
visible; the station is removed when its most recent actual CQ reaches age six.

New CQ stations are appended to the bottom of the existing list so the operator's selection does not jump unexpectedly.

## Receive Diagnostics

The footer reports receive health without changing radio or transmit authority.
`RX OK` includes the most recent audio RMS level, raw decoder output-line count,
all parsed FT8 decodes, CQ decodes, and decoder runtime. `RX DEGRADED` identifies
unready/disagreeing clock sources, silence/very-low/clipping audio, dropped
periods, or capture/decoder/diagnostic errors.

During an explicitly configured bounded comparison session, a second line shows
`DIAG RUN` or `DIAG DONE`. `ALL primary/comparison` counts every parsed FT8
message from `ft8_lib` and `ft8mon` independently; `CQ primary/comparison` counts
only CQ messages. These figures are intentionally different from visible CQ
rows, which also follow CQ eligibility, expiry, and worked-today rules.

For the issue-237 morning run, comparison and sample retention stop at 05:15
America/New_York. Normal primary receive continues. At most three WAV samples
are retained in stable slots, and both decoders receive the same captured PCM.
The mode is receive-only and does not authorize or transmit RF.

## Callsign Colors and Markers

The callsign color describes the most useful current/prior state while the station remains an eligible CQ candidate.

- **Yellow** — the most recent actual CQ is age 0 or 1 FT8 periods.
- **White** — the most recent actual CQ is age 2 or 3 periods.
- **Gray** — the most recent actual CQ is age 4 or 5 periods.
- **Red + `!` marker** — Rolling Thunder attempted this callsign/band during the current UTC date and the attempt failed, timed out, exhausted retries, or ended in an execution/preparation error.
- **Blue + `■` marker** — the operator intentionally aborted an FT8 attempt with this callsign/band during the current UTC date.
- **Tree symbol** — the decoded CQ explicitly contained the POTA token.

The selected row uses a strong border/background highlight. Selection does not erase the callsign status color.

Attempt-history colors do not force a station to remain visible. If a failed or aborted station ages out, it disappears. If that station later calls CQ again on the same band during the same UTC date, it reappears with its red or blue attempt-history state.

## Successful Contacts

After a successfully completed FT8 QSO:
- the contact is logged through the normal Rolling Thunder contact path;
- the callsign/band combination disappears from the CQ list for the remainder of the UTC date;
- the same callsign on another band remains eligible;
- the callsign becomes eligible again on the next UTC date.

## Failed and Aborted Attempts

A failed or aborted FT8 attempt is not a normal contact and is not sent to Wavelog as a QSO.

It is retained as machine-analysis/performance telemetry so later analysis can use the outcome, reason, timing, SNR, grids, distance, power, SWR, ALC, and other recorded values.

After acknowledging the terminal FT8 result with the encoder switch, the browser returns to IDLE and the operator can select another station.

## Operator Authorization

Starting an FT8 QSO requires an explicit operator authorization for one eligible
CQ station.

In v4.3.0 the authorization action is:

1. select the desired station in the FT8 CQ browser; and
2. short-press the rotary encoder switch.

That deliberate press authorizes one bounded QSO with that station only.

A future voice-control implementation may provide the same authorization when
the operator issues an explicit station-directed command (for example, a command
to call a specific currently eligible CQ station). Voice must route through the
same station-selection and authorization checks as the rotary control. A wake
word, passive speech, ambiguous command, or background decode is not
authorization.

One authorization never carries forward to another station. A new QSO requires
a new explicit operator action.

## Controls

- Rotate encoder — move through eligible CQ stations.
- Short encoder press — start exactly one QSO with the selected station when FT8 transmit is enabled.
- Button 1 — cycle supported FT8 bands and tune the standard FT8 dial frequency.
- Context Button 3 during an active QSO — immediately abort the current FT8 QSO.
- Leaving the FT8 context aborts any active FT8 work before radio restoration.

When a decoded FT8 message is addressed to the configured local callsign while
the screen is in the browser, a large incoming-call alert replaces the CQ table.
It shows the caller, received SNR, and grid when known. Button 2 answers exactly
that caller; Button 3 ignores it. Repeated messages from an ignored or already
accepted caller do not repeatedly authorize a QSO. Incoming messages do not
interrupt active or terminal QSO screens.

After a completed QSO, repeats from that just-worked callsign are treated as
continuation traffic for the next six FT8 periods and do not immediately reopen
the incoming-call alert. A different callsign still appears immediately, and a
later genuinely new call from the worked station can appear after the cutoff.
Failed or aborted attempts do not use this continuation guard. If Button 2
cannot start the responder workflow, the alert remains visible.

Button 2 starts a responder exchange, not a new CQ call. If the accepted message
contains the caller's grid, Rolling Thunder's first transmission in the opposite
slot is a signal report. If the accepted message already contains a signal
report (for example `KI5VNB K0BQB -03`), Rolling Thunder retains that report and
its first transmission is the acknowledged `R_REPORT`. The normal final 73 and
bounded retry/safety checks still apply. Merely decoding either message never
transmits.

## Radio Preparation

Before an authorized FT8 QSO can transmit, Rolling Thunder prepares and verifies the FT-891:
- FT8 dial frequency for the selected band;
- one initial 20–70 W configured-power target derived from frozen local/remote
  Maidenhead-grid distance;
- SSB-BFO USB.

Unknown distance and paths through 3,000 km use 20 W. The thresholds then use
5 W steps at 4,500, 6,000, 7,500, 9,000, 10,500, 11,500, 12,500, 13,500, and
14,500 km; longer paths use 70 W. Power is prepared once. The QSO controller
does not continually overwrite an operator's later manual adjustment.

A preparation failure is fail-closed: no PTT and no FT8 transmit audio.

When leaving the FT8 context, Rolling Thunder restores:
- 100 W output power;
- SSB-BFO AUTO.

## Safety Model

Rolling Thunder never automatically calls the next station. Every QSO requires an explicit operator selection.

Receive-only mode allows CQ browsing but cannot authorize RF transmission.


## FT8 and voice microphone selection

FT8 entry automatically sets and verifies menu **11-05 SSB MIC SELECT = REAR**
(`MIC = 0`, `REAR = 1`). FT8 uses the rear DATA/RTTY audio path.
Returning from FT8 to Browse, POTA, or DX sets **11-05 = MIC** so ordinary SSB
voice uses the front microphone. The destination context is authoritative;
the prior menu value is not restored.

The existing typed FT-891 adapter owns CAT encoding and readback. FT8 receive
entry/band changes and pre-QSO preparation require REAR. A failed write,
malformed reply, or mismatched readback prevents QSO authorization; no PTT or
transmit audio is permitted through the preparation path. Existing USB,
11-07 SSB BFO, IPO/preamp, NAR, NB, power, and bounded transmit policy remain.

Shared exit/rollback cleanup attempts MIC even if another restoration fails.
Failed-QSO recovery that remains on the FT8 screen reapplies REAR; a requested
context exit skips that recovery. CAT-safe shutdown performs serialized normal
receive cleanup before disconnect. With CAT unavailable, restoration cannot be
confirmed: check 11-05 manually before voice operation. Hardware acceptance of
this change is still required.

### Selected-station activity in map status strip (CP3.1 Step 2)

While viewing FT8, the existing cyan-outlined map status strip displays the local QSO phase in white, including the selected or active callsign and per-phase attempt count when available. A green second line reflects only fresh decoder-attributed transmissions **from** that target: CQ, third-party directed exchange, report, or sign-off. Calls to the target from other stations do not prove the target is replying. The green line disappears when activity becomes stale or unknown; observed 73 is not proof of a completed QSO. The strip has no new controls and does not change retries, power, or transmit authorization.

### FT8 activity indicator and map banner (CP3.1 Step 2A)

The left FT8 header reports **RX RUNNING** while capturing, **DECODING** while the decoder is working, and **TX RUNNING** only during active FT8 executor PTT. Transmitting takes precedence over decoding. Stopped/degraded receiver states remain visible. The cyan map status banner now shows own-state white text to the left and fresh remote-station evidence in green to the right, on a single line. IDLE stays centered. Width budgeting keeps both messages separate without changing the banner dimensions.
