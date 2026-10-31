"""T-026 calibration deploy policy (owner round 10)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pytest

from pitwall_sim.calibration.compare import rule_set_for_date, simulate_quali_lap, track_arrays
from pitwall_sim.calibration.deploy_policy import (
    DeployPlan,
    PolicyResult,
    acceleration_zone_index,
    runs_empty_early,
    settle_deploy_anywhere,
    settle_plan,
    split_by_length,
    superclip_by_energy,
    superclip_mask,
)
from pitwall_sim.car.lap_sim import LapResult
from pitwall_sim.config.loader import load_app, load_team_performance, load_track, load_tyres
from pitwall_sim.track.builder import read_track_model
from tests.unit._zones_helper import zone_length_m

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"


@pytest.fixture(scope="module")
def suzuka():  # type: ignore[no-untyped-def]
    return load_track("suzuka", CONFIG_DIR), read_track_model(ROOT / "data/tracks/suzuka.parquet")


def test_zone_index_follows_the_acceleration_zones(suzuka) -> None:  # type: ignore[no-untyped-def]
    track, model = suzuka
    index, ids = acceleration_zone_index(track, model.s_m)

    assert ids == ("SM1", "SM2", "ST3")
    assert index[0] == index[-1] == 0  # SM1 crosses s = 0 and is one zone
    assert index[4500] == 1 and index[5200] == 2
    assert index[3000] == -1
    assert np.bincount(index[index >= 0]).tolist() == [
        zone_length_m(track, "SM1"),
        zone_length_m(track, "SM2"),
        zone_length_m(track, "ST3"),
    ]


def test_energy_is_split_by_zone_length() -> None:
    index = np.array([-1, 0, 0, 0, -1, 1, -1, 2, 2, 2, 2, 2, 2])
    budget = split_by_length(index, 3, 10.0)

    assert budget.tolist() == pytest.approx([3.0, 1.0, 6.0])
    assert split_by_length(np.array([-1, -1]), 0, 5.0).size == 0


def _lap(battery: np.ndarray, harvested_j: float, drawn: np.ndarray, v: float = 80.0) -> LapResult:
    n = battery.size
    return LapResult(
        s_m=np.arange(n, dtype=np.float64),
        v_ms=np.full(n, v),
        t_s=np.arange(n, dtype=np.float64) / v,
        battery_j=battery,
        lap_time_s=n / v,
        harvested_j=harvested_j,
        drawn_j=float(drawn.sum()),
        fuel_used_kg=0.0,
        battery_end_j=float(battery[-1]),
        zone_drawn_j=drawn,
    )


def test_runs_empty_early_only_before_the_last_zone() -> None:
    index = np.array([0, 0, -1, -1, 1, 1, -1])
    early = _lap(np.array([5e5, 0.0, 0.0, 1e5, 1e5, 0.0, 0.0]), 0.0, np.zeros(2))
    late = _lap(np.array([5e5, 4e5, 3e5, 2e5, 1e5, 0.0, 0.0]), 0.0, np.zeros(2))

    assert runs_empty_early(early, index)
    assert not runs_empty_early(late, index)


def test_superclip_covers_the_shortfall_at_each_zone_end() -> None:
    index = np.full(400, -1, dtype=np.int64)
    index[50:150] = 0
    index[250:350] = 1
    lap = _lap(np.zeros(400), 0.0, np.zeros(2), v=80.0)

    mask = superclip_mask(index, lap, shortfall_j=2 * 250e3, clip_power_w=250e3)

    # 0.25 MJ per zone at 250 kW = 1 s = 80 m at 80 m/s, at the end of each zone.
    assert mask[150 - 80 : 150].all() and not mask[: 150 - 80].any()
    assert mask[350 - 80 : 350].all() and mask.sum() == 160


def test_settle_iterates_the_harvest_and_adds_superclip_only_when_needed(suzuka) -> None:  # type: ignore[no-untyped-def]
    track, model = suzuka
    index, ids = acceleration_zone_index(track, model.s_m)
    n = model.s_m.size
    calls: list[DeployPlan] = []

    def fake(battery_low: bool):  # type: ignore[no-untyped-def]
        def run(plan: DeployPlan) -> LapResult:
            calls.append(plan)
            battery = np.full(n, 1e6)
            if battery_low and not plan.superclip.any():
                battery[3000] = 0.0  # empty before the last zone
            return _lap(battery, 3e6, plan.zone_budget_j * 0.9)

        return run

    ok = settle_plan(track, model.s_m, 4e6, 8e6, 250e3, fake(battery_low=False))
    assert isinstance(ok, PolicyResult) and not ok.used_superclip
    # Pass 1 plans with the 8 MJ harvest limit; pass 2 with the 3 MJ achieved.
    assert calls[0].zone_budget_j.sum() == pytest.approx(12e6)
    assert ok.plan.zone_budget_j.sum() == pytest.approx(7e6)
    assert ok.passes == 2

    calls.clear()
    low = settle_plan(track, model.s_m, 4e6, 8e6, 250e3, fake(battery_low=True))
    assert low.used_superclip and low.plan.superclip.any()
    assert not low.plan.superclip[index < 0].any()  # only inside acceleration zones
    assert ids == low.plan.zone_ids


def _quali(model, track, deploy: str = "policy"):  # type: ignore[no-untyped-def]
    return simulate_quali_lap(
        track_arrays(model, track),
        track,
        rule_set_for_date(date(2026, 3, 28), CONFIG_DIR),
        load_team_performance(CONFIG_DIR).teams["mercedes"],
        load_tyres(CONFIG_DIR),
        load_app(CONFIG_DIR),
        deploy,  # type: ignore[arg-type]
    )


def test_zones_policy_deploys_only_inside_acceleration_zones(suzuka) -> None:  # type: ignore[no-untyped-def]
    """T-026 policy, still available as ``--deploy zones``."""
    track, model = suzuka
    result = _quali(model, track, "zones")
    assert isinstance(result, PolicyResult)
    lap, plan = result.lap, result.plan
    index, _ = acceleration_zone_index(track, model.s_m)

    assert lap.zone_drawn_j is not None
    assert np.all(lap.zone_drawn_j <= plan.zone_budget_j + 1.0)
    falls = np.diff(lap.battery_j) < -1.0
    assert not falls[index[:-1] < 0].any()  # energy only leaves the battery inside zones


def test_superclip_by_energy_sizes_each_zone_and_reports_the_overflow() -> None:
    index = np.full(400, -1, dtype=np.int64)
    index[50:150] = 0  # 100 m
    index[250:300] = 1  # 50 m
    lap = _lap(np.zeros(400), 0.0, np.zeros(2), v=80.0)

    # 250 kW at 80 m/s: 0.25 MJ -> 80 m (fits); 0.25 MJ in a 50 m zone -> 30 m too long.
    mask, capped = superclip_by_energy(index, lap, np.array([250e3, 250e3]), 250e3)

    assert mask[70:150].all() and not mask[:70].any()
    assert mask[250:300].all()
    assert capped == pytest.approx(250e3 * 30 / 80)


def test_budget_mode_clips_every_zone(suzuka) -> None:  # type: ignore[no-untyped-def]
    track, model = suzuka
    index, _ = acceleration_zone_index(track, model.s_m)
    n = model.s_m.size

    def run(plan: DeployPlan) -> LapResult:  # braking harvests 3 MJ, clipping the rest
        return _lap(np.full(n, 1e6), 3e6 + 1e5 * plan.superclip.sum() / max(n, 1),
                    plan.zone_budget_j * 0.5)  # fmt: skip

    result = settle_plan(track, model.s_m, 4e6, 8e6, 250e3, run, superclip="budget")

    assert result.used_superclip
    for z in range(3):
        assert result.plan.superclip[index == z].any()  # every acceleration zone clips
    assert not result.plan.superclip[index < 0].any()
    assert result.plan.zone_budget_j.sum() == pytest.approx(12e6)  # battery + whole allowance


# --------------------------------------------------------------------------- #
# T-028 (owner decision (c)): deploy anywhere, super-clip the shortfall
# --------------------------------------------------------------------------- #


def _anywhere_lap(n: int, harvested_j: float, unmet_j: float, clip_j: float, t: float) -> LapResult:
    lap = _lap(np.full(n, 1e6), harvested_j + clip_j, np.zeros(1))
    return LapResult(**{**lap.__dict__, "lap_time_s": t, "superclip_j": clip_j,
                        "unmet_deploy_j": unmet_j})  # fmt: skip


def test_no_clip_when_the_lap_is_not_energy_limited(suzuka) -> None:  # type: ignore[no-untyped-def]
    track, model = suzuka
    n = model.s_m.size

    result = settle_deploy_anywhere(
        track, model.s_m, 8e6, 250e3, lambda plan: _anywhere_lap(n, 3e6, 0.0, 0.0, 90.0)
    )

    assert not result.used_superclip and result.passes == 1
    assert np.all(result.plan.deploy_zone == 0) and np.isinf(result.plan.zone_budget_j[0])


def test_clip_is_bounded_by_the_shortfall_and_picks_the_fastest_lap(suzuka) -> None:  # type: ignore[no-untyped-def]
    track, model = suzuka
    index, _ = acceleration_zone_index(track, model.s_m)
    n = model.s_m.size
    clip_m: list[int] = []

    def run(plan: DeployPlan) -> LapResult:
        metres = int(plan.superclip.sum())
        clip_m.append(metres)
        # Lap time is best around 300 m of clipping; the shortfall is 1 MJ.
        return _anywhere_lap(n, 3e6, 1e6, 0.0, 90.0 + ((metres - 300) / 1000.0) ** 2)

    result = settle_deploy_anywhere(track, model.s_m, 8e6, 250e3, run)

    assert result.used_superclip
    assert not result.plan.superclip[index < 0].any()  # only at acceleration-zone ends
    assert result.lap.lap_time_s == min(90.0 + ((m - 300) / 1000.0) ** 2 for m in clip_m)
    # Never more than the 1 MJ shortfall: 1 MJ / 250 kW = 4 s at 80 m/s = 320 m
    # in total (plus one rounding metre per zone).
    assert max(clip_m) <= 320 + 3


def test_real_lap_deploys_anywhere_and_clips_the_shortfall(suzuka) -> None:  # type: ignore[no-untyped-def]
    track, model = suzuka
    index, _ = acceleration_zone_index(track, model.s_m)
    policy = _quali(model, track, "policy")
    greedy = _quali(model, track, "greedy")
    assert isinstance(policy, PolicyResult) and isinstance(greedy, LapResult)
    lap = policy.lap

    assert lap.lap_time_s <= greedy.lap_time_s + 1e-9  # clipping is chosen only if it pays
    assert lap.harvested_j <= 8.0e6 + 1.0  # 2026_pre_miami qualifying limit
    assert lap.superclip_j <= greedy.unmet_deploy_j + 1.0
    assert not policy.plan.superclip[index < 0].any()
    falls = np.diff(lap.battery_j) < -1.0
    assert falls[index[:-1] < 0].any()  # deploys outside the acceleration zones too
