"""Checkpoint 8 successful FT8 contact logging acceptance tests."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from rolling_thunder.contact_logging import ContactLoggingService
from rolling_thunder.contact_repository import ContactRepository
from rolling_thunder.domain import Contact, RadioMode, SynchronizationState
from rolling_thunder.ft8.coordinator import FT8QsoResult
from rolling_thunder.ft8.domain import FT8Period, FT8PeriodParity, FT8QsoContext, FT8QsoState
from rolling_thunder.ft8.logging import FT8QsoLoggingService
from rolling_thunder.wavelog import contact_to_adif


def _context(
    *,
    qso_id: str = "00000000-0000-0000-0000-000000000801",
    local_grid: str = "EM79xm",
    remote_grid: str | None = "FN31pr",
    radio_mode: str = "USB",
) -> FT8QsoContext:
    period = FT8Period(100)
    return FT8QsoContext(
        local_callsign="KI5VNB",
        remote_callsign="K1ABC",
        target_audio_frequency_hz=1500,
        radio_frequency_hz=14_074_000,
        radio_band="20m",
        radio_mode=radio_mode,
        local_grid=local_grid,
        latitude=39.5309 if local_grid == "EM79xm" else 39.9,
        longitude=-84.0866 if local_grid == "EM79xm" else -86.0,
        local_state="OH" if local_grid == "EM79xm" else "IN",
        local_cq_zone=4,
        local_itu_zone=8,
        tx_parity=FT8PeriodParity.ODD,
        authorized_period=period,
        authorized_utc=period.start_utc + timedelta(seconds=1),
        signal_report_db=14,
        remote_grid=remote_grid,
        qso_id=UUID(qso_id),
    )


def _result(
    *,
    status: FT8QsoState = FT8QsoState.COMPLETED,
    context: FT8QsoContext | None = None,
    received_report_db: int | None = -10,
) -> FT8QsoResult:
    started = datetime(2026, 9, 30, 20, 15, 1, tzinfo=UTC)
    return FT8QsoResult(
        status=status,
        context=context or _context(),
        sent_report_db=14,
        received_report_db=received_report_db,
        started_utc=started,
        ended_utc=started + timedelta(seconds=75),
        terminal_reason=None,
    )


def _service(database_path: Path) -> tuple[ContactRepository, FT8QsoLoggingService]:
    repository = ContactRepository(database_path)
    return repository, FT8QsoLoggingService(ContactLoggingService(repository))


def test_completed_ft8_result_logs_exact_frozen_snapshot_once(tmp_path: Path) -> None:
    repository, service = _service(tmp_path / "contacts.db")
    result = _result()

    first = service.handle_terminal_result(result)
    second = service.handle_terminal_result(result)

    assert first is not None
    assert second == first
    assert len(repository.list_all()) == 1
    assert repository.list_all()[0].my_latitude == 39.5309
    assert repository.list_all()[0].my_longitude == -84.0866
    assert first.contact_id == result.context.qso_id
    assert first.callsign == "K1ABC"
    assert first.frequency_hz == 14_074_000
    assert first.mode is RadioMode.FT8
    assert first.started_at == result.started_utc
    assert first.rst_sent == "+14"
    assert first.rst_received == "-10"
    assert first.grid == "FN31pr"
    assert first.my_grid == "EM79xm"
    assert (first.my_latitude, first.my_longitude) == (39.5309, -84.0866)
    assert (first.my_state, first.my_cq_zone, first.my_itu_zone) == ("OH", 4, 8)
    assert first.synchronization_state is SynchronizationState.PENDING


def test_idempotent_replay_survives_later_sync_state_change(tmp_path: Path) -> None:
    repository, service = _service(tmp_path / "contacts.db")
    result = _result()
    contact = service.handle_terminal_result(result)
    assert contact is not None

    repository.update_synchronization_state(
        contact.contact_id,
        SynchronizationState.SYNCHRONIZED,
    )

    replay = service.handle_terminal_result(result)

    assert replay is not None
    assert replay.synchronization_state is SynchronizationState.SYNCHRONIZED
    assert len(repository.list_all()) == 1
    assert repository.list_all()[0].my_latitude == 39.5309
    assert repository.list_all()[0].my_longitude == -84.0866


def test_non_success_terminal_outcomes_never_log(tmp_path: Path) -> None:
    repository, service = _service(tmp_path / "contacts.db")

    for state in (
        FT8QsoState.ABORTED,
        FT8QsoState.RETRY_EXHAUSTED,
        FT8QsoState.ERROR,
    ):
        assert service.handle_terminal_result(_result(status=state)) is None

    assert repository.list_all() == []


def test_completed_result_without_received_report_fails_closed(tmp_path: Path) -> None:
    repository, service = _service(tmp_path / "contacts.db")

    assert service.handle_terminal_result(_result(received_report_db=None)) is None
    assert repository.list_all() == []
    assert service.latest_error is not None


def test_frozen_grid_is_used_even_if_next_qso_starts_elsewhere(tmp_path: Path) -> None:
    repository, service = _service(tmp_path / "contacts.db")
    first_context = _context(
        qso_id="00000000-0000-0000-0000-000000000811",
        local_grid="EM79xm",
    )
    failed_context = _context(
        qso_id="00000000-0000-0000-0000-000000000812",
        local_grid="EM89aa",
    )
    next_context = _context(
        qso_id="00000000-0000-0000-0000-000000000813",
        local_grid="EM89aa",
    )

    first = service.handle_terminal_result(_result(context=first_context))
    assert first is not None
    assert first.my_grid == "EM79xm"
    assert (first.my_latitude, first.my_longitude) == (39.5309, -84.0866)

    assert service.handle_terminal_result(
        _result(status=FT8QsoState.RETRY_EXHAUSTED, context=failed_context)
    ) is None

    next_contact = service.handle_terminal_result(_result(context=next_context))
    assert next_contact is not None
    assert next_contact.my_grid == "EM89aa"
    assert (next_contact.my_latitude, next_contact.my_longitude) == (39.9, -86.0)
    assert (next_contact.my_state, next_contact.my_cq_zone, next_contact.my_itu_zone) == (
        "IN",
        4,
        8,
    )

    stored = {contact.contact_id: contact for contact in repository.list_all()}
    assert stored[first_context.qso_id].my_grid == "EM79xm"
    assert failed_context.qso_id not in stored
    assert stored[next_context.qso_id].my_grid == "EM89aa"


def test_ft8_contact_serializes_to_wavelog_as_mode_ft8() -> None:
    contact = Contact(
        contact_id=UUID("00000000-0000-0000-0000-000000000821"),
        callsign="K1ABC",
        frequency_hz=14_074_000,
        mode=RadioMode.FT8,
        started_at=datetime(2026, 9, 30, 20, 15, 1, tzinfo=UTC),
        rst_sent="+14",
        rst_received="-10",
        grid="FN31pr",
        my_grid="EM79xm",
    )

    adif = contact_to_adif(contact)

    assert "<MODE:3>FT8" in adif
    assert "<SUBMODE:" not in adif
    assert "<RST_SENT:3>+14" in adif
    assert "<RST_RCVD:3>-10" in adif
    assert "<MY_GRIDSQUARE:6>EM79xm" in adif
