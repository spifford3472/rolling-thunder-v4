# Engineering Documentation Agent Rules

This directory is the maintained current-state engineering knowledge base.

Documentation maintenance is part of implementation, not optional cleanup.

When code changes:

1. update the applicable feature/subsystem section;
2. update `ownership-and-dependencies.md` when ownership or dependency flow changes;
3. update `shared-component-contracts.md` when a shared invariant changes;
4. update `shared-component-consumers.md` when consumers change;
5. update `forge-services.md` for Forge process/API/lifecycle changes;
6. update `source-file-index.md` when modules are added, removed, renamed, or materially repurposed;
7. update `test-index.md` when validation ownership or test organization changes;
8. update `system-architecture.md` when deployed topology/process boundaries change;
9. update `../ROLLING_THUNDER_OPERATORS_GUIDE.md` when operator-visible behavior changes.

Do not copy historical checkpoint language into current-state guides unless it
remains relevant to the current contract.

Prefer links to authoritative subsystem documents for protocol-level detail, but
keep ownership, dependencies, change impact, and cross-feature risk explicit
here.

A feature guide must identify shared dependencies. Never describe a shared
module as feature-owned merely because it is visually reached from that feature.

If current code intentionally supersedes an older document, either update the
older document or clearly mark it historical/current-state-inexact so future
agents are not given contradictory instructions.
