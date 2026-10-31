"""SC-3: each alert fires in a constructed case and not otherwise; live = offline."""

from __future__ import annotations

import re
from types import SimpleNamespace

import numpy as np
import pytest

from simply_clipping.alerts import AlertRow, Engine, OwnTrack, offline_alerts, radio_line
from simply_clipping.battles import History
from simply_clipping.energy import CLIP, CRUISE, LIFT, CarTracker, Estimates, calibrated
from simply_clipping.live import Provider
from simply_clipping.loader import load_config
from simply_clipping.tests.test_energy import LAP_M, TRACK, drive

CFG = load_config()
V = 80.0  # m/s
ZONE = TRACK.zones[0]


def _hist(
    progress0: float,
    energy: float,
    conf: float,
    state: int = CRUISE,
    v: float = V,
    t1: float = 200.0,
    states: dict[tuple[float, float], int] | None = None,
) -> History:
    """Return a rival at constant speed from t = 0 to t1 (10 Hz); states set on progress ranges."""
    t = np.arange(0.0, t1, 0.1)
    prog = progress0 + v * t
    st = np.full(t.size, state, dtype=np.int8)
    for (a, b), s in (states or {}).items():
        st[(prog >= a) & (prog < b)] = s
    n = t.size
    est = Estimates(
        t,
        np.full(n, energy),
        st,
        np.full(n, conf),
        t,
        np.zeros(n),
        np.full(n, v),
        prog,
        np.full(n, 100.0),
        np.zeros(n, dtype=bool),
    )
    hist = History()
    hist.append(est, np.full(n, conf))
    return hist


def _own(
    progress0: float,
    battery: float,
    t1: float = 200.0,
    v: float = V,
    drain_kw: float = 0.0,
    throttle: float = 100.0,
) -> OwnTrack:
    own = OwnTrack(CFG, LAP_M)
    for t in np.arange(0.0, t1, 0.1):
        p = progress0 + v * t
        own.add(
            float(t),
            int(p // LAP_M) + 1,
            float(p % LAP_M),
            v,
            battery - drain_kw * t / 1e3,
            throttle,
            False,
        )
    return own


def _fire(own: OwnTrack, cars: dict[str, History], t: float) -> list[AlertRow]:
    engine = Engine("US", TRACK, CFG)
    out: list[AlertRow] = []
    for tick in np.arange(0.0, t + 1e-9, 0.5):
        us = own.at(float(tick))
        assert us is not None
        out += engine.evaluate(us, cars)
    return out


def _kinds(rows: list[AlertRow]) -> set[tuple[str, str, str]]:
    return {(r.type, r.car_b, r.branch) for r in rows}


# Our Car on the straight (s = 1100 m) at t = 100 s: progress = LAP_M + 1100.
P_US = LAP_M + 1100.0 - V * 100.0


@pytest.mark.parametrize(
    ("energy", "conf", "gap_m", "fires"),
    [
        (1.0, 0.8, 40.0, True),
        (1.0, 0.3, 40.0, False),
        (2.5, 0.8, 40.0, False),
        (1.0, 0.8, 120.0, False),
    ],
)
def test_attack_energy(energy: float, conf: float, gap_m: float, fires: bool) -> None:
    rows = _fire(_own(P_US, 3.0), {"AAA": _hist(P_US + gap_m, energy, conf)}, 100.0)
    assert (("ATTACK", "AAA", "energy") in _kinds(rows)) == fires


@pytest.mark.parametrize(("clip", "fires"), [(True, True), (False, False)])
def test_attack_observed_clip(clip: bool, fires: bool) -> None:
    """The rival clipped on this straight last lap (energy equal: only branch b can fire)."""
    last_lap = (ZONE.s_start_m + 200.0, ZONE.s_start_m + 500.0)  # 300 m = 3.75 s of CLIP
    hist = _hist(P_US + 40.0, 3.0, 0.8, states={last_lap: CLIP} if clip else None)
    rows = _fire(_own(P_US, 3.0), {"AAA": hist}, 100.0)
    assert (("ATTACK", "AAA", "observed clip") in _kinds(rows)) == fires


@pytest.mark.parametrize(
    ("energy", "gap_m", "fires"), [(3.5, -30.0, True), (3.5, -60.0, False), (2.5, -30.0, False)]
)
def test_defend_energy(energy: float, gap_m: float, fires: bool) -> None:
    rows = _fire(_own(P_US, 2.0), {"BBB": _hist(P_US + gap_m, energy, 0.8)}, 100.0)
    assert (("DEFEND", "BBB", "energy") in _kinds(rows)) == fires


@pytest.mark.parametrize(
    ("rival_clipped", "gap_m", "fires"),
    [(False, -30.0, True), (True, -30.0, False), (False, -60.0, False)],
)
def test_defend_own_battery(rival_clipped: bool, gap_m: float, fires: bool) -> None:
    """Our battery is short for the straight and the car behind was not seen clipping."""
    ours = 0.5
    every_lap = {
        (k * LAP_M + ZONE.s_start_m + 200.0, k * LAP_M + ZONE.s_start_m + 500.0): CLIP
        for k in range(-3, 4)
    }
    hist = _hist(P_US + gap_m, ours, 0.8, states=every_lap if rival_clipped else None)
    rows = _fire(_own(P_US, ours), {"BBB": hist}, 100.0)
    assert (("DEFEND", "BBB", "own battery") in _kinds(rows)) == fires


@pytest.mark.parametrize(("ours", "fires"), [(0.8, True), (1.5, False)])
def test_repass_risk(ours: float, fires: bool) -> None:
    """We pass a slower car (on the straight before the 1200 m one) with a low battery."""
    p0 = LAP_M + 600.0 - V * 100.0  # we reach s = 600 m at t = 100 s
    rival = _hist(p0 + 0.5 * 98.0 * 2, 3.0, 0.8, v=V - 1.0)  # we pass it at ~t = 98 s
    rows = _fire(_own(p0, ours), {"CCC": rival}, 100.0)
    assert (("REPASS_RISK", "CCC", "repass") in _kinds(rows)) == fires


def test_closing_speed_once_per_episode_biggest_rival() -> None:
    """Two slow LIFTing cars ahead of us on the straight while we deploy: one alert."""
    p0 = P_US + 200.0  # we are at s = 1300 m (on the straight) at t = 100 s
    own = _own(p0, 3.0, drain_kw=300.0)
    # both come within 200 m at t = 97 s; SLOWER closes faster (90 vs 72 km/h)
    cars = {
        "SLOW": _hist(p0 + 140.0 + V * 100.0 - 60.0 * 100.0, 3.0, 0.8, LIFT, v=60.0),
        "SLOWER": _hist(p0 + 125.0 + V * 100.0 - 55.0 * 100.0, 3.0, 0.8, LIFT, v=55.0),
    }
    rows = [r for r in _fire(own, cars, 103.0) if r.type == "CLOSING_SPEED_RISK"]
    assert [(r.car_b, r.time_s) for r in rows] == [("SLOWER", 97.0)]


def test_no_closing_alert_below_the_threshold() -> None:
    p0 = P_US + 200.0
    own = _own(p0, 3.0, drain_kw=300.0)
    cars = {"NEAR": _hist(p0 + 150.0 + V * 100.0 - 72.0 * 100.0, 3.0, 0.8, LIFT, v=72.0)}
    assert not [r for r in _fire(own, cars, 103.0) if r.type == "CLOSING_SPEED_RISK"]


def test_same_pair_and_type_suppressed_for_a_lap() -> None:
    rows = _fire(_own(P_US, 3.0), {"AAA": _hist(P_US + 40.0, 1.0, 0.8)}, 100.0)
    attacks = [r.time_s for r in rows if r.type == "ATTACK"]
    assert attacks == [0.0, 37.5, 75.0]  # 100 s together = 2.7 laps: once per lap (37.5 s)


def test_live_and_offline_give_the_same_alerts() -> None:
    """The same race through the bench path (one push) and the pit wall (frame by frame)."""
    rng = np.random.default_rng(5)
    run = drive(["deploy"] * 6, e_start=4.0)
    lag = 0.4  # Our Car follows the rival's line 0.4 s behind, with a full battery
    idx = np.unique(
        np.clip(
            np.arange(0, run["t"].size, 25) + rng.integers(-3, 4, run["t"][::25].size),
            0,
            run["t"].size - 1,
        )
    )
    t, v_kmh = run["t"][idx], run["v"][idx] * 3.6
    thr, brk, prog = np.round(run["thr"][idx]), run["brk"][idx] > 0.5, run["p"][idx]
    tracker = CarTracker("AAA", "", TRACK, CFG)
    est = Estimates.concat([tracker.push(t, v_kmh, thr, brk, prog), tracker.flush()])
    hist = History()
    hist.append(est, calibrated(est.raw_confidence, CFG))
    own = OwnTrack(CFG, LAP_M)
    view_t = np.arange(1.0, run["t"][-1], 0.1)
    our_p = np.interp(view_t - lag, run["t"], run["p"])
    our_v = np.interp(view_t - lag, run["t"], run["v"])
    for tv, p, v in zip(view_t, our_p, our_v, strict=True):
        own.add(float(tv), int(p // LAP_M) + 1, float(p % LAP_M), float(v), 3.9, 100.0, False)
    offline = offline_alerts({"AAA": hist}, own, "US", TRACK, CFG)
    provider = Provider(None, TRACK, CFG)
    seen: dict[str, tuple[float, str, str, str]] = {}
    for tv, p, v in zip(view_t, our_p, our_v, strict=True):
        k = int(np.searchsorted(t, tv, side="right"))
        frames = [
            SimpleNamespace(
                t_s=float(t[i]),
                speed_kmh=float(v_kmh[i]),
                throttle_pct=float(thr[i]),
                brake=bool(brk[i]),
                distance_m=float(prog[i] % LAP_M),
            )
            for i in range(max(0, k - 480), k)
        ]
        our_car = SimpleNamespace(
            driver_id="US",
            lap=int(p // LAP_M) + 1,
            s_m=float(p % LAP_M),
            v_ms=float(v),
            battery_mj=3.9,
            throttle=1.0,
            brake=0.0,
        )
        for a in provider.update(
            SimpleNamespace(t_s=float(tv), our_car=our_car, rival_feed={"AAA": frames})
        ):
            seen[a.alert_id] = (a.created_t, a.type, a.rival, a.evidence.branch or "")
    horizon = view_t[-1] - 3.0
    live = sorted(v for v in seen.values() if v[0] <= horizon)
    off = sorted((r.time_s, r.type, r.car_b, r.branch) for r in offline if r.time_s <= horizon)
    assert off, "the race should raise alerts"
    assert live == off


@pytest.mark.parametrize("corner", ["T1", None])
@pytest.mark.parametrize(("kind", "branch"), [
    ("ATTACK", "energy"), ("ATTACK", "observed clip"), ("DEFEND", "energy"),
    ("DEFEND", "own battery"), ("REPASS_RISK", "repass"), ("CLOSING_SPEED_RISK", "closing"),
])  # fmt: skip
def test_radio_line_is_short_and_states_only_evidence(kind: str, branch: str,
                                                       corner: str | None) -> None:  # fmt: skip
    """SC-6: one line, at most 12 words, every number from the alert's evidence."""
    row = AlertRow(100.0, 3, kind, "US", "VER", 0.8, branch, corner, 2.94, 1.23, -45.6, 0.4,
                   "CLIP", None, 0.9, 3.81)  # fmt: skip
    line = radio_line(row)
    assert "\n" not in line and len(line.split()) <= int(CFG["alerts"]["radio_max_words"]), line
    allowed = {"2.9", "1.2", "46", "3.8"}
    assert set(re.findall(r"\d+\.\d|\d{2,}", line)) <= allowed, line


def test_alerts_carry_their_radio_line() -> None:
    rows = _fire(_own(P_US, 3.0), {"AAA": _hist(P_US + 40.0, 1.0, 0.8)}, 10.0)
    assert rows and all(r.radio == radio_line(r) and r.radio for r in rows)
