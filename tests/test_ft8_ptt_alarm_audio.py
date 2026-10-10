"""Klaxon remains separate from DigiRig and is bounded in duration."""

from rolling_thunder.ft8.ptt_alarm_audio import klaxon_pcm


def test_klaxon_is_bounded_one_second_mono_s16() -> None:
    payload = klaxon_pcm()
    assert len(payload) == 16000 * 2
    assert any(payload)
