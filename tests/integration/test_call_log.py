"""Hackathon session 1: every engineer call is a CallRecord with a forkable snapshot."""

from __future__ import annotations

from pathlib import Path

from pitwall_sim.engineer.commands import CommandType
from pitwall_sim.live.session import LiveSession, LiveSetup
from pitwall_sim.race.snapshot import restore

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def test_alert_options_and_buttons_are_logged_with_snapshots() -> None:
    s = LiveSession(
        LiveSetup(our_driver_id="HAM", preset="repass", pause_on_alert=True), CONFIG_DIR
    )
    assert s.command(CommandType.SET_ENERGY_MODE, {"mode": "PUSH"}, say="Push now.") is None
    while not s.paused_on_alert and s.advance(5.0):
        pass
    alert = s.frame().alerts[0]
    s.call(alert.alert_id, 1)
    button, answered = s.call_log
    assert button.alert_id is None and button.option_label == str(CommandType.SET_ENERGY_MODE)
    assert len(button.command_ids) == 1 and button.lap == 1
    assert answered.alert_id == alert.alert_id and answered.t_s == s.t_s
    assert answered.option_label and answered.command_ids
    for record in s.call_log:
        snap = s.snapshots[record.snapshot_id]
        assert snap.t == record.t_s
        forked = restore(snap)  # the decision-cost forks start here
        forked.tick()
        assert forked.t > record.t_s
    # the snapshot is taken before the call: its own command is not queued in it
    snap = s.snapshots[button.snapshot_id]
    assert button.command_ids[0] not in {c.command_id for c in snap.command_log}
    events = s.frame().view.radio_log
    said = [e for e in events if e.sender == "ENGINEER" and e.text == "Push now."]
    assert said and said[0].command_ids == button.command_ids
    assert all(e.sender in ("ENGINEER", "DRIVER") for e in events)


def test_rejected_button_is_not_a_call() -> None:
    s = LiveSession(LiveSetup(our_driver_id="HAM"), CONFIG_DIR)
    reason = s.command(CommandType.SET_ENERGY_MODE, {"mode": "NOPE"})
    assert reason is not None and s.call_log == []


def test_radio_message_sends_commands_through_validation() -> None:
    """H2: typed radio -> validated commands, one CallRecord each, driver ack, next-lap step."""
    s = LiveSession(LiveSetup(our_driver_id="HAM", laps=4), CONFIG_DIR)
    s.advance(20.0)
    assert s.radio_message("Save this lap, attack into turn 1 next lap") == []
    engine = s.engine
    queued = engine.pending_commands + engine.applied_commands
    assert [c.type for c in queued] == [CommandType.SET_ENERGY_MODE]
    labels = [r.option_label for r in s.call_log]
    assert labels == ["radio: SET_ENERGY_MODE", "radio: SET_ENERGY_MODE (next lap)",
                      "radio: ATTACK (next lap)"]  # fmt: skip
    assert len({r.snapshot_id for r in s.call_log}) == 1
    lap = s.frame().view.our_car.lap
    while s.frame().view.our_car.lap == lap:
        s.advance(5.0)
    s.advance(1.0)
    sent = [c.type for c in engine.pending_commands + engine.applied_commands]
    assert sent.count(CommandType.SET_ENERGY_MODE) == 2 and CommandType.ATTACK in sent
    events = s.frame().view.radio_log
    engineer = [e for e in events if e.sender == "ENGINEER"]
    driver = [e for e in events if e.sender == "DRIVER"]
    assert engineer[0].source == "TEXT" and len(engineer[0].command_ids) == 1
    assert driver and driver[0].text.startswith("Copy, saving this lap")


def test_radio_rejection_and_say_again() -> None:
    s = LiveSession(LiveSetup(our_driver_id="HAM", laps=4), CONFIG_DIR)
    s.advance(5.0)
    reasons = s.radio_message("cancel box")  # no stop pending: validation rejects it
    assert reasons and "no stop is pending" in reasons[0] and s.call_log == []
    assert any(line.rejected for line in s.radio)
    s.radio_message("banana smoothie")
    s.advance(3.0)
    driver = [e for e in s.frame().view.radio_log if e.sender == "DRIVER"]
    assert driver[-1].text == "Say again?" and driver[-1].is_fallback
