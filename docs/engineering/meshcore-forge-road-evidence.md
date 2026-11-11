# MeshCore Forge geographic evidence and analysis store (source-only)

Status: UNDEPLOYED and UNPOPULATED. No map data was downloaded or
installed; no existing service or traffic worker has been modified.

## Ownership and interfaces

ForgeRoadSiteCatalog owns a dedicated owner-private SQLite schema-1 catalog
of explicitly reviewed road-site evidence. Each item requires an exact road,
exit or mile marker, region, latitude/longitude, source, immutable source
record ID, source timestamp, review timestamp and site-specific assertion.
It refuses stale reviews (more than seven days), generic road centroids,
conflicting source record identities and multiple matching records. Both
source and review are human-attested; the software cannot verify the
truthfulness or map topology of an arbitrary imported record. A matching
roadway exit is a landmark, NOT an incident location or verified route.

ForgeMeshCoreGeoImport accepts only bounded local schema
meshcore/road-sites-import/v1 JSON with a separately stated
--accept-reviewed-evidence flag. It performs no external HTTP or scraping.
ForgeMeshCoreGeoMain provides a versioned JSON query-only CLI for health and
exact lookup; ForgeCatalogLookup bridges to the already existing disabled
geocoder interface for future reuse. No server/listener is deployed.

TrafficAssessmentRepository owns a separate owner-private SQLite schema-1
append-only store of analysis decisions and bounded query-only inspection.
It never writes the broker, message ledger, QSO database, SCOUT cursor,
radio configuration, or any GPS snapshot. It stores only numeric broker ID,
time, relevance, confidence, deterministic reason, optional map source,
approximate distance, and a digest; NO raw message text, private content,
sender identity or GPS track. Conflicting replays fail closed and no
automatic pruning or replacement occurs.

Source files:
- src/rolling_thunder/forge_meshcore_geo_catalog.py
- src/rolling_thunder/forge_meshcore_geo_import.py
- src/rolling_thunder/forge_meshcore_geo_main.py
- src/rolling_thunder/forge_meshcore_geo_adapter.py
- src/rolling_thunder/meshcore_traffic_analysis_repository.py

## Geographic-data source selection

Ohio DOT TIMS and Ohio Geospatial Open Data are candidate government
sources, not already imported data:
https://www.transportation.ohio.gov/business/apps/tims
https://das.ohio.gov/technology-and-strategy/OGRIP/data_services

A future reviewed import must establish exact highway, exit, location,
record identity, dataset lineage, precision, applicable license, refresh
and geographic ambiguity before enabling provider-backed analysis.
Never automatically poll public Nominatim in a background service.

## Proposed future paths and security

Forge catalog: /home/geoff/.local/share/rolling-thunder/meshcore-road-evidence.db
AnvilMobile separate audit:
  /home/geoff/.local/share/meshcore-collector/meshcore-traffic-assessments.db

Parent directories mode 0700, files 0600. These are proposed locations:
neither file is installed by this source milestone. No additional systemd
unit, cron, timer, public/private listener, firewall rule, or MeshCore
RF command exists. Forge provider access and credentials remain disabled.
No live service is changed by a GitHub merge alone.

## Operator workflow (NOT YET APPROVED FOR PRODUCTION)

Following a separate checked, site-specific data review, the operator can
run the offline import and read-only lookup from the Python module CLIs.
Never import raw channel text or private messages as geographic evidence.
The importer requires operator-reviewed local JSON and explicit opt-in.
The read-only CLI supports --health or --lookup ROAD EXIT_OR_MILE REGION.

## Tests, validation, and rollback

Synthetic focused checks cover exact lookup, unknown/conflicting references,
stale/future evidence, source-ID immutability, owner permissions, bounded
JSON import, no-network provider bridging, read-only health, immutable audit
replays and privacy. Ruff, MyPy and full pytest must pass before merging.

Actual source deployment SHA, installed paths and backups, provider identity,
data import, service activation, field accuracy and driving/FT8 acceptance
are UNVERIFIED and require separate approval and documentation.

Rollback, if a future independent analysis service is enabled: disable only
that new service; preserve new catalog/audit SQLite with online backups,
leave existing collector, broker, traffic worker, QSO and SCOUT files intact.
Rollback code through the approved exact-SHA wrapper after recording the
previous source identity. Never overwrite newer SQLite files from backup.

Change history: 2026-11-11 source-only foundation staged; no production
mutation. A later release must document real tests, maps, jobs, integration,
backup paths, validation and rollback in the QTH infrastructure repository.
