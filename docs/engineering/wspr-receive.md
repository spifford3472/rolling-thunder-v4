# Parked receive-only WSPR

The persistent dashboard provides WSPR on its normal context cycle after FT8.
Validated physical Command Button 3 on a rendered WSPR screen requests one
session. Button 2, any context exit, dashboard shutdown, confirmed motion, UTC
disagreement or lost receive ownership revokes that request. Stale or
unavailable GPS keeps receive listening active at the frozen start grid. Uploads
continue only when the last fresh fixes established a parked position before GPS
loss; otherwise they pause until fresh GPS confirms the receiver is stationary
at the original position. Re-entry, reconnection and fresh GPS evidence leave
WSPR idle.

## Shared equipment and timing

- GPS remains owned by the existing poller. A start needs a valid fix and a
  continuously observed five seconds at or below 0.15 m/s. Position and advancing
  RMC UTC/motion evidence expire at four seconds. The system UTC is checked
  against chrony and the latest trusted GPS UTC using the existing FT8 clock calculation.
  WSPR samples chrony off the UI thread before receive and at slot changes.
  A synchronized chrony offset within 250 ms permits up to two seconds of GPS
  disagreement to account for receiver and serial delivery. With chrony unavailable,
  GPS must agree within one second. WSPR stops on a wall-clock shift greater than
  250 ms relative to monotonic time. If GPS becomes stale or unavailable during a
  session, receive listening continues at the frozen start position. Uploads remain
  enabled only if the last fresh fixes had established at least five seconds of
  stationary evidence immediately before loss; otherwise they pause until fresh
  GPS returns and confirms a stationary fix at the original position. After a
  GPS outage, uploads stay paused while the recovered fix indicates movement or
  displacement from the start. Once fresh GPS is available, WSPR stops when
  distinct fixes stay at least 50 feet from the frozen start position for five
  seconds.
  A fix inside the radius clears the motion confirmation, and repeated
  publications of the same fix do not advance it. GPS speed is used at start.
  A valid antenna and a physically parked vehicle remain operator requirements.
- At acceptance, freeze the current position for distance calculations and the
  four-character Maidenhead square for public reports. The dashboard previews
  that square. The upload adapter receives the grid and configured callsign.
- The single FT-891 adapter and its CAT operation lock guard receive ownership.
  Firmware TX and TX LED queries must agree with reception. These queries are
  advisory and never clear an FT8 transmit lockout. Active or preparing FT8,
  pending FT8 settings, shared spot tuning, Browse tuning and repeater setup
  inhibit acquisition. Background FT8 capture yields only when its decoder is
  idle and its audio workers quiesce. FT8 resumes after release.
- The reservation limits competing application CAT writes and prohibits CAT
  keying. Receiver frequency and mode changes reuse the existing band-memory
  sequence. WSPR leaves antenna tuning and ATAS controls alone.
  WSPR uses the shared DigiRig capture device through the ALSA pipe in USB with
  the FT-891 SSB BFO set to USB. It periodically verifies mode, BFO and
  frequency and checks them again at slot completion. A settings mismatch
  gets one read-only recheck, including RX verification, before stopping.
  A persistent mismatch identifies frequency, mode, or BFO. Cleanup preserves
  the original stop reason. On release, it restores
  previous frequency, mode and BFO if the firmware remains in RX and the WSPR
  settings are still in force. Physical front-panel controls remain under the
  operator's control.
- WSPR-2 windows begin on even UTC minutes. Capture takes 114 seconds at 12 kHz
  mono signed 16-bit PCM. Tune ahead of the boundary and allow at least two
  seconds to settle. The next band's tune can proceed while the previous slot
  decodes and reports. An incomplete window produces no results. An unverified
  band recall shows a skip and continues the rotation.

| Band | USB dial frequency |
| --- | ---: |
| 40 m | 7.038600 MHz |
| 30 m | 10.138700 MHz |
| 20 m | 14.095600 MHz |
| 17 m | 18.104600 MHz |
| 15 m | 21.094600 MHz |
| 12 m | 24.924600 MHz |
| 10 m | 28.124600 MHz |
| 6 m | 50.293000 MHz |

The frequencies, including the Region 2 six-meter center, follow the pinned
[WSJT-X frequency list](https://github.com/WSJTX/wsjtx/blob/967c85a6119110788b0df3782cf796485b2cee14/models/FrequencyList.cpp).
See the [WSJT-X WSPR guide](https://wsjt.sourceforge.io/wsjtx-doc/wsjtx-main-2.7.0.html#WSPR).

## Decoder and delivery

The package builds the separately licensed [pipe-only wsprd helper](../../tools/wsprd-pipe/README.md)
on Linux where a C compiler and FFTW development files are installed. The
dashboard can launch with the helper absent and reports the missing decoder
when started. The native process uses PCM stdin and decode stdout. It has no
audio file, decode journal, FFTW wisdom file, or persistent callsign hash.

The result worker makes fresh one-spot direct HTTPS attempts within the
current slot's 90-second decode and reporting budget. It uses the [WSJT-X upload form](https://github.com/WSJTX/wsjtx/blob/967c85a6119110788b0df3782cf796485b2cee14/Network/wsprnet.cpp)
and [WSPRnet HTTPS endpoint](https://wsprnet.org/post/) with curl 8.4 or later.
The [provider accepts four-character locator input](https://www.wsprnet.org/drupal/user/register).
Requests have four-second total deadlines, a 200 ms minimum start interval,
and a bounded response. An unavailable or unconfirmed request abandons the
rest of the current window's reports. A result already sent may reach the
provider after Stop. The screen can show that its acknowledgement is unknown.
There is no replay after network recovery and no reporting work on Forge.

### Bounded diagnostics

The dashboard configures a dedicated WSPR logger at
`<configured database directory>/rolling-thunder-wspr-debug.log`. It rotates at
1 MiB and keeps three backups. Entries record session lifecycle, band and UTC
slot, capture duration and byte count, decoder output count and duration, and
aggregate upload outcomes. They never record callsigns, locators, coordinates,
PCM, per-station decode fields, upload bodies, or provider response bodies.
These local aggregate diagnostics are retained only for troubleshooting and do
not feed station statistics or trigger retries.

Anonymous per-band counts and the closest/farthest acknowledged stations remain
in process memory only. The diagnostic file persists per-slot decode counts and
aggregate upload outcomes, without station identities or locations.

Distances are in statute miles from the frozen
session fix to each transmitted Maidenhead center. The session timer measures
monotonic time since acquisition. Decodes per hour use actual listening time
and all valid decodes for the local date. Local midnight clears that day's
counts, listening time and extrema while a live session keeps its timer and
frozen position. Restart clears all WSPR statistics.

## Acceptance

Use synthesized or recorded receive-only fixtures and a fake report endpoint
for automated checks. On a verified parked installation, check every band
recall, continued dashboard refresh, physical start/stop, navigation stop,
FT8/Browse handoff and actual WSPRnet acknowledgement. A full uninterrupted
rotation uses at least sixteen minutes including the eight receive slots.
The six-meter antenna and each FT-891 band memory must be validated on the
installed vehicle.
