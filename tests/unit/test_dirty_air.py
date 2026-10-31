"""T-032: dirty air and slipstream.

Acceptance: a following car's corner speed is lower and its straight speed
higher than the same car alone. Coefficients come from config at test time.
"""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from pitwall_sim.calibration.compare import rule_set_for_date
from pitwall_sim.car.dirty_air import (
    dirty_air_params,
    downforce_scale,
    drag_scale,
    gaps_ahead_m,
    wake_factor,
)
from pitwall_sim.config.loader import load_app, load_team_performance, load_track, load_tyres
from pitwall_sim.config.models import Compound
from pitwall_sim.race import step_kernel as K
from pitwall_sim.track.builder import read_track_model

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
TEAM = "mercedes"
FUEL_KG = 40.0


@pytest.fixture(scope="module")
def world():  # type: ignore[no-untyped-def]
    app = load_app(CONFIG_DIR)
    track = load_track("suzuka", CONFIG_DIR)
    perf = load_team_performance(CONFIG_DIR)
    tyres = load_tyres(CONFIG_DIR)
    model = read_track_model(ROOT / "data" / "tracks" / "suzuka.parquet")
    rules = rule_set_for_date(date(2026, 3, 29), CONFIG_DIR)
    trk = K.kernel_track(model, track)
    glb = K.kernel_globals(rules, app, track, tyres, TEAM, perf)
    cars = K.kernel_cars([TEAM] * 2, [Compound.MEDIUM] * 2, rules, app, perf, tyres, 8.5)
    return app, trk, glb, cars


def _run(world, s_m: list[float], v_ms: float, throttle: float, steps: int) -> K.KernelState:  # type: ignore[no-untyped-def]
    """Cars at ``s_m`` with fixed controls for ``steps`` steps (no speed tracking)."""
    app, trk, glb, cars = world
    n = len(s_m)
    car = K.KernelCars(*(a[:n] for a in cars))
    st = K.initial_state(n, s_m, [v_ms] * n, [2e6] * n, [FUEL_KG] * n)
    ctl = K.default_controls(n)
    ctl.throttle[:] = throttle
    for _ in range(steps):
        K.step(app.sim.dt_s, trk, glb, car, ctl, st)
    return st


# --------------------------------------------------------------------------- #
# Acceptance
# --------------------------------------------------------------------------- #


def test_following_car_is_faster_on_the_straight(world) -> None:  # type: ignore[no-untyped-def]
    trk = world[1]
    start = 100.0  # Suzuka main straight after the line
    assert np.abs(trk.kappa[: int(400 / trk.ds_m)]).max() < 2e-3
    alone = _run(world, [start], 70.0, 1.0, 40)
    pair = _run(world, [start, start + 20.0], 70.0, 1.0, 40)
    assert pair.v_ms[0] > alone.v_ms[0]
    assert pair.gap_ahead_m[0] < world[0].dirty_air.range_m


def test_following_car_corner_speed_is_lower(world) -> None:  # type: ignore[no-untyped-def]
    app, trk, glb, cars = world
    # The tightest corner: a speed above every car's limit is capped to it.
    k = int(np.argmax(np.abs(trk.kappa)))
    s_apex = k * trk.ds_m
    alone = _run(world, [s_apex - 2.0], 60.0, 0.0, 1)
    pair = _run(world, [s_apex - 2.0, s_apex + 8.0], 60.0, 0.0, 1)
    assert alone.v_ms[0] < 60.0  # capped at the corner speed
    assert pair.v_ms[0] < alone.v_ms[0]


def test_lone_car_is_unaffected(world) -> None:  # type: ignore[no-untyped-def]
    far = _run(world, [100.0, 100.0 + world[0].dirty_air.range_m + 50.0], 70.0, 1.0, 10)
    alone = _run(world, [100.0], 70.0, 1.0, 10)
    assert far.v_ms[0] == pytest.approx(alone.v_ms[0])
    assert math.isinf(alone.gap_ahead_m[0])


# --------------------------------------------------------------------------- #
# Formula and gaps
# --------------------------------------------------------------------------- #


def test_wake_factor_and_scales_follow_the_trd_formula(world) -> None:  # type: ignore[no-untyped-def]
    p = dirty_air_params(world[0])
    assert wake_factor(0.0, p.range_m) == 1.0
    assert wake_factor(p.range_m / 2, p.range_m) == pytest.approx(0.5)
    assert wake_factor(p.range_m, p.range_m) == 0.0
    assert wake_factor(math.inf, p.range_m) == 0.0
    f = 0.4
    assert downforce_scale(f, p.downforce_loss_max) == pytest.approx(1 - p.downforce_loss_max * f)
    assert drag_scale(f, p.drag_reduction_max) == pytest.approx(1 - p.drag_reduction_max * f)


def test_gaps_wrap_round_the_lap_and_skip_stopped_cars() -> None:
    s = np.array([10.0, 990.0, 500.0])
    running = np.array([True, True, True])
    out = np.empty(3)
    idx = np.empty(3, dtype=np.int64)
    in_pit = np.zeros(3, dtype=bool)
    gaps_ahead_m(s, running, in_pit, 1000.0, out, idx)
    assert out.tolist() == pytest.approx([490.0, 20.0, 490.0])
    assert idx.tolist() == [2, 0, 1]
    running[0] = False
    gaps_ahead_m(s, running, in_pit, 1000.0, out, idx)
    assert math.isinf(out[0]) and idx[0] == -1
    assert out[1] == pytest.approx(510.0) and idx[1] == 2
    running[0], in_pit[2] = True, True  # a pit-lane car is invisible to the track
    gaps_ahead_m(s, running, in_pit, 1000.0, out, idx)
    assert math.isinf(out[2]) and idx[1] == 0 and out[1] == pytest.approx(20.0)
