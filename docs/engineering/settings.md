# Settings

Settings owns clamped selection, all-visible-control presentation,
explicit routing, and
two-step power-confirmation lifecycle. Feature meaning remains with the map,
radar, callsign-info, persistence, radio/FT8, contact, DMR, physical-control, and
application-lifecycle owners.

The fixed clamped order is MAP ZOOM, RADAR, CALLSIGN INFO, MAP STYLE, REBOOT,
SHUTDOWN, followed by Construction Zones, Dangerous Slowdowns, Incidents,
and Travel Delays as full-width OHGO rows with the standard Settings typography.
On shorter screens the rows page with the encoder selection. The selected
control's button instruction stays in a fixed footer. Encoder
rotation changes only the highlighted row. B1 and encoder press are inert. B2
requests OUT/OFF/NIGHT or CANCEL; B3 requests IN/ON/DAY or advances power from
SELECT to CONFIRM. Requests are explicit and idempotent. Text exposes actual zoom,
style, ON/OFF/UNAVAILABLE state, power availability, action, and bounded failure
reason; color and switch position are supplementary. Zoom preserves map bounds.
Manual style uses the shared fan-out and solar manual override. For each OHGO
choice B2 means OFF and B3 means ON. Choices default to OFF and use the
existing asynchronous preference writer. Visibility is gated by GPS and feed
freshness independently of the saved switch position. See [OHGO](ohgo-incidents.md).

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

The Linux adapter invokes `sudo -n` with exactly one of the allowlisted commands
`/usr/bin/systemctl --no-ask-password reboot` or
`/usr/bin/systemctl --no-ask-password poweroff`, with `shell=False`, captured
output, and a five-second timeout on a bounded worker. The host sudoers entry is
`/etc/sudoers.d/rolling-thunder-settings-power`; it grants only those two exact
argument vectors to the `geoff` account. It does not permit a shell or arbitrary
systemctl arguments. The in-app serial-v2 confirmation and radio/commit guards
remain required. Failure or timeout leaves the dashboard running and preference
service open, with the bounded reason visible. Success remains pending and does
not call Tk or start cleanup; the service manager's actual SIGTERM sets a
thread-safe flag, and the UI refresh starts existing off-Tk cleanup on the main
thread. Cleanup attempts every registered step, including preference drain and
runtime stop, even after an earlier failure. The installed systemd stop limit is
20 seconds; that is a service limit, not a claim about physical shutdown timing.

Linux shutdown does not physically disconnect battery, fan, hub, or radio power;
a blank display is not proof that equipment is safe to unplug.
