# Parked USB/GPS/FT8 receive-only acceptance

**Status: NOT ACCEPTED — parked precondition met; receive-only evidence still outstanding.** This procedure records
what must be demonstrated on the installed AnvilMobile system before USB,
GPS, controller, or FT8 receive operation can be accepted. It grants no
deployment, service restart, database, USB manipulation, CAT/PTT, or RF
authority. A receive-only test must never start an FT8 QSO or key the radio.

## Current source and evidence boundary

The source baseline is merged `main` at
`3328c27d5eb41e4417fe6305d1942002a3488106`. PR #481 makes GPS polling stop
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
process currently launches from a mutable checkout, and #486 only redacted
evidence and documented identity limits. Therefore this observation cannot be
accepted as evidence for the current source release.

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

The owner confirmed on 2026-11-17 that the vehicle is parked, the radio is
powered off, and the MeshCore receiver is physically removed. This satisfies
the parked precondition and confirms no active radio operation at that point;
it does not establish live GPS, receive audio, FT8 decodes, or installed code
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
| Parked state, radio powered off, MeshCore removed | Owner confirmed | 2026-11-17 owner statement; no receive acceptance implied |
| Exact installed source/runtime identity | Not established | Current Pi uses a mutable checkout; the new protected-release/process verifier is source-only and requires a root-owned exact-SHA release plus a matching PID/boot/start-tick Tk heartbeat |
| One system-managed dashboard and effective protected configuration | Partial | Current read-only service state seen; installed identity/configuration reconciliation remains required |
| Unique radio/controller/GPS/audio mapping | Partial | Interfaces enumerate; physical function-to-device mapping not confirmed |
| Fresh GPS fix and visible loss/recovery behavior | Not tested | Live timestamped fix and safe observed recovery |
| Receive audio and two consecutive FT8 decode periods | Not tested | Timestamped receive-only observation with no QSO start |
| Physical radio remains in receive | Not tested | Operator observation; no software-only substitution |
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
CAT/PTT activity, or RF transmission occurred. Receive-only acceptance remains
incomplete.
