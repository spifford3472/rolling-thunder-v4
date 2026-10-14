"""SQLite repository for offline antenna reference and RF exposure scenarios."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import UUID

from rolling_thunder.antenna_reference_domain import (
    AntennaCatalogEntry,
    AntennaInstallation,
    BandAssociation,
    ExposureScenario,
    FrequencyRegion,
    FrequencySegment,
    GainSegment,
    GainUnit,
    GroundReflectionModel,
    InstallationBandAssignment,
    LossSegment,
    ModeProfile,
    TextProvenance,
)
from rolling_thunder.domain import Frequency
from rolling_thunder.storage import StorageError, initialize_database


def _provenance(source: object, notes: object) -> TextProvenance:
    return TextProvenance(
        source=str(source),
        notes=None if notes is None else str(notes),
    )


class AntennaReferenceRepository:
    """Persist validated feature aggregates in the shared local SQLite database."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        initialize_database(database_path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def save_catalog(self, catalog: AntennaCatalogEntry) -> None:
        """Atomically insert or update an antenna and its sourced reference rows."""
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO antenna_catalog (
                        antenna_id, name, manufacturer, model, source,
                        provenance_notes, notes, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(antenna_id) DO UPDATE SET
                        name=excluded.name, manufacturer=excluded.manufacturer,
                        model=excluded.model, source=excluded.source,
                        provenance_notes=excluded.provenance_notes, notes=excluded.notes,
                        updated_at=CURRENT_TIMESTAMP
                    """,
                    (
                        str(catalog.antenna_id),
                        catalog.name,
                        catalog.manufacturer,
                        catalog.model,
                        catalog.provenance.source,
                        catalog.provenance.notes,
                        catalog.notes,
                    ),
                )
                self._replace_bands(connection, catalog)
                self._replace_gains(connection, catalog)
        except sqlite3.Error as error:
            raise StorageError(f"Antenna catalog could not be stored: {error}") from error

    @staticmethod
    def _replace_bands(
        connection: sqlite3.Connection, catalog: AntennaCatalogEntry
    ) -> None:
        ids = tuple(str(item.association_id) for item in catalog.bands)
        if ids:
            placeholders = ",".join("?" for _ in ids)
            connection.execute(
                f"""DELETE FROM antenna_band_associations
                    WHERE antenna_id = ? AND association_id NOT IN ({placeholders})""",
                (str(catalog.antenna_id), *ids),
            )
        else:
            connection.execute(
                "DELETE FROM antenna_band_associations WHERE antenna_id = ?",
                (str(catalog.antenna_id),),
            )
        for item in catalog.bands:
            connection.execute(
                """
                INSERT INTO antenna_band_associations (
                    association_id, antenna_id, label, region, lower_hz, upper_hz,
                    source, provenance_notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(association_id) DO UPDATE SET
                    antenna_id=excluded.antenna_id, label=excluded.label,
                    region=excluded.region, lower_hz=excluded.lower_hz,
                    upper_hz=excluded.upper_hz, source=excluded.source,
                    provenance_notes=excluded.provenance_notes
                """,
                (
                    str(item.association_id),
                    str(catalog.antenna_id),
                    item.label,
                    item.region.value,
                    item.frequencies.lower.hz,
                    item.frequencies.upper.hz,
                    item.provenance.source,
                    item.provenance.notes,
                ),
            )

    @staticmethod
    def _replace_gains(
        connection: sqlite3.Connection, catalog: AntennaCatalogEntry
    ) -> None:
        ids = tuple(str(item.gain_id) for item in catalog.gains)
        if ids:
            placeholders = ",".join("?" for _ in ids)
            connection.execute(
                f"""DELETE FROM antenna_gain_segments
                    WHERE antenna_id = ? AND gain_id NOT IN ({placeholders})""",
                (str(catalog.antenna_id), *ids),
            )
        else:
            connection.execute(
                "DELETE FROM antenna_gain_segments WHERE antenna_id = ?",
                (str(catalog.antenna_id),),
            )
        for item in catalog.gains:
            connection.execute(
                """
                INSERT INTO antenna_gain_segments (
                    gain_id, antenna_id, lower_hz, upper_hz, gain_db, gain_unit,
                    source, provenance_notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(gain_id) DO UPDATE SET
                    antenna_id=excluded.antenna_id, lower_hz=excluded.lower_hz,
                    upper_hz=excluded.upper_hz, gain_db=excluded.gain_db,
                    gain_unit=excluded.gain_unit, source=excluded.source,
                    provenance_notes=excluded.provenance_notes
                """,
                (
                    str(item.gain_id),
                    str(catalog.antenna_id),
                    item.frequencies.lower.hz,
                    item.frequencies.upper.hz,
                    item.gain_db,
                    item.unit.value,
                    item.provenance.source,
                    item.provenance.notes,
                ),
            )

    def get_catalog(self, antenna_id: UUID) -> AntennaCatalogEntry | None:
        """Read one antenna aggregate by stable UUID."""
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """SELECT name, manufacturer, model, source, provenance_notes, notes
                       FROM antenna_catalog WHERE antenna_id = ?""",
                    (str(antenna_id),),
                ).fetchone()
                if row is None:
                    return None
                band_rows = connection.execute(
                    """SELECT association_id, label, region, lower_hz, upper_hz,
                              source, provenance_notes
                       FROM antenna_band_associations WHERE antenna_id = ?
                       ORDER BY lower_hz, upper_hz, association_id""",
                    (str(antenna_id),),
                ).fetchall()
                gain_rows = connection.execute(
                    """SELECT gain_id, lower_hz, upper_hz, gain_db, gain_unit,
                              source, provenance_notes
                       FROM antenna_gain_segments WHERE antenna_id = ?
                       ORDER BY lower_hz, upper_hz, gain_id""",
                    (str(antenna_id),),
                ).fetchall()
        except sqlite3.Error as error:
            raise StorageError(f"Antenna catalog could not be read: {error}") from error

        bands = tuple(
            BandAssociation(
                association_id=UUID(item[0]),
                label=item[1],
                region=FrequencyRegion(item[2]),
                frequencies=FrequencySegment(
                    lower=Frequency(hz=item[3]), upper=Frequency(hz=item[4])
                ),
                provenance=_provenance(item[5], item[6]),
            )
            for item in band_rows
        )
        gains = tuple(
            GainSegment(
                gain_id=UUID(item[0]),
                frequencies=FrequencySegment(
                    lower=Frequency(hz=item[1]), upper=Frequency(hz=item[2])
                ),
                gain_db=item[3],
                unit=GainUnit(item[4]),
                provenance=_provenance(item[5], item[6]),
            )
            for item in gain_rows
        )
        return AntennaCatalogEntry(
            antenna_id=antenna_id,
            name=row[0],
            manufacturer=row[1],
            model=row[2],
            provenance=_provenance(row[3], row[4]),
            bands=bands,
            gains=gains,
            notes=row[5],
        )

    def list_catalog(self) -> tuple[AntennaCatalogEntry, ...]:
        """Return all antenna entries in deterministic display order."""
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT antenna_id FROM antenna_catalog ORDER BY name COLLATE NOCASE, antenna_id"
                ).fetchall()
        except sqlite3.Error as error:
            raise StorageError(f"Antenna catalog could not be listed: {error}") from error
        entries = tuple(self.get_catalog(UUID(row[0])) for row in rows)
        return tuple(item for item in entries if item is not None)

    def save_installation(self, installation: AntennaInstallation) -> None:
        """Atomically store a physical installation, losses, and active bands."""
        try:
            with self._connect() as connection:
                for assignment in installation.band_assignments:
                    owner = connection.execute(
                        "SELECT antenna_id FROM antenna_band_associations WHERE association_id = ?",
                        (str(assignment.association_id),),
                    ).fetchone()
                    if owner != (str(installation.antenna_id),):
                        raise StorageError(
                            "Installation band assignment does not belong to its antenna"
                        )
                connection.execute(
                    """
                    INSERT INTO antenna_installations (
                        installation_id, antenna_id, name, location_description,
                        losses_complete, source, provenance_notes, notes, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(installation_id) DO UPDATE SET
                        antenna_id=excluded.antenna_id, name=excluded.name,
                        location_description=excluded.location_description,
                        losses_complete=excluded.losses_complete, source=excluded.source,
                        provenance_notes=excluded.provenance_notes, notes=excluded.notes,
                        updated_at=CURRENT_TIMESTAMP
                    """,
                    (
                        str(installation.installation_id),
                        str(installation.antenna_id),
                        installation.name,
                        installation.location_description,
                        int(installation.losses_complete),
                        installation.provenance.source,
                        installation.provenance.notes,
                        installation.notes,
                    ),
                )
                self._replace_losses(connection, installation)
                self._replace_assignments(connection, installation)
        except StorageError:
            raise
        except sqlite3.Error as error:
            raise StorageError(f"Antenna installation could not be stored: {error}") from error

    @staticmethod
    def _replace_losses(
        connection: sqlite3.Connection, installation: AntennaInstallation
    ) -> None:
        connection.execute(
            "DELETE FROM antenna_loss_segments WHERE installation_id = ?",
            (str(installation.installation_id),),
        )
        connection.executemany(
            """INSERT INTO antenna_loss_segments (
                   loss_id, installation_id, name, lower_hz, upper_hz, loss_db,
                   source, provenance_notes
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            tuple(
                (
                    str(item.loss_id),
                    str(installation.installation_id),
                    item.name,
                    item.frequencies.lower.hz,
                    item.frequencies.upper.hz,
                    item.loss_db,
                    item.provenance.source,
                    item.provenance.notes,
                )
                for item in installation.loss_segments
            ),
        )

    @staticmethod
    def _replace_assignments(
        connection: sqlite3.Connection, installation: AntennaInstallation
    ) -> None:
        connection.execute(
            "DELETE FROM antenna_installation_band_assignments WHERE installation_id = ?",
            (str(installation.installation_id),),
        )
        connection.executemany(
            """INSERT INTO antenna_installation_band_assignments (
                   assignment_id, installation_id, association_id, active,
                   source, provenance_notes
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            tuple(
                (
                    str(item.assignment_id),
                    str(installation.installation_id),
                    str(item.association_id),
                    int(item.active),
                    item.provenance.source,
                    item.provenance.notes,
                )
                for item in installation.band_assignments
            ),
        )

    def get_installation(self, installation_id: UUID) -> AntennaInstallation | None:
        """Read one complete physical installation aggregate."""
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """SELECT antenna_id, name, location_description, losses_complete,
                              source, provenance_notes, notes
                       FROM antenna_installations WHERE installation_id = ?""",
                    (str(installation_id),),
                ).fetchone()
                if row is None:
                    return None
                loss_rows = connection.execute(
                    """SELECT loss_id, name, lower_hz, upper_hz, loss_db,
                              source, provenance_notes
                       FROM antenna_loss_segments WHERE installation_id = ?
                       ORDER BY lower_hz, upper_hz, loss_id""",
                    (str(installation_id),),
                ).fetchall()
                assignment_rows = connection.execute(
                    """SELECT assignment_id, association_id, active, source, provenance_notes
                       FROM antenna_installation_band_assignments WHERE installation_id = ?
                       ORDER BY association_id""",
                    (str(installation_id),),
                ).fetchall()
        except sqlite3.Error as error:
            raise StorageError(f"Antenna installation could not be read: {error}") from error

        return AntennaInstallation(
            installation_id=installation_id,
            antenna_id=UUID(row[0]),
            name=row[1],
            location_description=row[2],
            losses_complete=bool(row[3]),
            loss_segments=tuple(
                LossSegment(
                    loss_id=UUID(item[0]),
                    name=item[1],
                    frequencies=FrequencySegment(
                        lower=Frequency(hz=item[2]), upper=Frequency(hz=item[3])
                    ),
                    loss_db=item[4],
                    provenance=_provenance(item[5], item[6]),
                )
                for item in loss_rows
            ),
            band_assignments=tuple(
                InstallationBandAssignment(
                    assignment_id=UUID(item[0]),
                    association_id=UUID(item[1]),
                    active=bool(item[2]),
                    provenance=_provenance(item[3], item[4]),
                )
                for item in assignment_rows
            ),
            provenance=_provenance(row[4], row[5]),
            notes=row[6],
        )

    def list_installations(self) -> tuple[AntennaInstallation, ...]:
        """Return all physical installations in deterministic display order."""
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    """SELECT installation_id FROM antenna_installations
                       ORDER BY name COLLATE NOCASE, installation_id"""
                ).fetchall()
        except sqlite3.Error as error:
            raise StorageError(f"Antenna installations could not be listed: {error}") from error
        installations = tuple(self.get_installation(UUID(row[0])) for row in rows)
        return tuple(item for item in installations if item is not None)

    def save_mode_profile(self, profile: ModeProfile) -> None:
        """Store one explicit RF-envelope mode profile without seeding defaults."""
        try:
            with self._connect() as connection:
                connection.execute(
                    """INSERT INTO antenna_mode_profiles (
                           mode_profile_id, name, rf_envelope_duty, source,
                           provenance_notes, updated_at
                       ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                       ON CONFLICT(mode_profile_id) DO UPDATE SET
                           name=excluded.name, rf_envelope_duty=excluded.rf_envelope_duty,
                           source=excluded.source,
                           provenance_notes=excluded.provenance_notes,
                           updated_at=CURRENT_TIMESTAMP""",
                    (
                        str(profile.mode_profile_id),
                        profile.name,
                        profile.rf_envelope_duty,
                        profile.provenance.source,
                        profile.provenance.notes,
                    ),
                )
        except sqlite3.Error as error:
            raise StorageError(f"Antenna mode profile could not be stored: {error}") from error

    def get_mode_profile(self, profile_id: UUID) -> ModeProfile | None:
        """Read one RF-envelope mode profile."""
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """SELECT name, rf_envelope_duty, source, provenance_notes
                       FROM antenna_mode_profiles WHERE mode_profile_id = ?""",
                    (str(profile_id),),
                ).fetchone()
        except sqlite3.Error as error:
            raise StorageError(f"Antenna mode profile could not be read: {error}") from error
        if row is None:
            return None
        return ModeProfile(
            mode_profile_id=profile_id,
            name=row[0],
            rf_envelope_duty=row[1],
            provenance=_provenance(row[2], row[3]),
        )

    def save_scenario(self, scenario: ExposureScenario) -> None:
        """Store one independently configurable reference scenario."""
        try:
            with self._connect() as connection:
                connection.execute(
                    """INSERT INTO rf_exposure_scenarios (
                           scenario_id, installation_id, mode_profile_id, name,
                           frequency_hz, forward_tx_watts, controlled_tx_fraction,
                           uncontrolled_tx_fraction,
                           occupant_distance_m, occupant_distance_verified,
                           ground_reflection_model, source, provenance_notes, notes,
                           updated_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                       ON CONFLICT(scenario_id) DO UPDATE SET
                           installation_id=excluded.installation_id,
                           mode_profile_id=excluded.mode_profile_id, name=excluded.name,
                           frequency_hz=excluded.frequency_hz,
                           forward_tx_watts=excluded.forward_tx_watts,
                           controlled_tx_fraction=excluded.controlled_tx_fraction,
                           uncontrolled_tx_fraction=excluded.uncontrolled_tx_fraction,
                           occupant_distance_m=excluded.occupant_distance_m,
                           occupant_distance_verified=excluded.occupant_distance_verified,
                           ground_reflection_model=excluded.ground_reflection_model,
                           source=excluded.source,
                           provenance_notes=excluded.provenance_notes, notes=excluded.notes,
                           updated_at=CURRENT_TIMESTAMP""",
                    (
                        str(scenario.scenario_id),
                        str(scenario.installation_id),
                        str(scenario.mode_profile_id),
                        scenario.name,
                        scenario.frequency.hz,
                        scenario.forward_tx_watts,
                        scenario.controlled_tx_fraction,
                        scenario.uncontrolled_tx_fraction,
                        scenario.occupant_distance_m,
                        int(scenario.occupant_distance_verified),
                        scenario.ground_reflection_model.value,
                        scenario.provenance.source,
                        scenario.provenance.notes,
                        scenario.notes,
                    ),
                )
        except sqlite3.Error as error:
            raise StorageError(f"RF exposure scenario could not be stored: {error}") from error

    def get_scenario(self, scenario_id: UUID) -> ExposureScenario | None:
        """Read one reference scenario by stable UUID."""
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """SELECT installation_id, mode_profile_id, name, frequency_hz,
                              forward_tx_watts, controlled_tx_fraction,
                              uncontrolled_tx_fraction, occupant_distance_m,
                              occupant_distance_verified, ground_reflection_model,
                              source, provenance_notes, notes
                       FROM rf_exposure_scenarios WHERE scenario_id = ?""",
                    (str(scenario_id),),
                ).fetchone()
        except sqlite3.Error as error:
            raise StorageError(f"RF exposure scenario could not be read: {error}") from error
        if row is None:
            return None
        return ExposureScenario(
            scenario_id=scenario_id,
            installation_id=UUID(row[0]),
            mode_profile_id=UUID(row[1]),
            name=row[2],
            frequency=Frequency(hz=row[3]),
            forward_tx_watts=row[4],
            controlled_tx_fraction=row[5],
            uncontrolled_tx_fraction=row[6],
            occupant_distance_m=row[7],
            occupant_distance_verified=bool(row[8]),
            ground_reflection_model=GroundReflectionModel(row[9]),
            provenance=_provenance(row[10], row[11]),
            notes=row[12],
        )
