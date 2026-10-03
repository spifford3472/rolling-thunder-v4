# Rolling Thunder FT8 Operator Guide

Status: CP9.1 feature-branch operating guide source. This document is intended to become the basis for a printable in-vehicle operator guide after final production acceptance.

## CQ Browser Eligibility

The FT8 CQ browser is not a general decoded-station list.

A callsign appears only when:
- Rolling Thunder has decoded that station calling CQ; and
- the station remains inside the current CQ activity retention window.

Non-CQ traffic from a station that has never appeared as a CQ candidate does not create a browser row.

Once a station has entered the CQ browser, later non-CQ traffic may update its presentation and may extend its activity lifetime. A station is removed after six FT8 periods with no traffic of any kind.

New CQ stations are appended to the bottom of the existing list so the operator's selection does not jump unexpectedly.

## Callsign Colors and Markers

The callsign color describes the most useful current/prior state while the station remains an eligible CQ candidate.

- **Yellow** — fresh CQ. The station has been heard calling CQ once or twice.
- **White** — repeated CQ. The station has been heard calling CQ three or more times.
- **Gray** — the station previously called CQ but recent non-CQ traffic shows it is active with someone else.
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

## Controls

- Rotate encoder — move through eligible CQ stations.
- Short encoder press — start exactly one QSO with the selected station when FT8 transmit is enabled.
- Button 1 — cycle supported FT8 bands and tune the standard FT8 dial frequency.
- Button 4 during an active QSO — immediately abort the current FT8 QSO.
- Leaving the FT8 context aborts any active FT8 work before radio restoration.

## Radio Preparation

Before an authorized FT8 QSO can transmit, Rolling Thunder prepares and verifies the FT-891:
- FT8 dial frequency for the selected band;
- 20 W output power;
- SSB-BFO USB.

A preparation failure is fail-closed: no PTT and no FT8 transmit audio.

When leaving the FT8 context, Rolling Thunder restores:
- 100 W output power;
- SSB-BFO AUTO.

## Safety Model

Rolling Thunder never automatically calls the next station. Every QSO requires an explicit operator selection.

Receive-only mode allows CQ browsing but cannot authorize RF transmission.
