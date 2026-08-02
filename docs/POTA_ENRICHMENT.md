# POTA Enrichment and Park Detail Overlay

## Purpose

Rolling Thunder can optionally enrich the mobile POTA panel with:

- operator names and optional primary profile photos from the QRZ XML
  callsign-data service
- current park temperature, condition, and park-local 24-hour time from
  Open-Meteo
- a generalized U.S. state outline from the U.S. Census TIGERweb service
- a generalized DX first-level subdivision or country outline from the
  geoBoundaries `gbOpen` service
- a locally rendered park-location pin using the coordinates already supplied
  by the POTA spot feed

These services enhance the POTA display only. They are not required for POTA
spot retrieval, local logging, radio state, filtering, encoder selection, or
receive-only tune intent.

All network work runs outside the Tkinter thread. A failed or unavailable
provider leaves the rest of the POTA panel operational.

## QRZ Account Requirement

QRZ callsign enrichment uses the QRZ XML callsign-data service. It requires the
QRZ account username and password used to create an XML session key.

The separate QRZ Logbook API key is not used by the XML callsign-data service.

When QRZ credentials are absent, POTA cards continue to show callsigns without
names. The park overlay shows a generated callsign badge instead of a profile
photo.

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

Visible POTA cards are queued for background QRZ profile lookup. Until the
lookup finishes, the card shows only the callsign. A successful cached result is
shown as:

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
3. The park detail card appears over the reserved situational panel.

The card displays:

- park name and POTA reference
- a U.S. state, DX subdivision, or DX country map on the left
- the park coordinates marked by a pin
- the focused activator's QRZ primary photo on the right when available
- a generated callsign badge when no suitable QRZ photo is available
- temperature in Fahrenheit and Celsius
- one familiar current-condition weather symbol
- park-local time in 24-hour format

For DX parks, Rolling Thunder first tries to match the POTA location code to a
geoBoundaries ADM1 subdivision. If the subdivision code is unavailable or does
not match, the map falls back to the country's ADM0 outline. POTA location codes
follow ISO-3166-2 whenever practical, which makes ADM1 matching possible for
most countries and territories.

Weather symbols are limited to:

- `☀` clear daytime
- `☾` clear nighttime
- `⛅` partly cloudy
- `☁` cloudy or fog
- `☂` drizzle or rain
- `❄` snow
- `⚡` thunderstorm

The card disappears when:

- 20 seconds elapse
- Context #3 is long-pressed
- the operator changes panels

Context #3 does nothing when no POTA spot is focused.

## Provider Failure Behavior

- QRZ unavailable: callsign-only cards and the callsign badge remain usable.
- QRZ profile has no primary photo: the callsign badge is displayed.
- Weather unavailable or coordinates missing: temperature, symbol, and local
  time show `NOT AVAILABLE`.
- U.S. Census or geoBoundaries unavailable: the map area shows
  `MAP NOT AVAILABLE` while QRZ and weather data remain visible.
- One provider fails: successful data from the other providers remains visible.
- Internet unavailable: POTA spot cache and all local application functions
  continue according to their existing behavior.

## Data and Image Safety

Map adapters request generalized boundaries as GeoJSON in a background worker.
Successful results are retained in the bounded in-memory enrichment cache.
Tkinter draws the outline and park pin locally; no map tiles or embedded browser
are used.

U.S. outlines are supplied by the U.S. Census Bureau. DX outlines use the
geoBoundaries `gbOpen` dataset from William & Mary geoLab under CC BY 4.0.

QRZ profile-image URLs are accepted only from `qrz.com` or its subdomains. The
image is downloaded in the background, limited in size, normalized to a bounded
PNG with Pillow, and then delivered to Tkinter as immutable cached data.
