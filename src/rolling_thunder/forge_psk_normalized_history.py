"""Offline normalization of complete archived PSK Reporter responses.

Never queries the network or prunes original data. Query provenance and
contact associations remain stable even when overlapping queries occur.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from rolling_thunder.maidenhead import maidenhead_grid_center

NORMALIZATION_VERSION = 2
RAW_RETENTION_DAYS = 90


def create_schema(db: sqlite3.Connection) -> None:
    db.executescript("""
    CREATE TABLE IF NOT EXISTS psk_reception (
        reception_id TEXT PRIMARY KEY,
        record_fingerprint TEXT NOT NULL,
        occurrence INTEGER NOT NULL,
        sender_callsign TEXT NOT NULL,
        receiver_callsign TEXT NOT NULL,
        receiver_locator_raw TEXT,
        receiver_locator_normalized TEXT,
        locator_quality TEXT NOT NULL,
        receiver_latitude REAL,
        receiver_longitude REAL,
        frequency_hz INTEGER NOT NULL,
        flow_start_utc TEXT NOT NULL,
        snr_db INTEGER,
        mode TEXT,
        sequence_number INTEGER,
        first_seen_query_id TEXT NOT NULL REFERENCES pskreporter_query(query_id),
        normalization_version INTEGER NOT NULL,
        UNIQUE(record_fingerprint, occurrence)
    );
    CREATE TABLE IF NOT EXISTS psk_qso_reception (
        contact_id TEXT NOT NULL,
        reception_id TEXT NOT NULL REFERENCES psk_reception(reception_id),
        query_id TEXT NOT NULL REFERENCES pskreporter_query(query_id),
        PRIMARY KEY(contact_id, reception_id)
    );
    CREATE TABLE IF NOT EXISTS psk_normalization_audit (
        contact_id TEXT PRIMARY KEY,
        query_id TEXT NOT NULL REFERENCES pskreporter_query(query_id),
        expected_count INTEGER NOT NULL,
        linked_count INTEGER NOT NULL,
        raw_sha256 TEXT,
        normalization_version INTEGER NOT NULL,
        normalized_at_utc TEXT NOT NULL,
        CHECK (linked_count = expected_count)
    );
    CREATE TABLE IF NOT EXISTS psk_query_normalization_audit (
        query_id TEXT PRIMARY KEY REFERENCES pskreporter_query(query_id),
        raw_sha256 TEXT NOT NULL,
        parsed_count INTEGER NOT NULL,
        skipped_count INTEGER NOT NULL,
        provider_record_count INTEGER NOT NULL,
        normalized_count INTEGER NOT NULL,
        normalized_at_utc TEXT NOT NULL,
        normalization_version INTEGER NOT NULL,
        CHECK(provider_record_count = parsed_count + skipped_count),
        CHECK(normalized_count = parsed_count)
    );
    CREATE INDEX IF NOT EXISTS idx_psk_reception_time ON psk_reception(flow_start_utc);
    CREATE INDEX IF NOT EXISTS idx_psk_reception_freq ON psk_reception(frequency_hz,flow_start_utc);
    CREATE INDEX IF NOT EXISTS idx_psk_reception_receiver ON psk_reception(receiver_callsign,flow_start_utc);
    """)


def _locator(value: Any) -> tuple[str | None, str]:
    if not isinstance(value, str) or not value.strip():
        return None, "missing"
    candidate = value.strip().upper()
    if len(candidate) not in (2, 4, 6, 8, 10, 12):
        return None, "invalid"
    for pair in range(len(candidate) // 2):
        a = candidate[pair * 2]
        b = candidate[pair * 2 + 1]
        upper = "ABCDEFGHIJKLMNOPQR" if pair == 0 else ("0123456789" if pair % 2 else "ABCDEFGHIJKLMNOPQRSTUVWX")
        if pair == 0:
            upper = "ABCDEFGHIJKLMNOPQR"
        elif pair % 2:
            upper = "0123456789"
        else:
            upper = "ABCDEFGHIJKLMNOPQRSTUVWX"
        if a not in upper or b not in upper:
            return None, "invalid"
    return candidate, "valid"


def normalize_summary(
    db: sqlite3.Connection, *, contact_id: str, query_id: str,
    matched_reports: list[dict[str, Any]], raw_xml: str | None,
) -> tuple[int, int]:
    """Idempotently normalize one QSO. Called within the caller's transaction."""
    prior = db.execute(
        "SELECT expected_count,linked_count FROM psk_normalization_audit WHERE contact_id=?",
        (contact_id,),
    ).fetchone()
    if prior is not None:
        if prior != (len(matched_reports), len(matched_reports)):
            raise ValueError("existing normalization count does not match archived reports")
        digest = hashlib.sha256(raw_xml.encode()).hexdigest() if raw_xml is not None else None
        audit = db.execute(
            "SELECT query_id,raw_sha256 FROM psk_normalization_audit WHERE contact_id=?",
            (contact_id,),
        ).fetchone()
        if audit != (query_id, digest):
            raise ValueError("normalization provenance changed; refuse silent overwrite")
        return int(prior[0]), int(prior[1])
    offsets: Counter[str] = Counter()
    for r in matched_reports:
        facts = {
            "sender": str(r["sender_callsign"]).upper(),
            "receiver": str(r["receiver_callsign"]).upper(),
            "locator": r.get("receiver_locator"),
            "frequency": int(r["frequency_hz"]),
            "time": r["flow_start_utc"],
            "snr": r.get("snr_db"),
            "mode": r.get("mode"),
            "sequence": r.get("sequence_number"),
        }
        encoded = json.dumps(facts, sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
        occurrence = offsets[fingerprint]
        offsets[fingerprint] += 1
        rid = hashlib.sha256(f"{fingerprint}:{occurrence}".encode()).hexdigest()
        grid, quality = _locator(r.get("receiver_locator"))
        coordinates = None
        if grid and len(grid) in (4, 6, 8):
            coordinates = maidenhead_grid_center(grid)
        db.execute(
            """INSERT OR IGNORE INTO psk_reception
               (reception_id,record_fingerprint,occurrence,sender_callsign,
                receiver_callsign,receiver_locator_raw,receiver_locator_normalized,
                locator_quality,receiver_latitude,receiver_longitude,frequency_hz,
                flow_start_utc,snr_db,mode,sequence_number,first_seen_query_id,
                normalization_version)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (rid, fingerprint, occurrence, facts["sender"], facts["receiver"],
             facts["locator"], grid, quality,
             None if coordinates is None else coordinates[0],
             None if coordinates is None else coordinates[1],
             facts["frequency"], facts["time"],
             facts["snr"], facts["mode"], facts["sequence"], query_id,
             NORMALIZATION_VERSION),
        )
        db.execute(
            "INSERT OR IGNORE INTO psk_qso_reception(contact_id,reception_id,query_id) VALUES (?,?,?)",
            (contact_id, rid, query_id),
        )
    linked = db.execute(
        "SELECT COUNT(*) FROM psk_qso_reception WHERE contact_id=?", (contact_id,)
    ).fetchone()[0]
    if linked != len(matched_reports):
        raise ValueError(f"normalization mismatch for {contact_id}: {linked}/{len(matched_reports)}")
    digest = hashlib.sha256(raw_xml.encode()).hexdigest() if raw_xml is not None else None
    db.execute(
        """INSERT INTO psk_normalization_audit
           (contact_id,query_id,expected_count,linked_count,raw_sha256,
            normalization_version,normalized_at_utc) VALUES (?,?,?,?,?,?,?)""",
        (contact_id, query_id, len(matched_reports), linked, digest,
         NORMALIZATION_VERSION, datetime.now(UTC).isoformat()),
    )
    return len(matched_reports), linked


def normalize_provider_query(
    db: sqlite3.Connection, *, query_id: str, raw_xml: str,
    skipped_expected: int,
) -> tuple[int, int]:
    """Normalize EVERY valid provider observation, regardless of QSO association.

    Idempotent across repeated runs. Requires complete source and reconciles
    parse/rejection counts before recording a durable audit.
    """
    # Local import avoids circular dependency with the repository used by client.
    from rolling_thunder.forge_pskreporter import parse_pskreporter_xml

    digest = hashlib.sha256(raw_xml.encode()).hexdigest()
    prior = db.execute(
        "SELECT raw_sha256,parsed_count,skipped_count FROM psk_query_normalization_audit "
        "WHERE query_id=?", (query_id,),
    ).fetchone()
    reports, skipped = parse_pskreporter_xml(raw_xml)
    if skipped != skipped_expected:
        raise ValueError(f"provider skipped-record discrepancy for {query_id}: "
                         f"{skipped} != {skipped_expected}")
    if prior is not None:
        if prior != (digest, len(reports), skipped):
            raise ValueError(f"provider query {query_id} changed after normalization")
        return len(reports), skipped
    values = [report.model_dump(mode="json") for report in reports]
    # Reuse existing deterministic IDs and duplicate occurrence policy.
    # Dummy QSO associations are never generated: insert only receptions.
    offsets: Counter[str] = Counter()
    for r in values:
        facts = {
            "sender": str(r["sender_callsign"]).upper(),
            "receiver": str(r["receiver_callsign"]).upper(),
            "locator": r.get("receiver_locator"),
            "frequency": int(r["frequency_hz"]),
            "time": r["flow_start_utc"],
            "snr": r.get("snr_db"),
            "mode": r.get("mode"),
            "sequence": r.get("sequence_number"),
        }
        fingerprint = hashlib.sha256(
            json.dumps(facts, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        occurrence = offsets[fingerprint]
        offsets[fingerprint] += 1
        rid = hashlib.sha256(f"{fingerprint}:{occurrence}".encode()).hexdigest()
        grid, quality = _locator(r.get("receiver_locator"))
        coordinates = maidenhead_grid_center(grid) if grid and len(grid) in (4, 6, 8) else None
        db.execute(
            """INSERT OR IGNORE INTO psk_reception (
                reception_id,record_fingerprint,occurrence,sender_callsign,
                receiver_callsign,receiver_locator_raw,receiver_locator_normalized,
                locator_quality,receiver_latitude,receiver_longitude,
                frequency_hz,flow_start_utc,snr_db,mode,sequence_number,
                first_seen_query_id,normalization_version
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (rid,fingerprint,occurrence,facts["sender"],facts["receiver"],
             facts["locator"],grid,quality,
             None if coordinates is None else coordinates[0],
             None if coordinates is None else coordinates[1],
             facts["frequency"],facts["time"],facts["snr"],
             facts["mode"],facts["sequence"],query_id,NORMALIZATION_VERSION),
        )
    db.execute(
        """INSERT INTO psk_query_normalization_audit
           (query_id,raw_sha256,parsed_count,skipped_count,provider_record_count,
            normalized_count,normalized_at_utc,normalization_version)
           VALUES (?,?,?,?,?,?,?,?)""",
        (query_id,digest,len(reports),skipped,len(reports)+skipped,
         len(reports),datetime.now(UTC).isoformat(),NORMALIZATION_VERSION),
    )
    return len(reports), skipped


def backfill(path: Path, *, apply: bool = False) -> dict[str, int]:
    """Dry-run is the default; never contacts the provider."""
    uri = f"file:{path}?mode={'rw' if apply else 'ro'}"
    with sqlite3.connect(uri, uri=True) as db:
        db.execute("PRAGMA foreign_keys=ON")
        if apply:
            create_schema(db)
        provider_rows = db.execute(
            "SELECT query_id,raw_xml,skipped_record_count FROM pskreporter_query "
            "WHERE status='succeeded' AND raw_xml IS NOT NULL ORDER BY queried_at_utc"
        ).fetchall()
        provider_reports = 0
        for qid, xml, skipped in provider_rows:
            from rolling_thunder.forge_pskreporter import parse_pskreporter_xml
            parsed, actual_skipped = parse_pskreporter_xml(xml)
            if actual_skipped != skipped:
                raise ValueError(f"provider skipped count mismatch for {qid}")
            provider_reports += len(parsed)
            if apply:
                normalize_provider_query(
                    db,query_id=qid,raw_xml=xml,skipped_expected=skipped
                )
        rows = db.execute("""
            SELECT s.contact_id,s.query_id,s.raw_response_json,q.raw_xml
            FROM qso_pskreporter_summary AS s
            JOIN pskreporter_query AS q ON s.query_id=q.query_id
            WHERE s.status IN ('queried_with_reports','queried_zero_reports')
            ORDER BY s.queried_at_utc,s.contact_id
        """).fetchall()
        count = 0
        reports = 0
        for cid, qid, raw, xml in rows:
            payload = json.loads(raw or "{}")
            matched = payload.get("matched_reports", [])
            if not isinstance(matched, list):
                raise TypeError(f"invalid matched report data for {cid}")
            count += 1
            reports += len(matched)
            if apply:
                normalize_summary(db,contact_id=cid,query_id=qid,matched_reports=matched,raw_xml=xml)
        if apply:
            db.commit()
    return {"contacts": count, "matched_reports": reports,
            "provider_queries": len(provider_rows),
            "provider_receptions": provider_reports}


def retention_preview(path: Path, now: datetime | None = None) -> list[str]:
    """Only previews 90-day candidates; no deletion implementation exists."""
    threshold = ((now or datetime.now(UTC)) - timedelta(days=RAW_RETENTION_DAYS)).isoformat()
    with sqlite3.connect(f"file:{path}?mode=ro",uri=True) as db:
        candidates = db.execute(
            "SELECT query_id FROM pskreporter_query WHERE queried_at_utc<? AND raw_xml IS NOT NULL",
            (threshold,),
        ).fetchall()
    return [str(row[0]) for row in candidates]


def prune_eligible_raw(
    path: Path, *, backup_evidence: Path, now: datetime | None = None,
) -> int:
    """Operator-only pruning, fail closed without independent backup proof.

    Evidence must be an independently made SQLite backup, with the entire
    source provider query (including raw XML) available and hash-identical.
    The backup is never written by this function.
    """
    if not backup_evidence.is_file() or backup_evidence.resolve() == path.resolve():
        raise ValueError("an independent, verified SQLite backup is required")
    candidates = retention_preview(path, now=now)
    if not candidates:
        return 0
    with sqlite3.connect(f"file:{backup_evidence}?mode=ro",uri=True) as backup:
        if backup.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise ValueError("backup integrity check failed")
        backed_up = {
            qid: xml for qid, xml in backup.execute(
                "SELECT query_id,raw_xml FROM pskreporter_query WHERE raw_xml IS NOT NULL"
            )
        }
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA foreign_keys=ON")
        for qid in candidates:
            row = db.execute(
                "SELECT raw_xml,skipped_record_count,status FROM pskreporter_query "
                "WHERE query_id=?", (qid,)
            ).fetchone()
            if row is None or row[2] != "succeeded" or row[0] is None:
                raise ValueError(f"query not safely eligible: {qid}")
            # Do not discard malformed provider records until their original
            # attributes have a separately reviewed durable quarantine format.
            if row[1] != 0:
                raise ValueError(f"query has skipped provider records: {qid}")
            digest = hashlib.sha256(row[0].encode()).hexdigest()
            if backed_up.get(qid) != row[0]:
                raise ValueError(f"backup does not preserve original XML: {qid}")
            audit = db.execute(
                "SELECT raw_sha256,parsed_count,skipped_count,normalized_count "
                "FROM psk_query_normalization_audit WHERE query_id=?", (qid,)
            ).fetchone()
            if audit is None or audit != (digest,audit[1],row[1],audit[1]):
                raise ValueError(f"incomplete provider normalization audit: {qid}")
            refs = db.execute(
                "SELECT contact_id,raw_response_json FROM qso_pskreporter_summary "
                "WHERE query_id=?", (qid,)
            ).fetchall()
            for cid, raw_json in refs:
                qa = db.execute(
                    "SELECT expected_count,linked_count,raw_sha256 "
                    "FROM psk_normalization_audit WHERE contact_id=? AND query_id=?",
                    (cid,qid),
                ).fetchone()
                if qa is None or qa[0] != qa[1] or qa[2] != digest:
                    raise ValueError(f"incomplete QSO audit: {cid}")
                raw = json.loads(raw_json or "{}")
                if len(raw.get("matched_reports",[])) != qa[0]:
                    raise ValueError(f"QSO original rows mismatch: {cid}")
        for qid in candidates:
            db.execute("UPDATE pskreporter_query SET raw_xml=NULL WHERE query_id=?", (qid,))
            # Do not change per-QSO JSON until consumers migrate.
        db.commit()
    return len(candidates)


def main() -> int:
    """Explicit offline operator entry point; no raw-data delete command exists."""
    import argparse

    parser = argparse.ArgumentParser(description="PSK history offline normalization/retention preview")
    parser.add_argument("--database", type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--backfill", action="store_true")
    action.add_argument("--retention-preview", action="store_true")
    action.add_argument("--prune-raw", action="store_true")
    parser.add_argument("--backup-evidence", type=Path)
    parser.add_argument("--apply", action="store_true", help="Apply backfill (never deletes raw responses)")
    args = parser.parse_args()
    if args.apply and args.retention_preview:
        parser.error("--apply is invalid for --retention-preview")
    if args.backfill:
        print(json.dumps({"mode": "apply" if args.apply else "dry-run", **backfill(args.database, apply=args.apply)}))
    elif args.retention_preview:
        print(json.dumps({"retention_days": RAW_RETENTION_DAYS,
                          "candidate_query_ids": retention_preview(args.database)}))
    else:
        if not args.apply or args.backup_evidence is None:
            parser.error("--prune-raw requires --apply and --backup-evidence")
        print(json.dumps({"pruned_queries": prune_eligible_raw(
            args.database,backup_evidence=args.backup_evidence
        )}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
