"""Unprompted driver radio (hackathon H3): the driver speaks up, from Our Car's data only.

Triggers, checked every tick, at most one message per ``MIN_GAP_S`` of race time:

- battery below ``LOW_BATTERY_MJ`` with a long straight (an acceleration zone of at
  least ``LONG_STRAIGHT_M``) starting within ``STRAIGHT_AHEAD_M``: once per straight;
- tyre wear above ``TYRE_WEAR``: once per set of tyres;
- a place gained or lost (public timing);
- rain starting (``Rain at Turn 7, it's getting slippery.``, at the next corner
  ahead) or stopping (public weather condition, E1): said at once, not rate limited.

Safety Car / VSC calls come from the session (they are not rate limited). Texts are
templates with the facts filled in (no LLM).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pitwall_sim.config.models import TrackConfig
from pitwall_sim.observe.engineer_view import EngineerView

MIN_GAP_S = 20.0
"""At most one unprompted message per this many race seconds (owner H3)."""
LOW_BATTERY_MJ = 0.5
TYRE_WEAR = 0.70
LONG_STRAIGHT_M = 600.0
"""A long straight (the alert rules' RE-PASS straight)."""
STRAIGHT_AHEAD_M = 400.0


@dataclass
class DriverRadio:
    """The driver's own radio messages for one race."""

    our: str
    track: TrackConfig
    _last_t: float = -1e9
    _place: int | None = None
    _straight_warned: tuple[int, str] | None = None
    """(lap, zone) of the last low-battery warning."""
    _tyres_warned: bool = False
    _straights: list[tuple[str, float]] = field(default_factory=list)
    _condition: str = "DRY"
    """Public weather condition at the last update (E1)."""

    def __post_init__(self) -> None:
        """Long straights: (zone_id, start s) of acceleration zones of ``LONG_STRAIGHT_M``+."""
        length = float(self.track.official_length_m or 0.0)
        for z in self.track.zones:
            span = (z.s_end_m - z.s_start_m) % length if length else z.s_end_m - z.s_start_m
            if "acceleration_zone" in z.tags and span >= LONG_STRAIGHT_M:
                self._straights.append((z.zone_id, z.s_start_m))

    def update(self, view: EngineerView) -> str | None:
        """Return the message to say now, if any (rate limited)."""
        car, timing = view.our_car, view.timing
        if (rain := self._rain(view)) is not None:
            self._last_t = view.t_s
            return rain
        place = timing.order.index(self.our) + 1 if self.our in timing.order else None
        message = None
        if car.tyre_wear < TYRE_WEAR:
            self._tyres_warned = False  # new tyres
        if self._place is not None and place is not None and place != self._place:
            message = f"Up to P{place}." if place < self._place else f"Down to P{place}."
        elif car.battery_mj < LOW_BATTERY_MJ and (straight := self._straight_ahead(car.s_m)):
            if self._straight_warned != (car.lap, straight):
                message = f"Battery's {car.battery_mj:.1f}, I'll be slow down the straight."
                self._straight_warned = (car.lap, straight)
        elif car.tyre_wear > TYRE_WEAR and not self._tyres_warned:
            message = f"Tyres are going, {car.tyre_wear:.0%} worn."
            self._tyres_warned = True
        if place is not None:
            self._place = place
        if message is None or view.t_s - self._last_t < MIN_GAP_S:
            return None
        self._last_t = view.t_s
        return message

    def _rain(self, view: EngineerView) -> str | None:
        """Return the rain line when the public condition goes from DRY to rain or back (E1)."""
        condition = view.weather_public.condition
        old, self._condition = self._condition, condition
        if old == "DRY" and condition != "DRY":
            return f"Rain at {self._corner_ahead(view.our_car.s_m)}, it's getting slippery."
        if old != "DRY" and condition == "DRY":
            return "Rain's stopped."
        return None

    def _corner_ahead(self, s_m: float) -> str:
        length = float(self.track.official_length_m or 1.0)
        corners = self.track.corners
        if not corners:
            return "the track"
        return min(corners, key=lambda c: (c.s_m - s_m) % length).name

    def _straight_ahead(self, s_m: float) -> str | None:
        length = float(self.track.official_length_m or 1.0)
        for zone_id, start in self._straights:
            if 0.0 <= (start - s_m) % length <= STRAIGHT_AHEAD_M:
                return zone_id
        return None
