"""Offline normalization of archived PSK Reporter matched reports.

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

NORMALIZATION_VERSION = 1
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


def backfill(path: Path, *, apply: bool = False) -> dict[str, int]:
    """Dry-run is the default; never contacts the provider."""
    uri = f"file:{path}?mode={'rw' if apply else 'ro'}"
    with sqlite3.connect(uri, uri=True) as db:
        db.execute("PRAGMA foreign_keys=ON")
        if apply:
            create_schema(db)
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
    return {"contacts": count, "matched_reports": reports}


def retention_preview(path: Path, now: datetime | None = None) -> list[str]:
    """Only previews 90-day candidates; no deletion implementation exists."""
    threshold = ((now or datetime.now(UTC)) - timedelta(days=RAW_RETENTION_DAYS)).isoformat()
    with sqlite3.connect(f"file:{path}?mode=ro",uri=True) as db:
        candidates = db.execute(
            "SELECT query_id FROM pskreporter_query WHERE queried_at_utc<? AND raw_xml IS NOT NULL",
            (threshold,),
        ).fetchall()
    return [str(row[0]) for row in candidates]


def main() -> int:
    """Explicit offline operator entry point; no raw-data delete command exists."""
    import argparse

    parser = argparse.ArgumentParser(description="PSK history offline normalization/retention preview")
    parser.add_argument("--database", type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--backfill", action="store_true")
    action.add_argument("--retention-preview", action="store_true")
    parser.add_argument("--apply", action="store_true", help="Apply backfill (never deletes raw responses)")
    args = parser.parse_args()
    if args.apply and not args.backfill:
        parser.error("--apply is only valid for --backfill")
    if args.backfill:
        print(json.dumps({"mode": "apply" if args.apply else "dry-run", **backfill(args.database, apply=args.apply)}))
    else:
        print(json.dumps({"retention_days": RAW_RETENTION_DAYS, "raw_delete_enabled": False,
                          "candidate_query_ids": retention_preview(args.database)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
