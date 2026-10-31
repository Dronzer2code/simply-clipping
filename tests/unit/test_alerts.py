"""Sprint A-1 / A-5: simply_clipping_lite alerts fire when, and only when, their rule holds."""

from __future__ import annotations

import inspect
import sys
import textwrap
from dataclasses import replace
from pathlib import Path

import pytest

from pitwall_sim.config.loader import load_app, load_rule_set, load_track
from pitwall_sim.config.models import AlertsConfig, Compound
from pitwall_sim.observe import alerts as A
from pitwall_sim.observe.engineer_view import EngineerView, PublicWeather
from pitwall_sim.observe.frames import PublicFeedFrame
from pitwall_sim.observe.radar.energy import RadarEstimate
from pitwall_sim.race.state import CarState, TimingState

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
L = 5807.0
ME, RIVAL = "VER", "NOR"
# Suzuka straights (suzuka.yaml): SM1 5716 -> 611 (702 m), SM2 4082 -> 4902 (820 m),
# ST3 5095 -> 5316 (221 m).


@pytest.fixture
def cfg() -> AlertsConfig:
    # The rule tests look at one view at a time: no hysteresis here (tested below).
    return load_app(CONFIG_DIR).alerts.model_copy(update={"hold_s": 0.0})


@pytest.fixture
def provider(cfg: AlertsConfig) -> A.SimplyClippingLite:
    return A.SimplyClippingLite.for_track(cfg, load_track("suzuka", CONFIG_DIR))


def _car(
    s_m: float = 4300.0, lap: int = 5, battery_mj: float = 3.0, v_kmh: float = 280.0,
    throttle: float = 1.0, brake: float = 0.0, status: str = "RUNNING",
) -> CarState:  # fmt: skip
    return CarState(
        driver_id=ME, team_id="red_bull", s_m=s_m, lap=lap, line=0, v_ms=v_kmh / 3.6,
        throttle=throttle, brake=brake, gear=8, aero_mode="STRAIGHT_MODE",
        battery_mj=battery_mj, harvest_mj_lap=0.0, deploy_mj_lap=0.0,
        overtake_available=False, overtake_active=False, energy_mode="BALANCED",
        compound=Compound.MEDIUM, tyre_age_laps=5, tyre_wear=0.2, tyre_temp_c=100.0,
        fuel_kg=60.0, damage=0.0, status=status, penalties_s=0.0,  # type: ignore[arg-type]
        track_limit_warnings=0,
    )  # fmt: skip


def _view(
    t: float = 500.0, me: CarState | None = None, order: tuple[str, ...] = (RIVAL, ME),
    interval: dict[str, float] | None = None, rival_mj: float = 3.0, conf: float = 0.8,
    state: str = "DEPLOY", rival_d: float | None = None, rival_kmh: float = 280.0,
    frame_age_s: float = 0.0, last_lap_s: float = 95.0,
    history: list[PublicFeedFrame] | None = None, prior: bool = False,
) -> EngineerView:  # fmt: skip
    me = me or _car()
    rival_d = me.s_m + 50.0 if rival_d is None else rival_d
    frame = PublicFeedFrame(t - frame_age_s, RIVAL, rival_kmh, 100.0, False, 8, 0.0, 0.0,
                            rival_d % L)  # fmt: skip
    timing = TimingState(
        order=list(order),
        interval_s=interval or {RIVAL: 0.0, ME: 0.5},
        last_lap_s=dict.fromkeys(order, last_lap_s),
    )
    return EngineerView(
        t_s=t, our_car=me, timing=timing, rival_feed={RIVAL: [*(history or []), frame]},
        radar={RIVAL: RadarEstimate(t, RIVAL, rival_mj, state, conf, None, prior)},  # type: ignore[arg-type]
        flag="GREEN", weather_public=PublicWeather(), radio_log=[], predictor=None,
    )  # fmt: skip


def _types(alerts: list[A.Alert]) -> set[tuple[str, str]]:
    return {(a.type, a.rival) for a in alerts}


def _pass(t0: float, start_m: float, end_m: float, kmh: float, drop_every: int = 0) -> list:  # type: ignore[type-arg]
    """Return 4 Hz feed frames of the rival from ``start_m`` to ``end_m``.

    Every ``drop_every``-th frame is missing.
    """
    frames, k, d = [], 0, start_m
    while d <= end_m:
        if not (drop_every and k % drop_every == 0):
            frames.append(PublicFeedFrame(t0 + 0.25 * k, RIVAL, kmh, 100.0, False, 8, 0.0, 0.0,
                                          d % L))  # fmt: skip
        k += 1
        d = start_m + kmh / 3.6 * 0.25 * k
    return frames


# --------------------------------------------------------------------------- #
# ATTACK
# --------------------------------------------------------------------------- #


def test_attack_fires_on_a_low_rival_ahead(provider: A.SimplyClippingLite) -> None:
    alerts = provider.update(_view(rival_mj=2.0))  # we have 3.0: 1.0 MJ more
    assert _types(alerts) == {("ATTACK", RIVAL)}
    a = alerts[0]
    assert a.confidence == 0.8 and a.evidence.our_mj == 3.0 and a.evidence.rival_mj == 2.0
    assert a.evidence.gap_s == 0.5 and a.lap == 6 and a.corner_id == "T15"
    assert a.expires_t == a.created_t + provider.cfg.expiry_s


@pytest.mark.parametrize(
    "case",
    [
        {"rival_mj": 2.5},  # only 0.5 MJ lower
        {"interval": {RIVAL: 0.0, ME: 1.5}},  # too far ahead
        {"rival_mj": 2.0, "conf": 0.0},  # no Radar fit yet
        {"rival_mj": 2.0, "order": (ME, RIVAL), "interval": {ME: 0.0, RIVAL: 3.0}},  # behind us
    ],
)
def test_attack_stays_silent_otherwise(provider: A.SimplyClippingLite, case: dict) -> None:  # type: ignore[type-arg]
    assert not any(a.type == "ATTACK" for a in provider.update(_view(**case)))


def _clip_case(cfg: AlertsConfig, state: str = "CLIP", later_s: float = 90.0,
               drop_every: int = 0, conf: float = 0.0) -> list[A.Alert]:  # fmt: skip
    """Return the alerts ``later_s`` after the rival drove SM2 around t = 400 s.

    It was seen ``state`` on SM2 (4082 -> 4902); now we are 0.5 s behind it
    before SM2. Energies level and the Radar has no energy confidence: only the
    observed clip can fire.
    """
    t_clip = 400.0
    provider = A.SimplyClippingLite.for_track(
        cfg, load_track("suzuka", CONFIG_DIR), feed_rate_hz=4.0
    )
    lap = _pass(t_clip - 5.0, 4082.0, 4902.0, 280.0, drop_every)
    far = {"interval": {RIVAL: 0, ME: 3.0}}
    for k in range(7):  # 1.5 s of ``state`` mid-SM2, then DEPLOY
        t_k = t_clip - 1.5 + 0.25 * k
        seen = [f for f in lap if f.t_s < t_k]
        provider.update(_view(t=t_k, state=state if k < 7 - 1 else "DEPLOY",
                              rival_d=4500.0 + 20.0 * k, history=seen, **far))  # type: ignore[arg-type]  # fmt: skip
    return provider.update(_view(t=t_clip + later_s, me=_car(s_m=3950.0), rival_mj=2.9,
                                 conf=conf, history=lap))  # fmt: skip


def test_attack_fires_when_the_rival_clipped_on_the_coming_straight_last_lap(
    cfg: AlertsConfig,
) -> None:
    alerts = _clip_case(cfg)
    assert _types(alerts) == {("ATTACK", RIVAL)}
    a = alerts[0]
    assert a.evidence.branch == "observed clip" and a.evidence.rival_mj is None  # no estimate
    assert a.confidence == a.evidence.detection_share >= cfg.detection_min_share
    assert not _clip_case(cfg, state="DEPLOY")  # never seen clipping
    blip = A.SimplyClippingLite.for_track(cfg, load_track("suzuka", CONFIG_DIR), None, 4.0)
    for k, state in enumerate(("DEPLOY", "CLIP", "DEPLOY")):  # one CLIP sample: not a clip
        blip.update(_view(t=400.0 + 0.25 * k, state=state, rival_d=4600.0,
                          interval={RIVAL: 0, ME: 3.0}))  # fmt: skip
    assert not blip._clips
    assert not _clip_case(cfg, later_s=2 * 95.0)  # a clip two laps ago does not count


def test_observed_clip_is_gated_by_detection_not_energy_confidence(cfg: AlertsConfig) -> None:
    every_4th_lost = _clip_case(cfg, drop_every=4)  # 75 % of the samples arrived
    assert _types(every_4th_lost) == {("ATTACK", RIVAL)}
    assert every_4th_lost[0].confidence == pytest.approx(0.75, abs=0.05)
    assert not _clip_case(cfg, drop_every=2)  # half the samples lost: below 0.7
    assert not _clip_case(cfg, drop_every=2, conf=0.9)  # a confident Radar does not lift it
    assert not _clip_case(cfg, drop_every=1)  # every frame of that pass gone from the feed
    # Only a later pass of SM2 is still in the feed window: the clipped one is not seen.
    provider = A.SimplyClippingLite.for_track(cfg, load_track("suzuka", CONFIG_DIR), None, 4.0)
    for k, state in enumerate(("CLIP",) * 6 + ("DEPLOY",)):
        provider.update(_view(t=400.0 + 0.25 * k, state=state, rival_d=4600.0 + 20.0 * k,
                              interval={RIVAL: 0, ME: 3.0}))  # fmt: skip
    later = _pass(460.0, 4082.0, 4902.0, 280.0)
    assert not provider.update(_view(t=490.0, me=_car(s_m=3950.0), rival_mj=2.9, conf=0.0,
                                     history=later))  # fmt: skip


def test_attack_evidence_names_the_energy_branch_and_the_prior(
    provider: A.SimplyClippingLite,
) -> None:
    alerts = provider.update(_view(rival_mj=2.0, prior=True))
    assert alerts[0].evidence.branch == "energy"
    assert alerts[0].evidence.rival_basis == "assumed full at start"


# --------------------------------------------------------------------------- #
# DEFEND
# --------------------------------------------------------------------------- #

BEHIND = {"order": (ME, RIVAL), "interval": {ME: 0.0, RIVAL: 0.4}}


def test_defend_fires_on_a_charged_rival_close_behind(provider: A.SimplyClippingLite) -> None:
    alerts = provider.update(_view(**BEHIND, rival_mj=3.9))  # type: ignore[arg-type]
    assert _types(alerts) == {("DEFEND", RIVAL)}
    assert alerts[0].evidence.gap_s == -0.4


@pytest.mark.parametrize(
    "case",
    [
        {**BEHIND, "rival_mj": 3.5},  # only 0.5 MJ more
        {"order": (ME, RIVAL), "interval": {ME: 0.0, RIVAL: 0.8}, "rival_mj": 3.9},  # > 0.6 s
        {**BEHIND, "rival_mj": 3.9, "conf": 0.0},
    ],
)
def test_defend_stays_silent_otherwise(provider: A.SimplyClippingLite, case: dict) -> None:  # type: ignore[type-arg]
    assert not any(a.type == "DEFEND" for a in provider.update(_view(**case)))


def _own_battery(cfg: AlertsConfig, battery_mj: float, clipped: bool = False,
                 gap_s: float = 0.4, power: bool = True) -> list[A.Alert]:  # fmt: skip
    """Return the alerts as we approach SM2 with a car ``gap_s`` behind.

    We drove SM2 (820 m) in 10 s; a lap later we come back with ``battery_mj``;
    the car behind's estimate is level with ours.
    """
    rules = load_rule_set("2026_post_miami", CONFIG_DIR).power if power else None
    provider = A.SimplyClippingLite.for_track(cfg, load_track("suzuka", CONFIG_DIR), rules)
    far = {"order": (ME, RIVAL), "interval": {ME: 0.0, RIVAL: 3.0}, "rival_d": 100.0}
    for k, s in enumerate(range(4090, 4905, 20)):  # through SM2 in 10 s, 4 Hz
        provider.update(_view(t=300.0 + 0.25 * k, me=_car(s_m=float(s)), **far))  # type: ignore[arg-type]
    provider.update(_view(t=320.0, me=_car(s_m=5000.0), **far))  # type: ignore[arg-type]
    if clipped:  # the car behind seen clipping on SM1 since (1.5 s)
        for k, state in enumerate(("CLIP",) * 7 + ("DEPLOY",)):
            provider.update(_view(t=330.0 + 0.25 * k, me=_car(s_m=5000.0 + 20.0 * k),
                                  state=state, **{**far, "rival_d": 100.0 + 20.0 * k}))  # type: ignore[arg-type]  # fmt: skip
    behind = {"order": (ME, RIVAL), "interval": {ME: 0.0, RIVAL: gap_s}}
    return provider.update(
        _view(
            t=400.0,
            me=_car(s_m=3950.0, battery_mj=battery_mj),
            rival_mj=battery_mj,
            conf=0.0,
            **behind,
        )
    )  # type: ignore[arg-type]


def test_defend_fires_when_our_battery_cannot_cover_the_straight(cfg: AlertsConfig) -> None:
    caps = load_rule_set("2026_post_miami", CONFIG_DIR).power.zone_caps_kw
    alerts = _own_battery(cfg, battery_mj=1.0)
    assert _types(alerts) == {("DEFEND", RIVAL)}
    ev = alerts[0].evidence
    assert ev.branch == "own battery" and alerts[0].confidence == 1.0
    # SM2 timed at ~9.75 s; the need sits between the "other" and acceleration-zone caps.
    assert 9.0 * float(caps.other) / 1e3 <= ev.need_mj <= 10.5 * float(caps.acceleration_zone) / 1e3  # type: ignore[arg-type, operator]
    enough = ev.need_mj + cfg.battery_reserve_mj + 0.1  # type: ignore[operator]
    assert not _own_battery(cfg, battery_mj=enough)  # enough for the whole straight
    assert _own_battery(cfg, battery_mj=enough - 0.2)
    assert not _own_battery(cfg, battery_mj=1.0, clipped=True)  # it is low too
    assert not _own_battery(cfg, battery_mj=1.0, gap_s=0.8)  # not close enough
    assert not _own_battery(cfg, battery_mj=1.0, power=False)  # no Rule Set caps given


# --------------------------------------------------------------------------- #
# RE-PASS RISK
# --------------------------------------------------------------------------- #


def _repass(provider: A.SimplyClippingLite, battery_mj: float, dt: float, s_m: float) -> set:  # type: ignore[type-arg]
    far = {RIVAL: 0.0, ME: 3.0}
    provider.update(_view(t=1000.0, me=_car(s_m=s_m, battery_mj=battery_mj), interval=far,
                          rival_d=s_m + 40.0))  # fmt: skip
    passed = _view(t=1000.0 + dt, me=_car(s_m=s_m + 20.0, battery_mj=battery_mj),
                   order=(ME, RIVAL), interval={ME: 0.0, RIVAL: 3.0}, rival_d=s_m)  # fmt: skip
    if dt > 1.0:  # the pass itself happened at t + 1 s
        provider.update(replace(passed, t_s=1001.0))
    return _types(provider.update(passed))


def test_repass_risk_fires_after_a_pass_on_low_battery(cfg: AlertsConfig) -> None:
    track = load_track("suzuka", CONFIG_DIR)

    def fresh() -> A.SimplyClippingLite:
        return A.SimplyClippingLite.for_track(cfg, track)

    assert ("REPASS_RISK", RIVAL) in _repass(fresh(), 0.8, 1.0, 3950.0)  # SM2 (820 m) ahead
    assert ("REPASS_RISK", RIVAL) not in _repass(fresh(), 1.5, 1.0, 3950.0)  # battery fine
    assert ("REPASS_RISK", RIVAL) not in _repass(fresh(), 0.8, 20.0, 3950.0)  # pass too old
    assert ("REPASS_RISK", RIVAL) not in _repass(fresh(), 0.8, 1.0, 5000.0)  # ST3: 221 m


# --------------------------------------------------------------------------- #
# CLOSING-SPEED RISK
# --------------------------------------------------------------------------- #

ON_SM2 = {"me": _car(s_m=4300.0, battery_mj=2.0), "interval": {RIVAL: 0.0, ME: 3.0}}


def test_closing_speed_fires_on_a_clipping_car_ahead(provider: A.SimplyClippingLite) -> None:
    alerts = provider.update(_view(**ON_SM2, state="CLIP", rival_d=4400.0, rival_kmh=230.0))  # type: ignore[arg-type]
    assert _types(alerts) == {("CLOSING_SPEED_RISK", RIVAL)}
    assert alerts[0].evidence.dv_kmh == pytest.approx(50.0)


@pytest.mark.parametrize(
    "case",
    [
        {**ON_SM2, "state": "CLIP", "rival_d": 4400.0, "rival_kmh": 250.0},  # dv only 30
        {**ON_SM2, "state": "CLIP", "rival_d": 4600.0, "rival_kmh": 230.0},  # 300 m away
        {**ON_SM2, "state": "DEPLOY", "rival_d": 4400.0, "rival_kmh": 230.0},  # nobody clips
        {**ON_SM2, "state": "CLIP", "rival_d": 4400.0, "rival_kmh": 230.0, "conf": 0.0},
        {**ON_SM2, "state": "CLIP", "rival_d": 4400.0, "rival_kmh": 230.0, "frame_age_s": 3.0},
        # the rival lifts 60 m before the end of SM2: braking for 130R, not clipping
        {"me": _car(s_m=4740.0, battery_mj=2.0), "interval": {RIVAL: 0.0, ME: 3.0},
         "state": "LIFT", "rival_d": 4840.0, "rival_kmh": 230.0},
        {"me": _car(s_m=4300.0, battery_mj=2.0, status="PIT"), "interval": {RIVAL: 0.0, ME: 3.0},
         "state": "CLIP", "rival_d": 4400.0, "rival_kmh": 230.0},
    ],
)  # fmt: skip
def test_closing_speed_stays_silent_otherwise(provider: A.SimplyClippingLite, case: dict) -> None:  # type: ignore[type-arg]
    assert not any(a.type == "CLOSING_SPEED_RISK" for a in provider.update(_view(**case)))


def test_closing_speed_when_we_lift_and_the_car_behind_deploys(
    provider: A.SimplyClippingLite,
) -> None:
    me = _car(s_m=4300.0, battery_mj=2.0, v_kmh=230.0, throttle=0.0)  # we LIFT on SM2
    view = _view(me=me, order=(ME, RIVAL), interval={ME: 0.0, RIVAL: 0.3}, state="DEPLOY",
                 rival_d=4200.0, rival_kmh=285.0)  # fmt: skip
    assert ("CLOSING_SPEED_RISK", RIVAL) in _types(provider.update(view))


# --------------------------------------------------------------------------- #
# Lifetime: clears, expires, suppressed for a lap
# --------------------------------------------------------------------------- #


def test_alert_clears_expires_and_is_suppressed_for_a_lap(provider: A.SimplyClippingLite) -> None:
    low = {"rival_mj": 2.0}
    first = provider.update(_view(t=500.0, **low))
    assert len(first) == 1
    assert provider.update(_view(t=503.0, **low))[0].alert_id == first[0].alert_id  # same alert
    assert not provider.update(_view(t=504.0, rival_mj=2.9))  # condition cleared: gone
    assert not provider.update(_view(t=506.0, **low))  # back, but suppressed (same lap)
    again = provider.update(_view(t=600.0, me=_car(lap=6, s_m=4310.0), **low))
    assert len(again) == 1 and again[0].alert_id != first[0].alert_id  # a lap later
    held = provider.update(_view(t=600.0 + provider.cfg.expiry_s, me=_car(lap=6, s_m=4320.0),
                                 **low))  # fmt: skip
    assert not held  # expired after expiry_s although the condition still holds


# --------------------------------------------------------------------------- #
# Plug-in and information barrier
# --------------------------------------------------------------------------- #


def test_provider_is_chosen_by_config(
    cfg: AlertsConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    track = load_track("suzuka", CONFIG_DIR)
    assert isinstance(A.make_provider(cfg, track), A.SimplyClippingLite)
    (tmp_path / "my_clipping.py").write_text(textwrap.dedent("""
        class Provider:
            def update(self, view):
                return []
        def create(cfg, track):
            return Provider()
    """), encoding="utf-8")  # fmt: skip
    monkeypatch.syspath_prepend(str(tmp_path))
    external = A.make_provider(cfg.model_copy(update={"provider": "external:my_clipping"}), track)
    assert external.update(_view()) == []
    sys.modules.pop("my_clipping", None)
    with pytest.raises(ValueError, match="unknown alerts.provider"):
        A.make_provider(cfg.model_copy(update={"provider": "magic"}), track)


def test_provider_reads_engineer_view_only() -> None:
    """The update signature takes an EngineerView; the import contract forbids the rest."""
    hints = inspect.get_annotations(A.SimplyClippingLite.update, eval_str=True)
    assert hints == {"view": EngineerView, "return": list[A.Alert]}
    contract = (ROOT / ".importlinter").read_text(encoding="utf-8")
    assert "source_modules =\n    pitwall_sim.observe.alerts" in contract
    for forbidden in ("pitwall_sim.race", "pitwall_sim.observe.radar", "pitwall_sim.car"):
        assert f"    {forbidden}\n" in contract.split("alerts-engineer-view-only")[1].split("[")[0]


# --------------------------------------------------------------------------- #
# Sprint day 4: confidence floor, same lap, hysteresis
# --------------------------------------------------------------------------- #


def test_no_alert_below_min_confidence(provider: A.SimplyClippingLite) -> None:
    floor = provider.cfg.min_confidence
    assert not provider.update(_view(rival_mj=2.0, conf=floor - 0.01))
    assert provider.update(_view(t=501.0, rival_mj=2.0, conf=floor + 0.01))


def test_attack_and_defend_only_against_cars_on_our_lap(provider: A.SimplyClippingLite) -> None:
    def view(laps_down_rival: int, **kw: object) -> EngineerView:
        v = _view(**kw)  # type: ignore[arg-type]
        timing = replace(v.timing, laps_down={ME: 0, RIVAL: laps_down_rival})
        return replace(v, timing=timing)

    assert not provider.update(view(1, rival_mj=2.0))  # the car "ahead" is a lap down
    assert not provider.update(view(1, t=501.0, **BEHIND, rival_mj=3.9))
    assert _types(provider.update(view(0, t=502.0, rival_mj=2.0))) == {("ATTACK", RIVAL)}


def test_condition_must_hold_before_an_alert_fires(cfg: AlertsConfig) -> None:
    held = A.SimplyClippingLite.for_track(
        cfg.model_copy(update={"hold_s": 1.0}), load_track("suzuka", CONFIG_DIR)
    )
    assert not held.update(_view(t=500.0, rival_mj=2.0))
    assert not held.update(_view(t=500.5, rival_mj=2.0))
    assert held.update(_view(t=501.0, rival_mj=2.0))  # true for 1.0 s
    flicker = A.SimplyClippingLite.for_track(
        cfg.model_copy(update={"hold_s": 1.0}), load_track("suzuka", CONFIG_DIR)
    )
    flicker.update(_view(t=600.0, rival_mj=2.0))
    flicker.update(_view(t=600.5, rival_mj=2.9))  # condition dropped: the clock restarts
    assert not flicker.update(_view(t=601.0, rival_mj=2.0))
    assert flicker.update(_view(t=602.0, rival_mj=2.0))
