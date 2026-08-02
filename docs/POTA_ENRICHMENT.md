# POTA Enrichment and Park Detail Overlay

## Purpose

Rolling Thunder can optionally enrich the mobile POTA panel with:

- operator names from the QRZ XML callsign-data service
- current park temperature from Open-Meteo
- park-local 24-hour time from Open-Meteo
- a freely licensed park image from Wikimedia Commons when available

These services enhance the POTA display only. They are not required for POTA
spot retrieval, local logging, radio state, filtering, encoder selection, or
receive-only tune intent.

All network work runs outside the Tkinter thread. A failed or unavailable
provider leaves the rest of the POTA panel operational.

## QRZ Account Requirement

QRZ callsign-name lookup uses the QRZ XML callsign-data service. It requires the
QRZ account username and password used to create an XML session key.

The separate QRZ Logbook API key is not used by the XML callsign-data service.

When QRZ credentials are absent, POTA cards continue to show callsigns without
names.

## Local Secret File

Never place QRZ credentials in:

- `config/rolling-thunder.yaml`
- any tracked repository file
- shell commands containing literal credentials
- logs
- issue or pull-request text

Create the local secret file on `anvilmobile` with an interactive no-echo prompt:

```bash
install -d -m 700 "$HOME/.config/rolling-thunder"
umask 077

read -r -p "QRZ username: " QRZ_USERNAME
read -r -s -p "QRZ password: " QRZ_PASSWORD
printf '\n'

{
    printf 'export ROLLING_THUNDER_QRZ_USERNAME=%q\n' "$QRZ_USERNAME"
    printf 'export ROLLING_THUNDER_QRZ_PASSWORD=%q\n' "$QRZ_PASSWORD"
} > "$HOME/.config/rolling-thunder/secrets.env"

unset QRZ_USERNAME QRZ_PASSWORD
chmod 600 "$HOME/.config/rolling-thunder/secrets.env"
```

The password is not echoed while it is entered. The `%q` formatting writes a
Bash-safe escaped value without printing it to the terminal.

Verify permissions without displaying the file contents:

```bash
stat -c '%a %U %G %n' \
  "$HOME/.config/rolling-thunder/secrets.env"
```

Expected permissions:

```text
600 geoff geoff /home/geoff/.config/rolling-thunder/secrets.env
```

Do not use `cat`, `grep`, `set -x`, or other commands that would display the
secret values.

## Starting the Dashboard from SSH

Load the local environment file into the process that launches Rolling Thunder:

```bash
cd /home/geoff/projects/rolling-thunder-v4 || exit 1
source .venv/bin/activate
source "$HOME/.config/rolling-thunder/secrets.env"

export DISPLAY=:0
export XAUTHORITY="$HOME/.Xauthority"

rolling-thunder-ui
```

Both QRZ variables must be set together. An incomplete pair stops startup with a
configuration error that names the missing variable but does not reveal either
value.

## Operator Behavior

### Callsign names

Visible POTA cards are queued for background name lookup. Until the lookup
finishes, the card shows only the callsign. A successful cached result is shown
as:

```text
KI5VNB - Geoff Kline
```

Portable suffixes such as `/P` are removed only for the QRZ query. The callsign
shown by the POTA spot remains unchanged.

Successful and negative results are cached in memory with bounded retention to
avoid repeated requests. The cache is not part of the contact log.

### Park detail overlay

On the POTA panel:

1. Rotate the encoder to focus a spot.
2. Short-press Context #3.
3. The park detail card appears over the reserved map panel.

The card displays:

- park name
- park image or `NOT AVAILABLE`
- temperature in Fahrenheit and Celsius
- park-local time in 24-hour format
- image attribution and license when an image is shown

The card disappears when:

- 20 seconds elapse
- Context #3 is long-pressed
- the operator changes panels

Context #3 does nothing when no POTA spot is focused.

## Provider Failure Behavior

- QRZ unavailable: callsign-only cards remain usable.
- Weather unavailable or coordinates missing: temperature and local time show
  `NOT AVAILABLE`.
- No suitable licensed image: the image area shows `NOT AVAILABLE`.
- One park-detail provider fails: successful data from the other provider is
  still displayed.
- Internet unavailable: POTA spot cache and all local application functions
  continue according to their existing behavior.

## Image Licensing

The image adapter accepts only Commons metadata indicating a freely reusable
license such as Creative Commons, CC0, or public domain. Non-free and restricted
results are rejected. When an image is displayed, its contributor attribution
and short license name are shown below it.

The image is normalized to PNG and bounded in size before it reaches Tkinter.
