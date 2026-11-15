# Historical draft PR reconciliation — 2026-11-15

**Scope:** read-only GitHub/Forge branch review against `main`
`96b0aa0838eaf2f2c78cec4e9c3355e57b97c9d1`, incorporating merged
STAB-07 (#472), DOC-X (#473), and FT8 receive-lockout correction (#474).
This report is a recommendation for historical PR housekeeping **not an
instruction to merge/rebase old branches or to close PRs without owner review**.

## Method and provenance

The GitHub API reported the open draft list and original changed-file inventories.
The isolated Forge repository fetched the draft head refs, enumerated each branch
file tree, and checked path presence against exact current `main`. **Every
source/test/deployment/document path in the remaining draft branch snapshots
exists on current `main`, except `docs/engineering/reconciliation-2026-11-13.md`
from draft #414.** This proves pathname coverage only, not byte-for-byte
functional equivalence or production installation. Earlier source revisions
can differ from newer integrated fixes; do not mass merge or restore their
old files. Original PR discussions and commits remain part of GitHub history.

## Disposition matrix

| PR | Original work | Current recommendation | Reason / preserve |
| --- | --- | --- | --- |
| #414 | DOC-03 architecture ledger, report-only CI inventory, FT8 and MeshCore observations | **Hold for historical owner review; do not merge** | DOC-X #473 supplies current ledger and blocking inventory CI; FT8 incorrect constant recovered in #474. Its dated reconciliation ledger alone is absent from current main; preserve via PR history, not by treating source-old assertions as current |
| #438 | STAB-06 launcher flock regression | **Superseded candidate for closure** | `tests/test_autostart_launcher.py` present and byte-identical on current main; newer test-index and supervisor documentation supersede original draft prose |
| #439 | DOC-02 current-state fixes | **Superseded candidate for closure** | Main incorporates its FT8 engineering and issue #410 correction files, with later DOC-X supersession/history and corrected shutdown documentation |
| #440 | REL-01 nonexecuted runbook | **Superseded candidate for closure after this REL-01 packet review** | Maintained runbook exists in main; this document provides current gate/rollback requirements rather than old candidate status |
| #442 | STAB-06C transaction lock | **Superseded candidate for closure** | `deploy/rolling-thunder-deploy-lock` and `tests/test_deployment_transaction_lock.py` present and byte-identical on main; corresponding current guide remains; source-only and not proof installed helper |
| #444, #445 | STAB-06E/F journal and recovery inspection | **Consolidated by #472; closure candidates** | Candidate code and associated tests included in merged integration; no privileged installation inferred |
| #447, #449, #451, #453 | STAB-07 integration, security, running identity, release/witness | **Consolidated by #472; closure candidates** | Keep original review provenance; do not reapply old release claims or approve privileged execution |
| #455, #457, #459, #461 | ARM64 dependency, staging, emulation, Tk lifecycle | **Consolidated by #472; closure candidates** | All historical lockfile/tool/test paths present in main, but remain hardware-disabled evidence only |
| #463, #465, #467, #469, #471 | Full mock dashboard, native comparison, signed package evidence, quarantine and Track A | **Consolidated by #472; closure candidates** | Functional fixes and tests integrated; Pi native archive provenance 14/16 signed, two quarantined; no exact installed identity or RF proof |

**Do not close #414 automatically:** it was explicitly retained as a separate
architecture-audit draft; its reviewable historical findings and unmerged ledger
are not interchangeable with the merged DOC-X records. No original PR is a
valid current release branch: retargeting onto `main` would resurrect older
documentation and may reverse safety corrections.

## Acceptance evidence retained

- STAB-07 merged PR #472, commit `b792151313e60596e6ff3ad51f6ed4e260078718`:
  offline ARM64 mock lifecycle, partial-start rollback, blocked cleanup,
  no-RF simulation and protected native/provenance constraints.
- DOC-X merged PR #473, commit `d3ac78f771ebaf7241ad884679489a837659d382`:
  401 source/index paths, source/document reconciliation and blocking CI drift.
- FT8 safety merged PR #474, commit `96b0aa0838eaf2f2c78cec4e9c3355e57b97c9d1`:
  real PTT alarm unlock **fail-closed** because physical RX is unverified;
  isolated visual-test alarm retains no transmitter authority.
- Older source/Pi observations are **dated**; the installed protected wrapper,
  systemd drop-ins, live release SHA, QSO database/WAL and real RF must be
  independently re-attested before any release.

## Recommended PR housekeeping sequence (review-only)

1. Preserve all references and the merged-source acceptance packet; verify
   branch-file coverage at the current main SHA once more if main moves.
2. With owner authorization, close the **15 stacked** #444–#471 historical
   drafts as superseded by #472, linking the consolidated merge and noting
   no production deployment. No merge or branch deletion is needed.
3. With owner authorization, close #438 and #442 as integrated source/test
   supersessions, and #439/#440 as updated documentation/runbook supersessions.
4. Keep #414 draft pending explicit decision whether its original historical
   ledger should be archived elsewhere or closed as superseded by DOC-X.
5. Never close a PR merely because its source file path exists: confirm its
   relevant tests and current behavior before changing its status.

**No PRs were closed or merged by this documentation task.** Rollback for
this report is reverting the documentation commit; GitHub draft status and
production state remain unchanged.

## Change history

- 2026-11-15: Audited 20 open draft PRs and source-path coverage against
  exact merged main; documented proposed supersessions and protected #414
  history without modifying any PR state, service, firewall or radio.
