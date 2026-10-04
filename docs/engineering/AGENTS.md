# Engineering Documentation Agent Rules

This directory describes current implemented ownership and dependencies.

When code changes:

1. update the applicable feature/subsystem section;
2. update `shared-component-consumers.md` when consumers change;
3. update `forge-services.md` for Forge process/API/lifecycle changes;
4. update `source-file-index.md` when modules are added, removed, renamed, or materially repurposed;
5. update `../ROLLING_THUNDER_OPERATORS_GUIDE.md` when operator-visible behavior changes.

Do not copy historical checkpoint language into current-state guides unless it remains relevant to the current contract.

Prefer links to authoritative subsystem documents for protocol-level detail, but keep ownership, dependencies, and change impact explicit here.

A feature guide must identify shared dependencies. Never describe a shared module as feature-owned merely because it is visually reached from that feature.
