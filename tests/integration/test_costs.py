"""Hackathon H1 part 2: decision costs from paired forks at each call's snapshot."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from pitwall_sim.engineer.commands import CommandType
from pitwall_sim.live import costs
from pitwall_sim.live.session import LiveSession, LiveSetup

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


@pytest.fixture(scope="module")
def finished() -> LiveSession:
    s = LiveSession(LiveSetup(our_driver_id="GAS", laps=3, pause_on_alert=True), CONFIG_DIR)
    s.advance(30.0)
    s.command(CommandType.SET_ENERGY_MODE, {"mode": "PUSH"})
    s.radio_message("box next lap mediums")
    while s.advance(10.0) or s.paused_on_alert:
        if s.paused_on_alert:
            s.call(s.frame().alerts[0].alert_id, 1)
    return s


def test_costs_only_after_the_flag() -> None:
    s = LiveSession(LiveSetup(our_driver_id="GAS", laps=3), CONFIG_DIR)
    s.command(CommandType.SET_ENERGY_MODE, {"mode": "PUSH"})
    with pytest.raises(RuntimeError):
        s.compute_cost(0)


def test_alternatives(finished: LiveSession) -> None:
    labels = [[o.label for o in costs.alternatives(r, spec)]
              for r, spec in zip(finished.call_log, finished.call_specs, strict=True)]  # fmt: skip
    assert labels[0] == ["SET_ENERGY_MODE", "not sent", "mode HARVEST"]  # BALANCED = not sent
    assert labels[1] == ["radio: BOX", "not sent", "BOX +1 lap"]
    alert_calls = [(r, ls) for r, ls in zip(finished.call_log, labels, strict=True) if r.alert_id]
    assert alert_calls, "the race should raise an alert"
    for record, ls in alert_calls:
        assert ls[0] == record.option_label and len(ls) == len(set(ls)) >= 2


def test_call_cost_is_paired_and_cached(finished: LiveSession, tmp_path: Path) -> None:
    record, spec = finished.call_log[1], finished.call_specs[1]
    snap = finished.snapshots[record.snapshot_id]
    start = time.perf_counter()
    cost = costs.call_cost(record, 1, spec, snap, "GAS", tmp_path)
    took = time.perf_counter() - start
    assert cost.n_seeds == costs.N_SEEDS and cost.delta_s >= 0.0
    assert cost.best_outcome_s <= cost.your_outcome_s
    assert cost.best_option_label in ("radio: BOX", "not sent", "BOX +1 lap")
    assert 30.0 < cost.your_outcome_s < 600.0  # two laps (or to the flag) in race seconds
    again = time.perf_counter()
    assert costs.call_cost(record, 1, spec, snap, "GAS", tmp_path) == cost  # from the cache
    assert time.perf_counter() - again < 0.2 * took
    # deterministic: the same forks give the same numbers
    assert costs.call_cost(record, 1, spec, snap, "GAS", None) == cost


def test_describe() -> None:
    from pitwall_sim.engineer.records import CallCost

    assert costs.describe(CallCost("c", 100.0, "x", 100.0, 0.0, 5)) == "best call"
    text = costs.describe(CallCost("c", 101.8, "BOX +1 lap", 100.0, 1.8, 5))
    assert text == "your call: +1.8 s vs best option (BOX +1 lap)"
