# REL-01 — parked production acceptance packet (prepared; NO GO)

**Current source baseline:** merged `main` at `3328c27d5eb41e4417fe6305d1942002a3488106` (2026-11-17).
**Disposition:** **NO GO for a full AnvilMobile release.** This packet records
acceptance requirements and source-level conclusions. It intentionally omits
hostnames, process identifiers, internal network addresses, hardware serials,
private filesystem paths, database contents, and production binary digests.
Those details are not needed to establish the gates below and must not be
copied into this public repository.

## Authority and release decision

This review authorizes source inspection, offline validation, and documentation
updates only. A merge, privileged helper installation, AnvilMobile deployment
or restart, service cutover, database mutation, physical USB work, or radio
operation requires its own explicit owner authorization. This packet grants no
such approval. No unattended transmit authority is added.

Green offline CI does not establish installed-image provenance, application
readiness, independent physical receive/de-key state, or a tested production
rollback. Do not schedule or promote a release automatically.

## Publicly supportable installed-state conclusions

The latest read-only host observation recorded an active system service using
system Python from a clean but mutable application checkout. Systemd's active
state established process existence only; independent UI/application readiness
was not observed. The installed checkout was behind current source. Exact
host/process and executable/native-file identifiers are omitted from this
public record. Current process/path observations and on-disk digests do not
prove which Python module bytes were already loaded into memory.

The installed deployment wrapper observed during the earlier inspection did
not provide invocation serialization, a recoverable transaction journal, or
an independent application-readiness check. PR #484's reviewed source adds
serialized, journaled deployment and rollback checks, but that candidate is
not installed or accepted in production. No wrapper, unit, drop-in, or sudo
configuration change is authorized by this packet.

An owner-authorized SQLite online backup of the primary QSO database was
created and verified while WAL mode was active. It is a consistent point-in-
time copy, not a restore over the live database. It covers only the primary
QSO database; separate MeshCore and optional outbox stores are outside its
scope. Artifact paths, hashes, row counts, and private manifests are withheld
from this public record. Do not restore an older snapshot over newer live
data.

The owner reported that the field test after the Forge contact-sync change
succeeded and contacts synchronized. Exact test identifiers and independent
post-test database evidence were not supplied, so this remains an owner report,
not a complete production acceptance record. The Forge endpoint was not
revalidated during this review.

The last historical read-only service inspection found MeshCore application
service state still present after PR #479 removed the application source. The
source merge does not stop, disable, or uninstall a host service and does not
remove its data. No current cutover state is asserted here; service ownership
and any cutover require a separately approved plan.

## 2026-11-17 receive-only and MeshCore read-only refresh

An authorized read-only check through the account owning the user systemd
manager found the Rolling Thunder system unit active. The expected MeshCore
receiver USB identity was absent from enumeration; the GPS serial endpoint and
USB audio capture interface were enumerated. These are device-presence checks
only: no live GPS fix, FT8 decode, or receiver-function test was observed. A
second remote-tool context ran under a different Unix account and therefore
reported a different user systemd view; user services must be checked through
their owning account's manager.

That owner-level manager reported `meshcore-collector.service` enabled and
active, and `meshcore-traffic-worker.service` enabled but inactive. This
confirms the historical source-removal warning remains operationally relevant;
it does not authorize stopping or disabling either service. No database or
queue was read or changed during this refresh. See
[`parked-receive-only-acceptance.md`](parked-receive-only-acceptance.md) for
the incomplete hardware acceptance record and
[`meshcore-installed-service-cutover-plan.md`](meshcore-installed-service-cutover-plan.md)
for the separately gated plan.

## Immutable acceptance gates

| Gate | Required evidence | Current disposition |
| --- | --- | --- |
| Exact release candidate | Reviewed merged SHA, exact-head CI, source/wheel/native manifest and signature | Not selected for AnvilMobile; NO GO |
| Native package provenance | Authenticated package metadata for every required installed package, or independently authenticated publisher-signed equivalent | 14 of 16 sampled package revisions have authenticated archive provenance. Two Raspberry Pi-patched revisions remain quarantined pending trust in the build-record signing key or recovery of their signed historical package index; see [STAB-07L](stab07l-rpi-historical-package-quarantine.md). |
| Running-code identity | Protected immutable release, exact constrained launch path, trusted process-instance observer, and readiness bound to that process | Not established. Existing checks correctly refuse to equate process path, source checkout, hashes, systemd active state, or signed observation with Python bytes in memory. |
| Deployment wrapper | Serialized invocations, durable transaction journal, protected verified backup, truthful readiness check, bounded rollback | Source candidate is merged; installed wrapper is not confirmed to match it and production acceptance is incomplete. |
| Durable data and rollback | Consistent verified backup of all required stores; compatible code/schema rollback; operator-owned recovery | Primary QSO online backup was verified. Other stores and production rollback remain unaccepted; no restore was performed. |
| USB/GPS/FT8 receive | Parked independent device mapping, fresh GPS, audio capture, receive-only decoding, and UI responsiveness | Not field-accepted by this packet. Enumeration and process state are not functional hardware proof. |
| Physical safety | Operator-confirmed receive/de-key and safe recovery plan | Not field-accepted. Software status and a successful `TX0;` command do not prove physical PTT release. |
| Owner approval | Parked vehicle, operator readiness, exact target SHA, stop/rollback owner, approved hardware plan | Not obtained for a full release. |

The operator must retain the ability to clear an application lockout; a system
restart restores operator control. Neither action proves physical PTT release.

## Parked preflight — no mutation until separately authorized

1. Confirm the vehicle is parked, no QSO or FT8 activity is in progress, power
   is stable, a console is reachable, and the operator can safely power down
   the radio. Assign stop and rollback decisions.
2. Revalidate exact target SHA and exact-head CI. Run repository quality gates
   and document any failed or skipped checks; a historical lint exception is
   not an automatic waiver.
3. Review the effective service, wrapper, drop-ins, identity, and deployment
   lock through an authorized path. `Type=simple` and `active` are not
   application readiness.
4. Before deployment, verify a fresh consistent backup of every required data
   store and its rollback compatibility. Preserve WAL, contacts, retry state,
   and outbox records; do not replace live data from Git or an older snapshot.
5. Verify native provenance and a protected immutable release. Stop if any
   required native input or the constrained launch identity is unverified.
6. Verify local logging, Forge reachability, and required data reconciliation
   without replaying or editing records manually.
7. Record a pass/no-go result for each gate. Missing evidence means NO GO.

## Approved deployment sequence (future only)

After new owner approval for a specific parked SHA:

1. Freeze the target and record the previous release and verified evidence
   manifest.
2. Invoke only a reviewed exact-SHA path that serializes deployments, journals
   recoverable transaction state, verifies the protected backup, and checks
   independent application readiness. Refuse concurrent or uncertain runs.
3. Verify transaction outcome, installed release identity, process-instance
   binding, and readiness. A shell exit, checkout SHA, or systemd active state
   is not healthy UI evidence.
4. Verify one managed UI process, a fresh UI heartbeat, status, and controlled
   navigation. Then test GPS/controller behavior and FT8 **receive only**.
5. Reconcile required local and remote data stores without losing records
   created during the release.
6. Observe bounded orderly stop/start behavior. Distinguish a CAT release
   command log from physical de-key observation.
7. Record each gate's evidence and result. Do not auto-promote on a partial
   pass.

## Physical FT8 gate: separate authorization only

FT8 recovery controls are operator-controlled recovery actions, not independent
physical RX proof. They do not add general PTT authority or expand FT8
automation. On a red TX indicator, unclear radio power, stuck CAT, unexpected
FT8 audio, or uncertain release: stop automation, use the owner's physical
safe procedure, preserve logs, and stop the release. Software `TX0;` success or
`transmitting=False` never substitutes for observation. Any deliberate
transmit/RF test requires its own parked approval, suitable antenna or dummy
load, safety observer, and hard abort.

## Failure and rollback

- If install state is indeterminate, the journal is missing or invalid, two
  dashboards exist, launch evidence is stale, readiness is absent, or PTT is
  uncertain: stop; do not enter a retry loop or force-kill as a substitute for
  physical de-key.
- Assess schema compatibility before application rollback. Never restore an
  older SQLite snapshot over new QSOs, lose WAL frames, truncate retry metadata,
  or delete transaction receipts to unblock a run.
- Roll back application code only through a verified serialized wrapper.
  Restore privileged helper code only under its separate grant. Refuse rollback
  if it risks data loss.
- Preserve audit receipts and the private preflight/rollback evidence. If a
  safe revert cannot be established before deployment, the result is NO GO.

## Source and status history

- PR #479 removed MeshCore application source while retaining Forge-backed
  OHGO. It did not perform a service cutover or delete installed data.
- PR #481 merged the GPS poll/shutdown quiescence fix. It has not been
  production-accepted by this packet.
- PR #484 merged a serialized deployment and rollback candidate. It is not
  confirmed installed or production-accepted.
- PR #485 recorded the verified primary-QSO online backup. The public record
  intentionally omits its private artifact metadata.
- PR #486 redacted private production identifiers and documented the remaining
  native-package signer-trust and running-code identity limits. It did not
  change runtime behavior or resolve those release gates.
- PR #480's Forge contact-sync component deployment and the owner's field-test
  report are separate from full Pi acceptance.

Current full AnvilMobile disposition remains **NO GO**. No AnvilMobile
deployment, restart, service cutover, database restore/mutation, USB
manipulation, CAT/PTT activity, or RF transmission was authorized or performed
by this documentation update.
