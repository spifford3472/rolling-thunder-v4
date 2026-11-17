# REL-01 installed-state snapshot — public redacted summary

**Result:** full production readiness remains **NO GO**.

This public summary records conclusions from read-only installed-state checks
without publishing hostnames, process identifiers, internal addresses, hardware
serials, private filesystem/database paths, database contents, or production
binary digests. The underlying exact operational identifiers are intentionally
not included in this repository. The observations are historical snapshots,
not continuous health monitoring or approval to change the system.

## Findings

| Area | Read-only conclusion | Limit / disposition |
| --- | --- | --- |
| Service lifecycle | The dashboard system service was active, with a separate launcher guard. | Systemd active state and a process lock do not establish Tk/application readiness or radio health. |
| Running-code identity | The service ran from a clean but mutable installed checkout using the system Python runtime. The checkout was behind current source. | Process path and present on-disk state do not prove which Python modules were loaded at process start. An immutable release and trusted process-instance observation remain required. |
| Installed wrapper | The inspected legacy wrapper stopped the service, backed up the primary QSO DB, installed an exact SHA, then checked systemd active state and checkout SHA. | No invocation mutex, transaction journal, or independent UI readiness check was found in that wrapper. PR #484's candidate is merged in source but is not confirmed installed or production-accepted. |
| Database preservation | An owner-authorized SQLite online backup of the primary QSO database was subsequently created and verified while WAL mode was active. | The backup is a consistent point-in-time copy, not a restore. It does not include separate MeshCore or optional outbox databases. Private artifact metadata and contents are withheld. |
| Contact sync | The owner reported a successful field test after the Forge contact-sync change. | Exact test identifiers and independent post-test database evidence were not supplied. The report is not full release acceptance. |
| USB/GPS/audio | Read-only enumeration and configured process mappings were inspected. | Enumeration and open descriptors do not prove fresh GPS, functional audio, successful FT8 decode, or stable physical USB operation. Hardware acceptance remains outstanding. |
| MeshCore | A historical inspection found an installed MeshCore user service after PR #479 removed the application source. | Source removal does not stop services or delete data. Current service state and any cutover require separately approved verification. |
| Forge continuity | A historical Forge health check succeeded after the contact-sync change. | No fresh endpoint verification is represented here. A health endpoint alone does not prove end-to-end contact delivery. |
| Physical safety | Source changes preserve operator-controlled lockout recovery and bounded FT8 behavior. | Software status, CAT release commands, and restart are not proof of physical PTT release. |

## Release decision

Full AnvilMobile release remains **NO GO** pending all of the following:

- authenticated provenance for all required native packages and a complete
  ARM64 runtime closure;
- protected immutable release identity, constrained launch path, independent
  process-instance observation, and application readiness;
- separately authorized installation and parked acceptance of the reviewed
  deployment wrapper, including serialization, journaling, backup, and
  data-preserving rollback;
- reconciliation of all required durable stores;
- parked USB, GPS, audio, FT8 receive-only, and operator safety acceptance;
- explicit owner approval for the exact release and each separately gated
  production or radio operation.

No deployment, restart, service cutover, database restore/mutation, hardware
operation, CAT/PTT activity, or RF transmission is authorized by this snapshot.
The operator must retain the ability to clear an application lockout, and a
system restart restores operator control. Neither establishes physical PTT
release.
