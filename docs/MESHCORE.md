# MeshCore USB Channel Notifications

Rolling Thunder can receive live channel messages from a MeshCore companion
device over USB serial and present selected channels on the map. This integration
is receive/display only. It does not send channel messages, radio commands, PTT,
MOX, tuning, or any other RF-transmit action.

## Configuration

Configure the machine-local YAML with the stable USB device path:

```yaml
meshcore:
  enabled: true
  device: /dev/serial/by-id/usb-your-meshcore-companion
  baud_rate: 115200
  command_timeout_s: 2.0
  channels:
    - "#hamradio"
    - "#skywarn"
    - "#traffic"
  message_overlay_seconds: 20
  reconnect_delay_s: 2.0
```

`device` must be an absolute path. Prefer `/dev/serial/by-id/...` so USB device
numbering changes do not redirect the adapter. Channel matching is
case-insensitive and configuration-driven.

The adapter uses the official `meshcore` Python library's serial companion
transport. The connected device must run companion firmware that exposes the
MeshCore companion protocol over USB; a repeater text console is not compatible.

## Live-only behavior

On startup and every reconnect, Rolling Thunder reads the configured channel
slots and drains the device's queued message backlog without publishing it. The
overlay becomes active only after that baseline is complete, so stored messages
do not appear merely because the application starts or USB reconnects.

Each new configured-channel message replaces the current notification. There is
no unbounded UI queue. The replacement receives a fresh configured display
period. Messages on other channels are ignored.

The black notification is drawn in the lower-left of the retained map canvas.
It contains a green bold channel header and a separately rendered white message.
Long content is wrapped and safely ellipsized to five message lines. Expiration
deletes only the notification canvas items; map and radar tiles are not fetched,
decoded, destroyed, or rebuilt as a consequence.

## Threading and recovery

`MeshCoreReceiveService` owns a daemon worker. USB connection, channel discovery,
startup synchronization, message fetching, disconnect handling, and reconnect
delay all occur in that worker. The Tk refresh loop reads only the immutable,
lock-protected `MeshCoreMessageOverlay` snapshot.

MeshCore device loss therefore cannot block Tk, local logging, map/radar updates,
GPS, POTA/DX, DMR, physical controls, or radio polling. The optional worker
retries after the configured delay and establishes a new live-only baseline on
every successful reconnect.

## Physical acceptance

The automated suite uses fakes and does not prove the installed device path,
firmware mode, channel-slot names, USB disconnect behavior, or full-screen
geometry. Validate those items on `anvilmobile` before merge.
