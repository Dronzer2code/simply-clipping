"""T-041: Rival Strategy AI rules (PF-10), scalar and compiled paths agree."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from pitwall_sim.config.loader import load_app
from pitwall_sim.config.models import Compound, EnergyMode, RivalStrategyConfig
from pitwall_sim.driver.ai_driver import DriverInstructions
from pitwall_sim.race import rival_strategy as RS

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"


@pytest.fixture(scope="module")
def cfg() -> RivalStrategyConfig:
    return load_app(CONFIG_DIR).rival_strategy


def _view(**kw: object) -> RS.RivalView:
    base: dict[str, object] = {
        "driver_id": "A", "laps_done": 10, "race_laps": 53, "battery_mj": 2.5,
        "line_battery_mj": 2.5, "tyre_wear": 0.2, "in_pit_lane": False,
        "gap_ahead_s": 5.0, "gap_behind_s": 5.0, "ahead": None, "behind": None,
    }  # fmt: skip
    base.update(kw)
    return RS.RivalView(**base)  # type: ignore[arg-type]


def _plan(**kw: object) -> RS.RivalPlan:
    base: dict[str, object] = {
        "driver_id": "A", "stop_lap": 25, "next_compound": Compound.HARD, "aggression": 0.5,
    }  # fmt: skip
    base.update(kw)
    return RS.RivalPlan(**base)  # type: ignore[arg-type]


def test_plans_follow_style_teammates_and_seed(cfg: RivalStrategyConfig) -> None:
    drivers, teams = ("A1", "A2", "B1", "B2"), ("a", "a", "b", "b")
    styles = {"a": "AGGRESSIVE", "b": "CONSERVATIVE"}

    def plans(seed: int) -> dict[str, RS.RivalPlan]:
        return RS.make_plans(
            drivers, teams, styles, {"a": 0.8}, 53, Compound.MEDIUM, cfg,
            np.random.default_rng(seed),
        )  # fmt: skip

    p = plans(42)
    assert p == plans(42)  # HR-04: the plan comes from the seeded stream only
    jitter = cfg.stop_jitter_laps
    for driver, style, order in (("A1", "AGGRESSIVE", 0), ("B2", "CONSERVATIVE", 1)):
        due = round(53 * cfg.stop_fraction[style]) + order * cfg.teammate_offset_laps  # type: ignore[index]
        assert abs(p[driver].stop_lap - due) <= jitter
    assert p["A1"].aggression == 0.8 and p["B1"].aggression == 0.5  # missing -> 0.5
    assert all(q.next_compound == Compound.HARD for q in p.values())
    hard = RS.make_plans(
        drivers, teams, styles, {}, 53, Compound.HARD, cfg, np.random.default_rng(42)
    )
    assert all(q.next_compound == Compound.MEDIUM for q in hard.values())
    # Too short for a stop: the plan never comes due.
    short = RS.make_plans(
        drivers, teams, styles, {}, 3, Compound.MEDIUM, cfg, np.random.default_rng(1)
    )
    now = DriverInstructions()
    for q in short.values():
        assert all(
            RS.decide(_view(laps_done=lap, race_laps=3), q, now, cfg).box_for is None
            for lap in range(4)
        )


def test_harvest_hysteresis_reads_the_battery_at_the_line(cfg: RivalStrategyConfig) -> None:
    plan, now = _plan(), DriverInstructions()
    low = cfg.low_battery_mj
    # A dip mid-lap does not switch the mode; the line value does.
    assert (
        RS.decide(_view(battery_mj=low / 2), plan, now, cfg).instructions.mode
        == EnergyMode.BALANCED
    )
    d = RS.decide(_view(line_battery_mj=low / 2), plan, now, cfg)
    assert d.instructions.mode == EnergyMode.HARVEST and plan.harvesting
    between = (cfg.low_battery_mj + cfg.recover_battery_mj) / 2
    assert (
        RS.decide(_view(line_battery_mj=between), plan, now, cfg).instructions.mode
        == EnergyMode.HARVEST
    )
    d = RS.decide(_view(line_battery_mj=cfg.recover_battery_mj), plan, now, cfg)
    assert d.instructions.mode == EnergyMode.BALANCED and not plan.harvesting
    final = _view(laps_done=53 - cfg.push_final_laps)
    assert RS.decide(final, _plan(), now, cfg).instructions.mode == EnergyMode.PUSH


def test_battle_flags_use_the_radar_estimate(cfg: RivalStrategyConfig) -> None:
    plan, now, gap = _plan(), DriverInstructions(), cfg.battle_gap_s / 2
    weak = RS.OpponentEstimate("B", 0.5, 0.8)
    strong = RS.OpponentEstimate("B", 4.0, 0.8)
    unknown = RS.OpponentEstimate("B", 0.0, 0.0)
    attack = RS.decide(_view(gap_ahead_s=gap, ahead=weak), plan, now, cfg).instructions
    assert attack.attack and not attack.hold_position
    hold = RS.decide(_view(gap_ahead_s=gap, ahead=strong), plan, now, cfg).instructions
    assert hold.hold_position and not hold.attack
    # No confidence: assumed level with own battery -> no attack.
    level = RS.decide(_view(gap_ahead_s=gap, ahead=unknown), plan, now, cfg).instructions
    assert level.hold_position
    assert RS.decide(_view(gap_behind_s=gap, behind=weak), plan, now, cfg).instructions.defend
    assert not RS.decide(_view(gap_behind_s=gap, behind=strong), plan, now, cfg).instructions.defend
    out = RS.decide(_view(gap_ahead_s=2 * cfg.battle_gap_s, ahead=weak), plan, now, cfg)
    assert out.instructions == now  # out of battle: nothing changes


def test_pit_calls(cfg: RivalStrategyConfig) -> None:
    now = DriverInstructions()
    plan = _plan(stop_lap=25)
    early = 25 - cfg.window_laps - 1
    assert RS.decide(_view(laps_done=early), plan, now, cfg).box_for is None
    assert RS.decide(_view(laps_done=25), plan, now, cfg).box_for == Compound.HARD
    worn = _view(laps_done=25 - cfg.window_laps, tyre_wear=cfg.wear_threshold)
    assert RS.decide(worn, plan, now, cfg).box_for == Compound.HARD
    undercut = _view(laps_done=25 - cfg.window_laps, gap_behind_s=cfg.undercut_gap_s / 2)
    assert RS.decide(undercut, plan, now, cfg).box_for == Compound.HARD
    assert RS.decide(_view(laps_done=25, in_pit_lane=True), plan, now, cfg).box_for is None
    done = _plan(stop_lap=25, stops_done=1)
    assert RS.decide(_view(laps_done=30), done, now, cfg).box_for is None
    critical = _view(laps_done=5, tyre_wear=cfg.critical_wear)
    assert RS.decide(critical, done, now, cfg).box_for == Compound.HARD  # extra stop
    last = _view(laps_done=53 - cfg.no_stop_last_laps, tyre_wear=1.0)
    assert RS.decide(last, plan, now, cfg).box_for is None


def test_compiled_decisions_match_the_scalar_rules(cfg: RivalStrategyConfig) -> None:
    """``decide_book`` row by row equals :func:`decide` over random situations."""
    rng = np.random.default_rng(42)
    n, race_laps = 400, 53
    plans = {
        f"D{k}": _plan(
            driver_id=f"D{k}", stop_lap=int(rng.integers(15, 35)),
            aggression=float(rng.uniform(0.0, 1.0)), stops_done=int(rng.integers(0, 2)),
            harvesting=bool(rng.random() < 0.3),
        )
        for k in range(n)
    }  # fmt: skip
    ids = tuple(plans)
    book = RS.RivalBook.from_plans(plans, ids)
    battery = rng.uniform(0.0, 4.0, n)
    line = np.where(rng.random(n) < 0.5, rng.uniform(0.0, 4.0, n), battery)
    wear = rng.uniform(0.0, 1.0, n)
    laps = rng.integers(0, race_laps, n)
    pit = rng.random(n) < 0.1
    gap_a = np.where(rng.random(n) < 0.2, np.inf, rng.uniform(0.0, 3.0, n))
    gap_b = np.where(rng.random(n) < 0.2, np.inf, rng.uniform(0.0, 3.0, n))
    e_a, e_b = rng.uniform(0.0, 4.0, n), rng.uniform(0.0, 4.0, n)
    conf_a = np.where(rng.random(n) < 0.3, 0.0, rng.uniform(0.1, 1.0, n))
    conf_b = np.where(rng.random(n) < 0.3, 0.0, rng.uniform(0.1, 1.0, n))
    ahead_e = np.where(conf_a > 0, e_a, battery)
    behind_e = np.where(conf_b > 0, e_b, battery)
    mode, attack, defend, hold, box = RS.decide_book(
        book, battery, line, wear, laps, race_laps, pit, gap_a, gap_b, ahead_e, behind_e, cfg
    )
    for k, driver in enumerate(ids):
        view = _view(
            driver_id=driver, laps_done=int(laps[k]), race_laps=race_laps,
            battery_mj=float(battery[k]), line_battery_mj=float(line[k]),
            tyre_wear=float(wear[k]), in_pit_lane=bool(pit[k]),
            gap_ahead_s=float(gap_a[k]), gap_behind_s=float(gap_b[k]),
            ahead=None if np.isinf(gap_a[k]) else RS.OpponentEstimate("X", e_a[k], conf_a[k]),
            behind=None if np.isinf(gap_b[k]) else RS.OpponentEstimate("Y", e_b[k], conf_b[k]),
        )  # fmt: skip
        plan = plans[driver]
        d = RS.decide(view, plan, DriverInstructions(), cfg)
        got = (RS.MODE_ORDER[mode[k]], attack[k], defend[k], hold[k], box[k])
        want = (
            d.instructions.mode, d.instructions.attack, d.instructions.defend,
            d.instructions.hold_position, d.box_for is not None,
        )  # fmt: skip
        assert got == want, (k, view, plan)
        assert book.harvesting[k] == plan.harvesting
        assert book.plan(driver) == replace(plan)


def test_battle_inputs_read_only_positions_gaps_and_radar() -> None:
    """Opponents' energy comes from the Radar arrays; nobody else's battery is an input."""
    s_m = np.array([100.0, 300.0, 200.0, 50.0])
    on_track = np.array([True, True, True, False])  # car 3 in the pit lane
    ahead_idx = np.array([2, -1, 1, -1])
    gap_m = np.array([100.0, np.inf, 100.0, np.inf])
    v = np.full(4, 50.0)
    index = np.array([0, 1, 2], dtype=np.int64)
    own = np.array([2.0, 3.0, 1.0])
    radar = np.array([0.5, 3.5, 1.5, 9.0])
    conf = np.array([1.0, 1.0, 0.0, 1.0])
    ga, gb, ahead_e, behind_e = RS.battle_inputs(
        index, s_m, on_track, ahead_idx, gap_m, v, own, radar, conf
    )
    np.testing.assert_allclose(ga, [2.0, np.inf, 2.0])
    # order by distance 0 < 2 < 1: car 1 has car 2 behind, car 2 has car 0,
    # car 0 (last) has car 1 behind it round the lap.
    np.testing.assert_allclose(gb, [np.inf, 2.0, 2.0])
    np.testing.assert_allclose(ahead_e, [2.0, 3.0, 3.5])  # car 0 chases car 2: no confidence
    np.testing.assert_allclose(behind_e, [3.5, 3.0, 0.5])  # car 2 behind car 1: no confidence
