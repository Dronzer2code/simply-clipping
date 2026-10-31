"""Hackathon H3: unprompted driver radio triggers and the 20 s rate limit."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pitwall_sim.config.loader import load_track
from pitwall_sim.live.driver_radio import MIN_GAP_S, DriverRadio

TRACK = load_track("suzuka", Path(__file__).resolve().parents[2] / "config")
SM2_START = 4082.0  # Suzuka's back straight (an acceleration zone over 600 m)


def _view(t: float, place: int = 5, battery: float = 3.0, wear: float = 0.2,
          s_m: float = 2000.0, lap: int = 3) -> Any:  # fmt: skip
    order = [f"C{k}" for k in range(1, 23)]
    order.insert(place - 1, "US")
    car = SimpleNamespace(lap=lap, s_m=s_m, battery_mj=battery, tyre_wear=wear)
    return SimpleNamespace(t_s=t, our_car=car, timing=SimpleNamespace(order=order[:22]))


def test_triggers_and_rate_limit() -> None:
    radio = DriverRadio("US", TRACK)
    assert radio.update(_view(0.0)) is None  # first look: nothing changed
    assert radio.update(_view(10.0, place=4)) == "Up to P4."
    assert radio.update(_view(15.0, place=6)) is None  # within 20 s: quiet
    assert radio.update(_view(10.0 + MIN_GAP_S, place=7)) == "Down to P7."
    low = radio.update(_view(60.0, place=7, battery=0.3, s_m=SM2_START - 200.0))
    assert low == "Battery's 0.3, I'll be slow down the straight."
    assert radio.update(_view(90.0, place=7, battery=0.3, s_m=SM2_START - 100.0)) is None  # once
    assert radio.update(_view(120.0, place=7, wear=0.74)) == "Tyres are going, 74% worn."
    assert radio.update(_view(150.0, place=7, wear=0.8)) is None  # once per set
    radio.update(_view(160.0, place=7, wear=0.05))  # new tyres
    assert radio.update(_view(200.0, place=7, wear=0.72)) == "Tyres are going, 72% worn."


def test_low_battery_only_before_a_long_straight() -> None:
    radio = DriverRadio("US", TRACK)
    radio.update(_view(0.0))
    assert radio.update(_view(30.0, battery=0.3, s_m=2500.0)) is None  # in the esses
