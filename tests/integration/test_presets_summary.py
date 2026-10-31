"""Sprint day 4: setup presets produce their alert; end-of-race call summary (A-4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pitwall_sim.live.presets import REPASS_OUR_MJ, grid_order
from pitwall_sim.live.session import LiveSession, LiveSetup

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
TARGET = {"repass": "REPASS_RISK", "closing_speed": "CLOSING_SPEED_RISK"}


@pytest.mark.parametrize("preset", ["repass", "closing_speed"])
@pytest.mark.parametrize("our", ["GAS", "HAM"])
def test_preset_produces_its_alert_in_the_first_3_laps(preset: str, our: str) -> None:
    s = LiveSession(LiveSetup(our_driver_id=our, preset=preset), CONFIG_DIR)  # type: ignore[arg-type]
    while s.engine.st.lap[s.engine.our_index] < 3 and s.advance(5.0):
        if any(r.alert.type == TARGET[preset] for r in s.calls):
            break
    assert any(r.alert.type == TARGET[preset] for r in s.calls), [r.alert.type for r in s.calls]


def test_presets_change_only_starting_conditions() -> None:
    default = ("A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O")
    assert grid_order("none", "C", default) is None
    assert grid_order("repass", "C", default).index("C") == 9  # type: ignore[union-attr]
    assert grid_order("closing_speed", "C", default).index("C") == 13  # type: ignore[union-attr]
    s = LiveSession(LiveSetup(our_driver_id="GAS", preset="repass"), CONFIG_DIR)
    i = s.engine.our_index
    assert i is not None and s.preset_rival is not None
    r = s.engine.driver_ids.index(s.preset_rival)
    assert s.engine.st.battery_j[i] == pytest.approx(REPASS_OUR_MJ * 1e6)
    assert s.engine.st.battery_j[r] == 0.0


@pytest.fixture(scope="module")
def finished() -> LiveSession:
    """Run a short Test-mode race, answering every alert with option 1."""
    s = LiveSession(
        LiveSetup(our_driver_id="HAM", preset="repass", test_mode=True, laps=5), CONFIG_DIR
    )
    while s.advance(2.0):
        for alert in s.frame().alerts:
            s.call(alert.alert_id, 1)
    return s


def test_summary_lists_every_alert_with_call_and_outcome(finished: LiveSession) -> None:
    summary = finished.summary()
    assert summary.alerts == len(summary.records) > 0
    outcomes = {"pass made", "no pass", "position kept", "position lost", "re-passed"}
    for r in summary.records:
        assert r.outcome in outcomes
        assert r.option != "pending"
    assert summary.calls_made == sum(r.answered for r in summary.records)
    attacks = [r for r in summary.records if r.alert.type == "ATTACK" and r.answered]
    assert summary.successful_attacks == sum(r.outcome == "pass made" for r in attacks)
    judged = [r for r in summary.records if r.alert.type in ("ATTACK", "DEFEND")]
    assert summary.judged == len(judged)
    assert all(r.true_diff_mj is not None for r in summary.records)  # Test mode


def test_summary_without_test_mode_has_no_truth() -> None:
    s = LiveSession(LiveSetup(our_driver_id="HAM", preset="repass", laps=2), CONFIG_DIR)
    while s.advance(5.0):
        pass
    summary = s.summary()
    assert summary.correct is None and summary.judged is None
    assert all(r.true_diff_mj is None and r.correct is None for r in summary.records)
