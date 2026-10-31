"""Hackathon H1 part 1: the post-race Reveal (estimate vs truth, calls in context)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from pitwall_sim.engineer.commands import CommandType
from pitwall_sim.live.reveal import OFF_MJ, TOP_RIVALS
from pitwall_sim.live.session import LiveSession, LiveSetup

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def test_reveal_after_the_flag_only() -> None:
    s = LiveSession(LiveSetup(our_driver_id="GAS", laps=4, pause_on_alert=True), CONFIG_DIR)
    s.command(CommandType.SET_ENERGY_MODE, {"mode": "PUSH"})
    while s.advance(10.0) or s.paused_on_alert:
        assert s.reveal() is None  # no Rival truth before the flag (HR-03)
        if s.paused_on_alert:
            s.call(s.frame().alerts[0].alert_id, 1)
    reveal = s.reveal()
    assert reveal is not None
    assert len(reveal.rivals) == TOP_RIVALS
    battles = [r.battle_s for r in reveal.rivals]
    assert battles == sorted(battles, reverse=True) and battles[0] > 0.0
    for r in reveal.rivals:
        assert r.driver_id != "GAS" and r.lap.size == r.truth_mj.size > 100
        assert np.all(np.diff(r.t_s) > 0) and np.all((r.confidence >= 0) & (r.confidence <= 1))
    assert len(reveal.calls) == len(s.call_log) >= 2
    for c in reveal.calls:
        assert c.cost == "computing…" and c.position_after is not None  # filled by the flag
        assert c.rival is not None and c.truth_mj is not None and c.estimate_mj is not None
    assert reveal.calls_off == sum(abs(c.error_mj or 0.0) > OFF_MJ for c in reveal.calls)
    assert 0.0 < reveal.radar_mae_mj < 4.0
