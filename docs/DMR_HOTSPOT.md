# DMR Hotspot Monitoring and Logging

## Purpose

The DMR panel monitors the configured local WPSD/MMDVM hotspot without giving
Rolling Thunder any transmit authority. SSH live activity and WPSD HTTP history
remain background-owned; Tkinter consumes immutable snapshots only.

## Monitored talkgroup state

Rolling Thunder does not assume TG3100.

The authoritative local monitored-talkgroup state is learned from RF activity by
the configured Rolling Thunder operator callsign. When that callsign transmits
or kerchunks a group call such as `TG 91` through the hotspot, the live MMDVM
feed updates `monitored_talkgroup` to 91.

After application restart, if no live operator RF event has been seen yet,
Rolling Thunder may recover the state from the newest WPSD history row whose:

- source is RF;
- callsign matches the configured operator callsign; and
- target contains a numeric DMR talkgroup.

Network-originated callers and RF activity from another callsign cannot change
the monitored talkgroup.

Until a monitored talkgroup is known, DMR history/current-audio logging
selection is disabled and the panel explicitly shows `TG ?`.

## Filtering and logging

The monitor retains the raw bounded WPSD history snapshot for diagnostics. The
operator-facing selection path derives a separate filtered view containing only
the current monitored talkgroup.

This means:

- unrelated busy talkgroups do not enter encoder history selection;
- Context Button #1 stages current audio only when it belongs to the monitored
  talkgroup;
- encoder staging can only select history rows from the monitored talkgroup;
- the immutable staged QSO freezes the actual talkgroup number;
- Context Button #2 persists that exact staged talkgroup in the contact notes;
- changing the monitored talkgroup changes future eligibility rather than
  rewriting an already-staged QSO.

The DMR parser itself remains talkgroup-neutral. TG3100, TG91, TG9, and other
numeric group-call targets use the same typed parsing path.

## Failure behavior

WPSD history or radio-info failure retains last-known usable data while marking
the relevant source degraded. Live-feed loss clears current audio but does not
invent a replacement monitored talkgroup.

DMR failure does not block ordinary local logging, GPS, mapping, repeaters,
POTA/DX, physical controls, or radio polling.
