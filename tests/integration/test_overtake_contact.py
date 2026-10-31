"""T-038 / MVP-11: overtake contact raises an incident; its severity raises a VSC or an SC."""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Literal

import numpy as np
import pytest

from pitwall_sim.race.engine import RaceEngine, RaceSetup
from pitwall_sim.race.overtake import OvertakeEvent

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
OUR = "GAS"
Severity = Literal["LIGHT", "VSC", "SC"]


def _engine(contact_p: float = 1.0, severity: Severity | None = None, laps: int = 8) -> RaceEngine:
    e = RaceEngine(RaceSetup(our_driver_id=OUR, laps=laps, fuel_kg=110.0), CONFIG_DIR)
    while e.t < 60.0:  # a minute of the default race first
        e.tick()
    assert not e.retired and e.track_status.status == "GREEN"
    update: dict[str, object] = {"contact_p": contact_p}
    if severity is not None:
        update["contact_shares"] = {s: float(s == severity) for s in ("LIGHT", "VSC", "SC")}
    events = e.app.race_events.model_copy(update=update)
    e.app = e.app.model_copy(update={"race_events": events})  # this engine only
    return e


def _attempt(e: RaceEngine, a: int, d: int, p_pass: float = 0.5,
             blue_flag: bool = False) -> OvertakeEvent:  # fmt: skip
    return OvertakeEvent(e.t, a, d, float(e.st.s_m[a]), p_pass, False, blue_flag)


@pytest.mark.parametrize(("severity", "status"), [("SC", "SC"), ("VSC", "VSC")])
def test_contact_stops_the_attacker_and_raises_sc_or_vsc(severity: Severity, status: str) -> None:
    e = _engine(severity=severity)
    a, d = 5, 4
    e._contact(_attempt(e, a, d))
    assert e.status[a] == "DNF" and e.retired[a] == f"contact with {e.driver_ids[d]}"
    assert e.status[d] != "DNF"
    assert e.track_status.status == status and e.flag == status
    assert e.contacts[-1].severity == severity and e.contacts[-1].attacker == a
    assert e.track_events[-1][2].startswith(e.driver_ids[a])


def test_light_contact_slows_both_cars_only() -> None:
    e = _engine(severity="LIGHT")
    a, d = 5, 4
    v = e.st.v_ms[[a, d]].copy()
    e._contact(_attempt(e, a, d))
    factor = e.app.race_events.contact_speed_factor
    assert np.allclose(e.st.v_ms[[a, d]], v * factor)
    assert e.track_status.status == "GREEN" and not e.retired
    assert e.contacts[-1].severity == "LIGHT"


def test_no_contact_on_hopeless_attempts_or_blue_flags() -> None:
    e = _engine(severity="SC")
    state = pickle.dumps(e.rngs["events"].bit_generator.state)
    low = e.app.race_events.contact_min_p_pass / 2.0
    e._contact(_attempt(e, 5, 4, p_pass=low))
    e._contact(_attempt(e, 5, 4, blue_flag=True))
    assert not e.contacts and e.track_status.status == "GREEN"
    assert pickle.dumps(e.rngs["events"].bit_generator.state) == state  # no draw spent


def test_contact_happens_in_a_race_and_is_deterministic() -> None:
    """Every real attempt touches (contact_p 1): the race raises SC / VSC from contact."""

    def run() -> RaceEngine:
        e = _engine(contact_p=1.0)
        while not e.contacts and e.t < 1500.0 and not e.finished:
            e.tick()
        return e

    first, again = run(), run()
    assert first.contacts and first.contacts == again.contacts
    c = first.contacts[0]
    assert c.severity in ("LIGHT", "VSC", "SC")
    if c.severity != "LIGHT":
        assert first.track_status.status in ("SC", "VSC")
