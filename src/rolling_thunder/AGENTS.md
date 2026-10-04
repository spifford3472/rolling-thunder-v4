# Rolling Thunder Source Agent Instructions

These instructions apply to code under `src/rolling_thunder/` in addition to
the repository-root `AGENTS.md`.

Before editing a module, locate it in
`docs/engineering/source-file-index.md` and identify its owner/consumers in
`docs/engineering/ownership-and-dependencies.md` and
`docs/engineering/shared-component-consumers.md`.

## Shared-code rule

A request mentioning one screen does not grant permission to redefine shared
GPS, logging, radio, callsign-info, map, status, control, persistence, or Forge
contracts.

Inspect affected consumer tests before changing a shared interface or lifecycle.

## UI rule

Tkinter code renders immutable state and invokes application/controller
boundaries. Do not add blocking provider, network, SQLite, filesystem, serial,
CAT, or audio work to the UI thread.

## Hardware/radio rule

Use the typed radio, CAT, GPS, audio, and control boundaries. Do not open device
paths from application/UI code and do not introduce feature-specific raw-CAT
shortcuts when a shared typed service owns the operation.

Do not broaden transmit authority as a side effect of unrelated work.

## Forge modules

Files beginning with `forge_` implement backend/provider/service behavior.

**Forge services must be designed as reusable programmatic services that can be
called by other authorized applications, not only Rolling Thunder.**

For Forge changes:
- read `docs/engineering/forge-services.md`;
- keep API models presentation-neutral;
- do not expose Tkinter/screen/widget concepts;
- do not make provider lifecycles depend on Pi refresh timing;
- preserve independent health, persistence, backoff/rate-limit/provider-etiquette
  behavior;
- consider backward compatibility for current and future non-Rolling-Thunder
  consumers.

## Documentation rule

Update the engineering documentation in the same branch whenever source
responsibility, contracts, consumers, lifecycle, or public behavior changes.
Update the Operator's Guide when behavior is visible to the operator.
