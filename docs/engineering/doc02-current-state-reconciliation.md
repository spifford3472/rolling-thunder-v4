# DOC-02 — current-state documentation corrections

Date: 2026-11-14. Scope: repository documentation only. This document
records correction provenance and remaining gaps; it is **not** an operational
release certificate.

## Corrected source-grounded drift

| DOC-01 ID | Correction | Evidence limit |
| --- | --- | --- |
| A | Dated issue #410 supervision report now has a current-source supersession pointer: inherited `flock` plus secondary `pgrep` | Installed launcher remains a separate exact-SHA verification |
| B | Current system architecture links the later parked stop and wrapper observations | Original time-bound inventory remains unchanged |
| C | Literal `\\n\\n` in the current launcher paragraph converted to real paragraph breaks | Pure editorial correction |
| D | Duplicated propagation inbox sentence consolidated into disabled-by-default wording | No provider activation or deployment is implied |
| E | FT8 engineering guide's CP9.1 status explicitly described as historical; guide is living reference | Production FT8 and printable release acceptance remain open |
| F | Forge PSK autoqueue oneshot failure is an operational incident, **not** a documentation-only fix | Read-only incident investigation still required |

Historical observations are retained rather than silently overwritten.

## DOC-03 and PR #414

Draft PR #414 spans `.github/workflows/ci.yml` (new report-only
documentation inventory audit), operator FT8 safety guidance, MeshCore/OHGO
ownership, source/test indexes, and broader architecture reconciliation.
It is **not** entirely superseded by DOC-02. Its evidence ledger includes
unverified production claims and scope beyond a narrow formatting correction.

Recommended next review gates:
1. Compare #414's source/test index counts against exact current GitHub main
   using a bidirectional inventory, then review report-only CI integration.
2. Review operator safety claims for accuracy, especially constant
   `radio_confirmed_receive=True` in the FT8 unlock path. Do not present
   operator gesture as physical RX verification.
3. Verify MeshCore/OHGO boundaries against current code and installed
   composition. No removal or network/service changes are approved.
4. Land verified documentation-only slices separately where possible.
   Keep #414 draft until its own regression and CI-documentation gates pass.
5. Align STAB-04/05/06 evidence and real system readiness after those
   branches are reviewed and merged with explicit owner approval.

## Rollback and change history

2026-11-14: Corrected four source-known editorial/status discrepancies and
cross-linked dated shutdown observations; no production or host changes.
Revert this documentation PR to roll back.
