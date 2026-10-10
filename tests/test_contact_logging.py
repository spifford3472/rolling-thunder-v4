"""Tests for the dashboard-facing contact logging application service."""

from datetime import UTC, datetime

import pytest

from rolling_thunder.contact_logging import ContactCommitError, ContactLoggingService
from rolling_thunder.contact_weather import ContactWeatherSnapshot
from rolling_thunder.domain import (
    Contact,
    ContactEnrichmentState,
    ContactWeatherObservation,
    Frequency,
    GPSFixState,
    GPSPosition,
    RadioConnectionState,
    RadioMode,
    RadioState,
    SynchronizationState,
)
from rolling_thunder.gps import GPSConnectionState, GPSState
from rolling_thunder.local_jurisdiction import LocalJurisdictionResolver, StateBoundary
from rolling_thunder.pota_spots import ParkReference, PotaSpot


class FixedClock:
    """Return one deterministic timestamp."""

    def __init__(self, value: datetime) -> None:
        self._value = value

    def now(self) -> datetime:
        return self._value


class RecordingRepository:
    """Record contacts without physical storage."""

    def __init__(self) -> None:
        self.contacts: list[Contact] = []

    def add(self, contact: Contact) -> None:
        self.contacts.append(contact)


class FailingRepository:
    """Simulate a durable storage failure."""

    def add(self, contact: Contact) -> None:
        raise RuntimeError(f"storage failed for {contact.callsign}")


class FixedWeatherSnapshots:
    def capture(self, contact: Contact) -> ContactWeatherSnapshot:
        del contact
        return ContactWeatherSnapshot(
            contact=ContactWeatherObservation(summary="Remote cloudy; 18.0 C"),
            local=ContactWeatherObservation(summary="Local clear; 21.0 C"),
        )


def jurisdiction_resolver() -> LocalJurisdictionResolver:
    return LocalJurisdictionResolver(
        (
            StateBoundary(
                state="OH",
                polygons=((((-85.0, 38.0), (-80.0, 38.0), (-80.0, 42.0), (-85.0, 42.0)),),),
            ),
            StateBoundary(
                state="IN",
                polygons=((((-90.0, 38.0), (-85.0, 38.0), (-85.0, 42.0), (-90.0, 42.0)),),),
            ),
        )
    )


def connected_radio_state(*, transmitting: bool = False) -> RadioState:
    """Build a valid connected radio snapshot."""
    return RadioState(
        connection_state=RadioConnectionState.CONNECTED,
        frequency=Frequency(hz=14_250_000),
        mode=RadioMode.USB,
        transmitting=transmitting,
        updated_at=datetime(2026, 7, 25, 14, 0, tzinfo=UTC),
    )


def test_manual_commit_freezes_already_published_weather() -> None:
    repository = RecordingRepository()
    now = datetime(2026, 7, 25, 14, 5, tzinfo=UTC)
    service = ContactLoggingService(
        repository,
        FixedClock(now),
        weather_snapshot_provider=FixedWeatherSnapshots(),
    )

    contact = service.commit(
        pending_callsign="K1ABC",
        radio_state=connected_radio_state(),
        weather_notes_enabled=True,
    )

    assert repository.contacts == [contact]
    assert contact.contact_weather is not None
    assert contact.contact_weather.summary == "Remote cloudy; 18.0 C"
    assert contact.local_weather is not None
    assert contact.local_weather.summary == "Local clear; 21.0 C"


def test_commit_persists_normalized_contact_with_radio_state() -> None:
    """A successful Commit should persist exactly one complete local contact."""
    repository = RecordingRepository()
    started_at = datetime(2026, 7, 25, 14, 5, tzinfo=UTC)
    service = ContactLoggingService(repository, FixedClock(started_at))

    contact = service.commit(
        pending_callsign=" ki5vnb ",
        radio_state=connected_radio_state(),
    )

    assert repository.contacts == [contact]
    assert contact.callsign == "KI5VNB"
    assert contact.frequency_hz == 14_250_000
    assert contact.mode is RadioMode.USB
    assert contact.started_at == started_at
    assert contact.my_latitude is None
    assert contact.my_longitude is None
    assert contact.rst_sent == "59"
    assert contact.rst_received == "59"
    assert contact.synchronization_state is SynchronizationState.PENDING


def test_commit_persists_gps_and_unique_pota_metadata() -> None:
    repository = RecordingRepository()
    started_at = datetime(2026, 7, 25, 14, 5, tzinfo=UTC)
    service = ContactLoggingService(
        repository,
        FixedClock(started_at),
        jurisdiction_resolver=jurisdiction_resolver(),
    )
    position = GPSPosition(
        fix_state=GPSFixState.THREE_DIMENSIONAL,
        latitude=39.5309,
        longitude=-84.0866,
        altitude_m=250.0,
        updated_at=started_at,
    )
    gps_state = GPSState(
        connection_state=GPSConnectionState.CONNECTED,
        position=position,
        updated_at=started_at,
    )
    pota_spot = PotaSpot(
        activator="KI5VNB",
        park=ParkReference(
            reference="US-1234",
            latitude=40.0,
            longitude=-83.0,
        ),
        frequency=Frequency(hz=14_250_000),
        mode=RadioMode.USB,
        spotted_at=started_at,
    )

    contact = service.commit(
        pending_callsign="KI5VNB",
        radio_state=connected_radio_state(),
        gps_state=gps_state,
        pota_context_active=True,
        pota_spots=(pota_spot,),
    )

    assert contact.my_grid == "EM79wm"
    assert contact.my_latitude == 39.5309
    assert contact.my_longitude == -84.0866
    assert (contact.my_state, contact.my_cq_zone, contact.my_itu_zone) == ("OH", 4, 8)
    assert contact.grid == "EN80ma"
    assert contact.pota_reference == "US-1234"
    assert contact.notes == "POTA US-1234"


def test_commit_supports_explicit_signal_reports() -> None:
    """Later UI workflows may provide reports without changing persistence logic."""
    repository = RecordingRepository()
    service = ContactLoggingService(repository)

    contact = service.commit(
        pending_callsign="GB90MGY",
        radio_state=connected_radio_state(),
        rst_sent="57",
        rst_received="59",
    )

    assert contact.rst_sent == "57"
    assert contact.rst_received == "59"


@pytest.mark.parametrize(
    ("callsign", "radio_state", "message"),
    [
        ("", connected_radio_state(), "No pending callsign"),
        (
            "KI5VNB",
            RadioState(
                connection_state=RadioConnectionState.DISCONNECTED,
                updated_at=datetime(2026, 7, 25, 14, 0, tzinfo=UTC),
            ),
            "radio must be connected",
        ),
        ("KI5VNB", connected_radio_state(transmitting=True), "while the radio is transmitting"),
    ],
)
def test_commit_rejects_unsafe_or_incomplete_state(
    callsign: str,
    radio_state: RadioState,
    message: str,
) -> None:
    """Commit must fail before persistence when operator or radio state is unsafe."""
    repository = RecordingRepository()
    service = ContactLoggingService(repository)

    with pytest.raises(ContactCommitError, match=message):
        service.commit(pending_callsign=callsign, radio_state=radio_state)

    assert repository.contacts == []


def test_storage_failure_is_not_reported_as_success() -> None:
    """A repository failure must propagate so pending state can remain available."""
    service = ContactLoggingService(FailingRepository())

    with pytest.raises(RuntimeError, match="storage failed for KI5VNB"):
        service.commit(
            pending_callsign="KI5VNB",
            radio_state=connected_radio_state(),
        )


def test_commit_marks_qrz_fallback_pending_before_durable_write() -> None:
    repository = RecordingRepository()
    started_at = datetime(2026, 7, 25, 14, 5, tzinfo=UTC)
    service = ContactLoggingService(
        repository,
        FixedClock(started_at),
        qrz_fallback_available=True,
    )

    contact = service.commit(
        pending_callsign="W8O",
        radio_state=connected_radio_state(),
    )

    assert repository.contacts == [contact]
    assert contact.grid is None
    assert contact.enrichment_state is ContactEnrichmentState.PENDING_QRZ


@pytest.mark.parametrize(
    "state", [None, GPSConnectionState.DISCONNECTED, GPSFixState.NO_FIX, "stale"]
)
def test_unusable_gps_never_prevents_local_commit(state: object) -> None:
    repository = RecordingRepository()
    now = datetime(2026, 7, 25, 14, 5, tzinfo=UTC)
    gps = None
    if state is not None:
        gps = GPSState(
            connection_state=GPSConnectionState.DISCONNECTED
            if state is GPSConnectionState.DISCONNECTED
            else GPSConnectionState.CONNECTED,
            position=None
            if state is GPSConnectionState.DISCONNECTED
            else GPSPosition(
                fix_state=GPSFixState.NO_FIX
                if state is GPSFixState.NO_FIX
                else GPSFixState.THREE_DIMENSIONAL,
                latitude=None if state is GPSFixState.NO_FIX else 39.5309,
                longitude=None if state is GPSFixState.NO_FIX else -84.0866,
                updated_at=datetime(2026, 7, 25, 14, 0, tzinfo=UTC) if state == "stale" else now,
            ),
            updated_at=now,
        )
    qso = ContactLoggingService(repository, FixedClock(now)).commit(
        pending_callsign="K1ABC",
        radio_state=connected_radio_state(),
        gps_state=gps,
    )
    assert repository.contacts == [qso]
    assert qso.my_latitude is None and qso.my_longitude is None



def test_next_ordinary_contact_gets_fresh_jurisdiction_snapshot() -> None:
    repository = RecordingRepository()
    now = datetime(2026, 7, 25, 14, 5, tzinfo=UTC)
    service = ContactLoggingService(
        repository,
        FixedClock(now),
        jurisdiction_resolver=jurisdiction_resolver(),
    )

    def gps(longitude: float) -> GPSState:
        return GPSState(
            connection_state=GPSConnectionState.CONNECTED,
            position=GPSPosition(
                fix_state=GPSFixState.THREE_DIMENSIONAL,
                latitude=39.5,
                longitude=longitude,
                updated_at=now,
            ),
            updated_at=now,
        )

    first = service.commit(
        pending_callsign="K1ABC",
        radio_state=connected_radio_state(),
        gps_state=gps(-84.0),
    )
    second = service.commit(
        pending_callsign="K2ABC",
        radio_state=connected_radio_state(),
        gps_state=gps(-86.0),
    )

    assert (first.my_state, first.my_cq_zone, first.my_itu_zone) == ("OH", 4, 8)
    assert (second.my_state, second.my_cq_zone, second.my_itu_zone) == ("IN", 4, 8)
    assert repository.contacts == [first, second]
