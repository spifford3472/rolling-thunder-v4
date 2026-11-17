# Parked USB/GPS/FT8 receive-only acceptance

**Status: NOT ACCEPTED — parked precondition met; receive-only evidence still outstanding.** This procedure records
what must be demonstrated on the installed AnvilMobile system before USB,
GPS, controller, or FT8 receive operation can be accepted. It grants no
deployment, service restart, database, USB manipulation, CAT/PTT, or RF
authority. A receive-only test must never start an FT8 QSO or key the radio.

## Current source and evidence boundary

The source baseline is merged `main` at
`a24d7d2a14cd1ea110696249e889a42fb0dc42c1`. PR #481 makes GPS polling stop
report whether a read has quiesced and prevents disconnecting a receiver that
may still be in use. The source and deterministic tests establish this
shutdown behavior; they do not establish that the installed AnvilMobile process
uses that source.

On 2026-11-17, an authorized read-only check through the owner of the user
systemd manager observed the Rolling Thunder system service active, serial
device paths enumerated, and a USB audio capture interface present. The
historically identified MeshCore receiver USB identity was absent. No fresh GPS
fix, live FT8 decode, or receive/de-key observation was collected. A second
remote-tool context used a different Unix account and could not see the owner's
user-level service state; use the owning account's manager for MeshCore checks.
Machine-specific identifiers and private paths are omitted from this public
record.

There is no verified running-code identity bound to the installed process. The
process currently launches from a mutable checkout. PRs #487 and #488 update
documentation and fix Forge-side SQLite URI handling; neither changes the
AnvilMobile runtime identity or receive readiness. Therefore this observation
cannot be accepted as evidence for the current source release.

## Latest read-only installed-state recheck — 2026-11-17

The system Rolling Thunder service was active with one dashboard MainPID in its
service cgroup and zero recorded service restarts. The running command uses the
existing editable checkout, whose clean Git revision predates current merged
`main`. The expected Tk-loop readiness heartbeat was absent. This is process and
checkout evidence only: it does not prove which Python modules are loaded, nor
that Tk, GPS, audio, or FT8 receive is ready. The deployment wrapper and one
protected service drop-in could not be read or rehashed through the available
non-root account; earlier verified snapshots remain dated evidence.

The owner confirmed the vehicle was parked, the radio was powered on, FT8
signals were audible, and GPS was working. The vehicle was subsequently
returned to the garage and the radio is now off. This is owner-reported
receive-audio and GPS-function evidence;
no timestamps, freshness details, or private measurements were supplied. It
does not establish application FT8 decoding, two consecutive decode periods,
physical receive/PTT indication, or exact installed source identity. The exact
installed source identity gate and remaining receive-only checks therefore
remain incomplete.

## Source and offline test evidence

- `src/rolling_thunder/ft8/audio.py` constructs a receive-only `arecord`
  capture command (mono, 12 kHz, signed 16-bit little-endian PCM). Starting
  audio capture does not itself start an FT8 QSO or transmit.
- `ApplicationRuntime.start` starts FT8 receive and then GPS polling. GPS
  acquisition still depends on configured serial-device identity and a live
  valid receiver fix.
- `ApplicationRuntime.stop` releases radio-owned FT8 services before unrelated
  workers, stops GPS polling, and skips GPS disconnect if polling did not
  quiesce. This is a software lifecycle guarantee only.
- Existing hardware-free regression coverage includes
  `tests/test_gps_polling.py`, `tests/test_serial_gps.py`,
  `tests/test_serial_gps_buffer_freshness.py`, `tests/test_ft8_audio.py`,
  `tests/test_ft8_receive.py`, `tests/test_ft8_ptt_alarm.py`,
  `tests/test_stab02_shutdown_failure_modes.py`, and
  `tests/test_stab04_shutdown_deadline_contract.py`.
- These tests use fakes. They do not verify physical USB identity, antenna/GPS
  reception, audio wiring, decoded RF, or physical PTT state.

## Required parked acceptance sequence

The owner confirmed on 2026-11-17 that the vehicle was parked, the radio was
powered on for receive, FT8 signals were audible, and GPS was working. The
vehicle is now back in the garage and the radio is off. The parked precondition
was met during the observation. The report does not establish FT8 software
decode periods, physical radio receive/PTT indication, or installed code
identity. Separately authorize any deployment or restart needed to test the
selected exact SHA. This procedure does not authorize a transmit test.

1. Record the exact target `main` SHA, exact installed source/runtime identity,
   and successful exact-head CI. Stop if the installed process cannot be tied
   to the reviewed candidate or if a deployment transaction is unresolved.
2. Verify the effective system unit, service owner, launcher, protected
   drop-ins, and device configuration through authorized read-only paths. Use
   unique stable device identity for radio CAT, physical controls, GPS, and
   audio. Record the mapping in the private acceptance record; do not publish
   serial numbers, addresses, private paths, or hashes.
3. Confirm there is exactly one managed dashboard. Verify GPS reports a
   currently valid fix with a fresh timestamp and plausible position, and that
   loss/degraded status is visible. A tty link or connected state alone is not
   a GPS pass.
4. With the radio manually placed in a known receive configuration, observe
   receive audio and at least two consecutive FT8 decode periods. Do not use
   QSO start, retry, power adjustment, tuning automation, PTT, or any control
   that can initiate a transmit workflow. Record audio health, decode times,
   and the UI response interval. Do not record callsigns or contact payloads
   in the public evidence packet.
5. Verify the physical radio indicator remains in receive throughout the
   observation, and confirm the operator can immediately use physical radio
   power/PTT controls. Software flags, CAT readbacks, an issued `TX0;`, a
   successful service state, or an FT8 decode are not proof of physical PTT
   release.
6. Observe orderly UI shutdown only if a separately approved parked
   maintenance window includes stopping the service. Confirm the bounded
   shutdown result and that GPS disconnect does not overlap an active read.
   Do not unplug/replug devices or induce USB faults during this acceptance.
7. Record pass/no-go per item, exact timestamps and private evidence locations.
   Preserve the current operator recovery contract: the operator can clear an
   application lockout and a system restart restores operator control. Neither
   action proves physical PTT release. If any state is uncertain, stop and use
   the owner's physical recovery procedure; do not auto-retry or transmit.

## Acceptance record

| Check | Result | Evidence required |
| --- | --- | --- |
| Parked observation, radio powered on for receive, MeshCore removed | Owner reported; partial pass | 2026-11-17 owner statement; vehicle subsequently returned to garage; radio now off |
| Exact installed source/runtime identity | Not established | Process-bound release identity and readiness evidence |
| One system-managed dashboard and effective protected configuration | Partial | Current read-only service state seen; installed identity/configuration reconciliation remains required |
| Unique radio/controller/GPS/audio mapping | Partial | Interfaces enumerate; physical function-to-device mapping not confirmed |
| GPS function | Owner reported working; partial | Fresh fix timestamp/validity and visible loss/recovery behavior not recorded |
| FT8 receive audio | Owner reported audible; partial | Application audio health and two consecutive decode periods not recorded |
| Physical radio remains in receive | Not recorded | Operator observation of receive indicator and physical controls; software is insufficient |
| Bounded orderly stop and rollback | Not tested | Separately approved maintenance-window result; preserve data |
| Overall decision | **NO GO** | All required items must pass; missing evidence is not a pass |

## Recovery and release boundary

The operator retains final authority. A software lockout is not permanent: the
operator may clear it through the existing on-screen recovery gesture, and a
system restart resets the in-memory lockout. Neither is proof that the radio is
physically de-keyed. Do not add transmit authority or expand FT8 automation as
part of acceptance. Any transmit/RF test remains a distinct owner-approved
activity with its own safety plan.

On 2026-11-17, the separately authorized MeshCore service cutover was completed
as recorded in `meshcore-installed-service-cutover-plan.md`. No Rolling Thunder
deployment or restart, source database mutation, physical USB operation,
CAT/PTT activity, or RF transmission was performed by this review. The owner
reports that the parked radio was powered on for receive, FT8 signals were
audible, and GPS was working. The vehicle is now back in the garage and the
radio is off. These observations do not complete application decode, physical
receive/PTT, runtime identity, or overall receive-only acceptance.
