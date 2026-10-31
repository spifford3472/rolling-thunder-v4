# Settings

Settings owns the frozen six-row selection, all-visible-row presentation,
explicit routing, and
two-step power-confirmation lifecycle. Feature meaning remains with the map,
radar, callsign-info, persistence, radio/FT8, contact, DMR, physical-control, and
application-lifecycle owners.

The fixed clamped order is MAP ZOOM, RADAR, CALLSIGN INFO, MAP STYLE, REBOOT,
SHUTDOWN. All six compact rows remain visible at the supported 1280x720 display
size, with the selected row's button instruction in a fixed footer. Encoder
rotation changes only the highlighted row. B1 and encoder press are inert. B2
requests OUT/OFF/NIGHT or CANCEL; B3 requests IN/ON/DAY or advances power from
SELECT to CONFIRM. Requests are explicit and idempotent. Text exposes actual zoom,
style, ON/OFF/UNAVAILABLE state, power availability, action, and bounded failure
reason; color and switch position are supplementary. Zoom preserves map bounds.
Manual style uses the shared fan-out and solar manual override.

## Power contract

Browsing never requests an OS transition. REBOOT and SHUTDOWN require two
distinct, increasing, fresh serial-v2 RELEASE events in the same healthy nonce
and generation, separated by the deliberate-input interval. Confirmation expires
after ten seconds and is canceled by B2, row/context change, controller loss,
session replacement, unhealthy transport, replay, stale/future/nonfinite/held
input, or guard failure. Power shows UNAVAILABLE without a current healthy,
trusted serial-v2 session. Legacy serial, keyboard repeats, and input without
host expiry proof fail closed.

The guard consumes published state only. It refuses while an FT8 QSO context is
attached (including terminal), FT8 preparation/restore or hardware execution is
busy/transmitting, the PTT alarm is active/inhibited, radio receive state is
unknown, or ordinary/DMR durable commit is active. It is rechecked before the OS
adapter. A bounded three-second preference barrier drains earlier queued writes
without stopping the runtime; Forge, Wavelog, internet, and outbox delivery are
not prerequisites.

Once the OS request is pending, every new operator command is rejected: this
includes context changes, tuning/selection movement, capture, QSO actions and
commits. Ordinary navigation remains available during the first SELECT/CONFIRM
stage. Cleanup-started state has the same all-command guard.

The Linux adapter permits only `/usr/bin/systemctl --no-ask-password reboot` or
`poweroff`, with `shell=False`, captured output, and a five-second timeout on a
bounded worker. Failure or timeout leaves the dashboard running and preference
service open, with the bounded reason visible. Success remains pending and does
not call Tk or start cleanup; the service manager's actual SIGTERM sets a
thread-safe flag, and the UI refresh starts existing off-Tk cleanup on the main
thread. Cleanup attempts every registered step, including preference drain and
runtime stop, even after an earlier failure. The installed systemd stop limit is
20 seconds; that is a service limit, not a claim about physical shutdown timing.

Linux shutdown does not physically disconnect battery, fan, hub, or radio power;
a blank display is not proof that equipment is safe to unplug.
