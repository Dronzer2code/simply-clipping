"""SC-1: power equations, the 10 Hz stream and the CdA fit."""

from __future__ import annotations

import copy

import numpy as np
import pytest

from simply_clipping.loader import Config, const, load_config, segment_ids
from simply_clipping.physics import (
    FIELDS,
    CdaFit,
    Points,
    RunBuilder,
    Stream,
    aero_modes,
    electric_power_kw,
    resistance_w,
    wheel_power_kw,
)

CFG = load_config()


def _cfg_no_fuel() -> Config:
    cfg = copy.deepcopy(CFG)
    cfg["fuel"]["start_kg"] = 0.0
    return cfg


def test_constant_speed_gives_drag_and_rolling_only() -> None:
    v, m, cda = np.array([50.0, 80.0]), np.array([800.0, 800.0]), 0.7
    p = wheel_power_kw(v, np.zeros(2), m, cda, CFG)
    rho, crr, g = (const(CFG, k) for k in ("car.rho_kg_m3", "car.crr", "car.g_ms2"))
    expect = (0.5 * rho * cda * v**3 + crr * m * g * v) / 1e3
    np.testing.assert_allclose(p, expect)
    np.testing.assert_allclose(resistance_w(v, m, cda, CFG) / 1e3, expect)


def test_zero_speed_gives_zero_power() -> None:
    p = wheel_power_kw(np.zeros(3), np.array([0.0, 5.0, -5.0]), np.full(3, 800.0), 0.7, CFG)
    np.testing.assert_array_equal(p, 0.0)
    assert electric_power_kw(p, np.zeros(3), 400.0, CFG).tolist() == [0.0, 0.0, 0.0]


def _raw(rng: np.random.Generator, t_end: float) -> tuple[np.ndarray, ...]:
    """Return a 4 Hz feed with jitter and dropouts, speed noise 0.5 km/h."""
    t = np.cumsum(rng.uniform(0.22, 0.28, int(t_end * 4)))
    t = t[rng.random(t.size) > 0.05]
    v = 200.0 + 60.0 * np.sin(t / 7.0) + rng.normal(0.0, 0.5, t.size)
    return t, v, np.full(t.size, 100.0), np.zeros(t.size, dtype=bool), np.cumsum(v / 3.6 * 0.25)


def _fields_equal(a: Points, b: Points) -> bool:
    return all(np.array_equal(getattr(a, f), getattr(b, f)) for f in FIELDS)


def test_stream_is_chunk_invariant() -> None:
    """Pushing a race at once or in random chunks gives the same points, bit for bit."""
    rng = np.random.default_rng(42)
    t, v, thr, brk, prog = _raw(rng, 120.0)
    t = np.concatenate((t, t[-1] + 1.5 + t[:40]))  # a long gap, then more data
    v, thr = np.concatenate((v, v[:40])), np.concatenate((thr, thr[:40]))
    brk, prog = np.concatenate((brk, brk[:40])), np.concatenate((prog, prog[-1] + prog[:40]))
    whole = Stream(CFG)
    once = Points.concat([whole.push(t, v, thr, brk, prog), whole.flush()])
    chunked = Stream(CFG)
    cuts = np.sort(rng.choice(np.arange(1, t.size), 60, replace=False))
    parts = [chunked.push(t[a:b], v[a:b], thr[a:b], brk[a:b], prog[a:b])
             for a, b in zip(np.r_[0, cuts], np.r_[cuts, t.size], strict=True)]  # fmt: skip
    assert _fields_equal(once, Points.concat([*parts, chunked.flush()]))
    assert len(once) > 1000 and once.segment[-1] > once.segment[0]  # the gap split the stream


def test_stream_never_interpolates_across_a_long_gap() -> None:
    t = np.array([0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.8, 3.0, 3.25, 3.5, 3.75,
                  4.0, 4.25, 4.5])  # fmt: skip
    n = t.size
    stream = Stream(CFG)
    raw = (t, np.full(n, 180.0), np.full(n, 100.0), np.zeros(n, dtype=bool), t * 50.0)
    pts = Points.concat([stream.push(*raw), stream.flush()])
    assert not ((pts.t_s > 2.0 + 1e-9) & (pts.t_s < 2.8 - 1e-9)).any()
    assert segment_ids(t, const(CFG, "signal.max_gap_s")).tolist() == [0] * 9 + [1] * 8
    np.testing.assert_allclose(pts.v_ms, 50.0)
    np.testing.assert_allclose(pts.a_ms2, 0.0, atol=1e-9)


def _synthetic_runs(cda: dict[str, float], cfg: Config, rng: np.random.Generator) -> CdaFit:
    """Fit a car accelerating at full throttle with a different (partial) power on every run."""
    m = float(const(cfg, "car.mass_kg"))
    rho, crr, g = (const(cfg, k) for k in ("car.rho_kg_m3", "car.crr", "car.g_ms2"))
    v_start = {"straight": 232.0, "corner": 155.0}
    t_all, v_all, mode_all = [], [], []
    t0 = 0.0
    for _lap in range(30):
        for mode in aero_modes(cfg):
            p_w = rng.uniform(300e3, 420e3)  # any deploy level (lesson L-c)
            v, dt = v_start[mode] / 3.6, 0.01
            ts, vs = [], []
            for k in range(int(6.0 / dt)):
                ts.append(t0 + k * dt)
                vs.append(v)
                v += (p_w / v - 0.5 * rho * cda[mode] * v**2 - crr * m * g) / m * dt
            t_all.append(np.array(ts))
            v_all.append(np.array(vs))
            mode_all.append(np.full(len(ts), aero_modes(cfg).index(mode)))
            t0 = ts[-1] + 3.0  # off throttle in between (a long gap: separate runs)
    t_hi, v_hi, mode_hi = np.concatenate(t_all), np.concatenate(v_all), np.concatenate(mode_all)
    t = np.arange(0.0, t_hi[-1], 0.25) + rng.uniform(-0.03, 0.03, int(np.ceil(t_hi[-1] / 0.25)))
    t = t[(rng.random(t.size) > 0.05)]  # 4 Hz, jitter 30 ms, 5 % dropped, like the export
    near = np.clip(np.searchsorted(t_hi, t), 0, t_hi.size - 1)
    t = t[np.abs(t_hi[near] - t) < 0.02]  # only while a run is on
    near = np.clip(np.searchsorted(t_hi, t), 0, t_hi.size - 1)
    v_kmh = v_hi[near] * 3.6 + rng.normal(0.0, 0.5, t.size)
    n = t.size
    stream = Stream(cfg)
    raw = (t, v_kmh, np.full(n, 100.0), np.zeros(n, dtype=bool), np.cumsum(v_kmh / 3.6) * 0.25)
    pts = Points.concat([stream.push(*raw), stream.flush()])
    mode = mode_hi[np.searchsorted(t_hi, pts.t_s).clip(0, t_hi.size - 1)]
    fit, builder = CdaFit(cfg), RunBuilder(cfg)
    runs = builder.feed(pts, mode, np.full(len(pts), -1), np.full(len(pts), m))
    for run in runs + builder.close():
        fit.add(aero_modes(cfg)[run.mode], run.points.v_ms, run.points.a_ms2, run.m_kg, False)
    return fit


@pytest.mark.parametrize("cda", [{"straight": 0.70, "corner": 1.50},
                                 {"straight": 0.55, "corner": 1.20}])  # fmt: skip
def test_known_cda_is_recovered_within_5_percent(cda: dict[str, float]) -> None:
    cfg = _cfg_no_fuel()
    fit = _synthetic_runs(cda, cfg, np.random.default_rng(42))
    for mode, true in cda.items():
        got = fit.fitted(mode)
        assert got is not None, mode
        assert abs(got / true - 1.0) < 0.05, (mode, got, true)
