"""Sprint S-5 / A-3: live pit wall lite runs smoothly; alert buttons send the A-2 commands."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from pytestqt.qtbot import QtBot  # noqa: E402

from pitwall_sim.engineer.commands import CommandType  # noqa: E402
from pitwall_sim.live.session import LiveSession, LiveSetup  # noqa: E402
from pitwall_sim.ui.pitwall_lite import PitWallWindow  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
T = CommandType


def _window(qtbot: QtBot, **setup: object) -> tuple[PitWallWindow, LiveSession]:
    session = LiveSession(LiveSetup(**{"our_driver_id": "GAS", **setup}), CONFIG_DIR)  # type: ignore[arg-type]
    window = PitWallWindow(session, start_speed="PAUSE")
    qtbot.addWidget(window)
    window.resize(1480, 900)
    window.show()
    return window, session


def test_thirty_seconds_at_16x_without_a_slow_frame(qtbot: QtBot) -> None:
    window, session = _window(qtbot)
    window.set_speed("16x")
    qtbot.waitUntil(lambda: session.t_s >= 30.0, timeout=20000)
    window.set_speed("PAUSE")
    assert len(window.frame_times) >= 20
    slowest_ms = 1e3 * max(window.frame_times)
    print(f"\n16x: {len(window.frame_times)} frames, slowest {slowest_ms:.0f} ms (limit 100 ms)")
    assert max(window.frame_times) < 0.100, max(window.frame_times)
    assert window.tower.item(0, 1).text()  # the tower is filled
    window.close()


def _until_alert(qtbot: QtBot, window: PitWallWindow, session: LiveSession) -> str:
    window.set_speed("16x")
    qtbot.waitUntil(lambda: session.paused_on_alert, timeout=60000)
    qtbot.waitUntil(lambda: bool(window._cards), timeout=5000)
    frame = session.frame()
    return frame.alerts[0].alert_id


def _sent(session: LiveSession) -> list[tuple[CommandType, dict[str, object]]]:
    cmds = session.engine.pending_commands + session.engine.applied_commands
    return [(c.type, c.params) for c in sorted(cmds, key=lambda c: c.issued_at_s)]


def test_option_button_sends_the_option_commands(qtbot: QtBot) -> None:
    window, session = _window(qtbot, pause_on_alert=True, our_driver_id="HAM", preset="repass")
    alert_id = _until_alert(qtbot, window, session)
    alert = session.frame().alerts[0]
    option = session.frame().options[alert_id][0]
    expected = [cmd for step in option.steps if step.when == "now" for cmd in step.commands]
    qtbot.mouseClick(window._cards[alert_id].buttons[1], Qt.MouseButton.LeftButton)
    got = [(kind, params) for kind, params in _sent(session)]
    assert [(k, {p: str(v) for p, v in ps.items()}) for k, ps in got] == [
        (k, {p: str(v) for p, v in ps.items()}) for k, ps in expected
    ], alert
    assert alert_id not in window._cards and not session.paused_on_alert
    assert any(line.sender == "ENGINEER" for line in session.radio)
    window.close()


def test_f1_answers_the_newest_alert(qtbot: QtBot) -> None:
    window, session = _window(qtbot, pause_on_alert=True, our_driver_id="HAM", preset="repass")
    alert_id = _until_alert(qtbot, window, session)
    option = session.frame().options[alert_id][0]
    qtbot.keyClick(window, Qt.Key.Key_F1)
    record = next(r for r in session.calls if r.alert.alert_id == alert_id)
    assert record.option == option.label
    window.set_speed("4x")
    start = time.perf_counter()
    qtbot.waitUntil(lambda: any(line.sender == "DRIVER" for line in session.radio)
                    or time.perf_counter() - start > 10, timeout=15000)  # fmt: skip
    if option.ack:
        assert any(line.text == option.ack for line in session.radio)  # template ack
    window.close()


def test_test_mode_shows_true_battery_only_when_chosen(qtbot: QtBot) -> None:
    plain, session = _window(qtbot)
    assert session.frame().truth_mj is None and "TEST MODE" not in plain.windowTitle()
    plain.close()
    test, session_t = _window(qtbot, test_mode=True)
    truth = session_t.frame().truth_mj
    assert truth is not None and "GAS" not in truth and len(truth) == 21
    assert "TEST MODE" in test.windowTitle()
    test.close()


@pytest.mark.parametrize("speed", ["PAUSE", "1x", "4x", "16x"])
def test_speed_buttons(qtbot: QtBot, speed: str) -> None:
    window, _ = _window(qtbot)
    qtbot.mouseClick(window.speed_buttons[speed], Qt.MouseButton.LeftButton)
    assert window.thread_.speed == {"PAUSE": 0.0, "1x": 1.0, "4x": 4.0, "16x": 16.0}[speed]
    window.close()


def test_call_summary_opens_at_the_flag(qtbot: QtBot) -> None:
    window, session = _window(qtbot, laps=2, preset="repass", test_mode=True)
    window.set_speed("16x")
    qtbot.waitUntil(lambda: window.summary_dialog is not None, timeout=60000)
    dialog = window.summary_dialog
    assert dialog is not None and session.engine.finished
    assert dialog.table.rowCount() == session.summary().alerts > 0
    assert dialog.table.horizontalHeaderItem(dialog.table.columnCount() - 1).text() == (
        "alert right? (test)"
    )
    reveal = dialog.reveal_tab  # H1: the Reveal tab at the flag
    assert reveal is not None and len(reveal.plots) == 3
    cost = reveal.table.columnCount() - 1
    assert reveal.table.horizontalHeaderItem(cost).text() == "cost"
    assert reveal.table.rowCount() == len(session.call_log)
    assert all(reveal.table.item(r, cost).text() == "computing…"
               for r in range(reveal.table.rowCount()))  # fmt: skip
    dialog.close()
    window.close()


def test_setup_screen_race_laps(qtbot: QtBot) -> None:
    """Day 9: a short race distance reaches the flag (and the call summary) quickly."""
    from pitwall_sim.ui.setup_screen import SetupScreen

    screen = SetupScreen(CONFIG_DIR)
    qtbot.addWidget(screen)
    assert screen.choice().laps == 15  # hackathon H7: a 15-lap race by default
    screen.laps.setValue(screen.full_laps)
    assert screen.choice().laps is None  # the full race
    screen.laps.setValue(3)
    assert screen.choice().laps == 3
    assert screen.choice().scripted_sc_lap is None  # no Safety Car unless chosen
    screen.sc_lap.setValue(7)
    assert screen.choice().scripted_sc_lap == 7


def test_radio_box_sends_a_message(qtbot: QtBot) -> None:
    """H2: typing in the radio box and pressing Enter sends parsed commands."""
    window, session = _window(qtbot)
    qtbot.keyClicks(window.radio_input, "push")
    qtbot.keyClick(window.radio_input, Qt.Key.Key_Return)
    assert window.radio_input.text() == ""
    assert [r.option_label for r in session.call_log] == ["radio: SET_ENERGY_MODE"]
    window.close()


def test_16x_is_16x(qtbot: QtBot) -> None:
    """The clock runs at the chosen speed, not faster (whole engine ticks used to overshoot)."""
    window, session = _window(qtbot)
    window.set_speed("16x")
    qtbot.waitUntil(lambda: session.t_s >= 5.0, timeout=20000)
    t0, w0 = session.t_s, time.perf_counter()
    qtbot.wait(3000)
    rate = (session.t_s - t0) / (time.perf_counter() - w0)
    window.set_speed("PAUSE")
    assert 12.0 < rate < 17.5, rate
    window.close()


def test_telemetry_tab_fills_with_a_ghost_at_16x(qtbot: QtBot) -> None:
    """H6: speed / throttle / battery vs lap distance; the previous lap as a ghost."""
    window, _ = _window(qtbot)
    window.trace_tabs.setCurrentWidget(window.telemetry_panel)
    window.set_speed("16x")
    qtbot.waitUntil(lambda: window.telemetry.telemetry.has_ghost, timeout=60000)
    qtbot.wait(1000)
    window.set_speed("PAUSE")
    x, _ = window.telemetry.curves["speed"].getData()
    gx, _ = window.telemetry.ghosts["battery"].getData()
    assert x is not None and gx is not None and len(gx) > 50 and len(x) > 0
    assert max(window.frame_times) < 0.100, max(window.frame_times)
    window.close()


def test_reveal_engineer_score_fills_after_the_costs(qtbot: QtBot) -> None:
    """E2: 'computing' until every call's cost is in, then the score out of 100."""
    from pitwall_sim.engineer.records import CallCost
    from pitwall_sim.ui.pitwall_lite import RevealTab

    window, session = _window(qtbot, laps=1)
    assert session.command(T.SET_ENERGY_MODE, {"mode": "PUSH"}, "Push.") is None
    assert session.command(T.SET_ENERGY_MODE, {"mode": "HARVEST"}, "Harvest.") is None
    window.set_speed("16x")
    qtbot.waitUntil(lambda: session.engine.finished, timeout=60000)
    window.set_speed("PAUSE")
    reveal = session.reveal()
    assert reveal is not None and len(reveal.calls) == 2
    tab = RevealTab(reveal, session.drivers)
    qtbot.addWidget(tab)
    costs: list[CallCost] = []
    tab.enable_score(20.0, lambda: list(costs))
    assert "computing" in tab.score_label.text()
    costs.append(CallCost("a#0", 101.0, "HOLD", 100.0, 1.0, 5))
    tab.set_cost(0, "your call: +1.0 s vs best option (HOLD)")
    assert "computing" in tab.score_label.text() and "1 / 2" in tab.score_label.text()
    costs.append(CallCost("a#1", 100.0, "HARVEST", 100.0, 0.0, 5))
    tab.set_cost(1, "best call")
    assert tab.score_label.text() == "Engineer score: 95 / 100"  # 100 exp(-1 / 20)
    assert "2 calls, 1 best" in tab.score_line.text()
    window.close()
