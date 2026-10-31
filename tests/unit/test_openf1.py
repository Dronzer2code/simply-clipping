"""T-010 OpenF1 fallback: throttle, response cache and fastest-lap lookup.

No network: every OpenF1 response is canned and served by a fake ``fetch``.
"""

from __future__ import annotations

import io
import urllib.error
import urllib.parse
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from pitwall_sim.config.loader import load_app, load_track
from pitwall_sim.config.models import OpenF1Config, TrackConfig
from pitwall_sim.track import openf1
from pitwall_sim.track.openf1 import (
    OpenF1Client,
    OpenF1Error,
    RateLimiter,
    http_get_json,
    load_lap_xy_openf1,
    load_laps_xy_openf1,
)

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"

SESSIONS = [
    {"session_key": 11230, "session_name": "Qualifying", "location": "Melbourne",
     "circuit_short_name": "Melbourne", "country_name": "Australia"},
    {"session_key": 11249, "session_name": "Qualifying", "location": "Suzuka",
     "circuit_short_name": "Suzuka", "country_name": "Japan"},
]  # fmt: skip

LAPS = [
    # Out lap: has a duration but must be ignored.
    {"driver_number": 30, "lap_number": 1, "date_start": "2026-03-28T06:10:00.000000+00:00",
     "lap_duration": 80.0, "is_pit_out_lap": True},
    # No date_start: ignored.
    {"driver_number": 44, "lap_number": 2, "date_start": None,
     "lap_duration": 85.0, "is_pit_out_lap": False},
    {"driver_number": 63, "lap_number": 9, "date_start": "2026-03-28T06:48:00.000000+00:00",
     "lap_duration": 89.100, "is_pit_out_lap": False},
    {"driver_number": 12, "lap_number": 11, "date_start": "2026-03-28T06:49:01.042000+00:00",
     "lap_duration": 88.778, "is_pit_out_lap": False},
    # Unfinished lap: no duration.
    {"driver_number": 1, "lap_number": 12, "date_start": "2026-03-28T06:50:00.000000+00:00",
     "lap_duration": None, "is_pit_out_lap": False},
]  # fmt: skip

LOCATION = [
    {"date": "2026-03-28T06:49:01.300000+00:00", "x": 30, "y": 40},
    {"date": "2026-03-28T06:49:01.198000+00:00", "x": 10, "y": -20},  # out of order
    {"date": "2026-03-28T06:49:01.500000+00:00", "x": 50, "y": 60},
]


class _FakeApi:
    """Serves canned rows by endpoint and records every URL requested."""

    def __init__(self, routes: dict[str, list[dict[str, Any]]]) -> None:
        self.routes = routes
        self.urls: list[str] = []

    def __call__(self, url: str, timeout_s: float) -> list[dict[str, Any]]:
        self.urls.append(url)
        endpoint = urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1]
        return [dict(row) for row in self.routes.get(endpoint, [])]


class _NoSleepLimiter(RateLimiter):
    def __init__(self) -> None:
        super().__init__(3, 30, clock=lambda: 0.0, sleep=lambda _s: None)


@pytest.fixture
def cfg() -> OpenF1Config:
    return load_app(CONFIG_DIR).openf1


@pytest.fixture
def suzuka() -> TrackConfig:
    return load_track("suzuka", CONFIG_DIR)


def _client(cfg: OpenF1Config, cache_dir: Path, api: _FakeApi) -> OpenF1Client:
    return OpenF1Client(cfg, cache_dir, limiter=_NoSleepLimiter(), fetch=api)


# --------------------------------------------------------------------------- #
# Throttle
# --------------------------------------------------------------------------- #


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_throttle_allows_three_per_second() -> None:
    clock = _FakeClock()
    limiter = RateLimiter(3, 30, clock=clock, sleep=clock.sleep)

    for _ in range(3):
        limiter.wait()
    assert clock.sleeps == []

    limiter.wait()  # 4th request inside the same second waits for the 1st to age out
    assert clock.sleeps == [pytest.approx(1.0)]


def test_throttle_allows_thirty_per_minute() -> None:
    clock = _FakeClock()
    limiter = RateLimiter(3, 30, clock=clock, sleep=clock.sleep)

    for _ in range(30):
        limiter.wait()
    assert clock.now == pytest.approx(9.0)  # 30 requests at 3/s

    limiter.wait()  # 31st waits until the 1st request is a minute old
    assert clock.now == pytest.approx(60.0)


def test_config_carries_the_free_tier_limits(cfg: OpenF1Config) -> None:
    assert cfg.max_requests_per_s == 3
    assert cfg.max_requests_per_min == 30
    assert cfg.base_url == "https://api.openf1.org/v1"


# --------------------------------------------------------------------------- #
# Response cache
# --------------------------------------------------------------------------- #


def test_responses_are_cached_so_a_rebuild_is_offline(cfg: OpenF1Config, tmp_path: Path) -> None:
    api = _FakeApi({"sessions": SESSIONS})
    filters = [("year=", "2026"), ("session_name=", "Qualifying")]

    first = _client(cfg, tmp_path, api).get("sessions", filters)
    again = _client(cfg, tmp_path, api).get("sessions", filters)

    assert first == again == SESSIONS
    assert len(api.urls) == 1
    assert len(list(tmp_path.glob("sessions_*.json"))) == 1


def test_empty_results_are_not_cached(cfg: OpenF1Config, tmp_path: Path) -> None:
    api = _FakeApi({})

    assert _client(cfg, tmp_path, api).get("laps", [("session_key=", "1")]) == []
    assert _client(cfg, tmp_path, api).get("laps", [("session_key=", "1")]) == []
    assert len(api.urls) == 2
    assert not list(tmp_path.iterdir())


def test_http_404_means_no_results(monkeypatch: pytest.MonkeyPatch) -> None:
    def not_found(*_args: object, **_kwargs: object) -> None:
        body = io.BytesIO(b'{"detail":"No results found."}')
        raise urllib.error.HTTPError("https://x", 404, "Not Found", {}, body)  # type: ignore[arg-type]

    monkeypatch.setattr(urllib.request, "urlopen", not_found)
    assert http_get_json("https://api.openf1.org/v1/laps?session_key=1", 5.0) == []


def test_other_http_errors_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    def rate_limited(*_args: object, **_kwargs: object) -> None:
        raise urllib.error.HTTPError("https://x", 429, "Too Many", {}, io.BytesIO(b""))  # type: ignore[arg-type]

    monkeypatch.setattr(urllib.request, "urlopen", rate_limited)
    with pytest.raises(OpenF1Error, match="429"):
        http_get_json("https://api.openf1.org/v1/laps?session_key=1", 5.0)


# --------------------------------------------------------------------------- #
# Fastest lap -> location samples
# --------------------------------------------------------------------------- #


def test_fastest_lap_location_in_metres(
    cfg: OpenF1Config, suzuka: TrackConfig, tmp_path: Path
) -> None:
    api = _FakeApi({"sessions": SESSIONS, "laps": LAPS, "location": LOCATION})

    x, y, source = load_lap_xy_openf1(suzuka, _client(cfg, tmp_path, api))

    # Samples sorted by time and converted from 1/10 m.
    assert np.allclose(x, [1.0, 3.0, 5.0])
    assert np.allclose(y, [-2.0, 4.0, 6.0])
    assert source["provider"] == "openf1"
    assert source["session_key"] == "11249"
    assert source["driver_number"] == "12"
    assert source["lap_time_s"] == "88.778"

    location_url = urllib.parse.unquote(api.urls[-1])
    assert "session_key=11249" in location_url
    assert "driver_number=12" in location_url
    # The window is exactly the fastest lap: date_start .. date_start + lap_duration.
    assert "date>=2026-03-28T06:49:01.042" in location_url
    assert "date<=2026-03-28T06:50:29.820" in location_url
    assert "+" not in location_url


def test_named_driver_uses_the_drivers_endpoint(
    cfg: OpenF1Config, suzuka: TrackConfig, tmp_path: Path
) -> None:
    track = suzuka.model_copy(
        update={"geometry_source": suzuka.geometry_source.model_copy(update={"driver": "RUS"})}
    )
    laps_rus = [lap for lap in LAPS if lap["driver_number"] == 63]
    api = _FakeApi(
        {
            "sessions": SESSIONS,
            "drivers": [{"driver_number": 63, "name_acronym": "RUS"}],
            "laps": laps_rus,
            "location": LOCATION,
        }
    )

    _, _, source = load_lap_xy_openf1(track, _client(cfg, tmp_path, api))

    assert source["driver_number"] == "63"
    assert any("driver_number=63" in url for url in api.urls if "/laps?" in url)


def test_unknown_event_is_reported(cfg: OpenF1Config, suzuka: TrackConfig, tmp_path: Path) -> None:
    track = suzuka.model_copy(update={"fastf1_event": "Atlantis"})
    api = _FakeApi({"sessions": SESSIONS})

    with pytest.raises(OpenF1Error, match="Atlantis"):
        load_lap_xy_openf1(track, _client(cfg, tmp_path, api))


def test_no_location_samples_is_reported(
    cfg: OpenF1Config, suzuka: TrackConfig, tmp_path: Path
) -> None:
    api = _FakeApi({"sessions": SESSIONS, "laps": LAPS})

    with pytest.raises(OpenF1Error, match="location"):
        load_lap_xy_openf1(suzuka, _client(cfg, tmp_path, api))


def test_session_names_cover_the_fastf1_identifiers() -> None:
    assert openf1.SESSION_NAMES["Q"] == "Qualifying"
    assert openf1.SESSION_NAMES["R"] == "Race"


def test_pooled_laps_are_each_drivers_best_fastest_first(
    cfg: OpenF1Config, suzuka: TrackConfig, tmp_path: Path
) -> None:
    """T-029: the N fastest clean laps, one per driver."""
    many = LAPS + [
        {"driver_number": 63, "lap_number": 12, "date_start": "2026-03-28T06:51:00.000000+00:00",
         "lap_duration": 89.050, "is_pit_out_lap": False},  # car 63's better lap
        {"driver_number": 81, "lap_number": 7, "date_start": "2026-03-28T06:45:00.000000+00:00",
         "lap_duration": 89.300, "is_pit_out_lap": False},
    ]  # fmt: skip
    location = [{"date": f"2026-03-28T06:49:{i:02d}.000000+00:00", "x": 10 * i, "y": 0}
                for i in range(30)]  # fmt: skip
    api = _FakeApi({"sessions": SESSIONS, "laps": many, "location": location})

    laps, source = load_laps_xy_openf1(suzuka, _client(cfg, tmp_path, api), 3)

    assert len(laps) == 3
    assert source["pooled_laps"] == "12:88.778;63:89.050;81:89.300"
    assert source["driver_number"] == "12" and source["lap_time_s"] == "88.778"
    assert np.allclose(laps[0][0][:3], [0.0, 1.0, 2.0])  # 1/10 m -> m


def test_one_lap_requested_is_the_fastest_lap(
    cfg: OpenF1Config, suzuka: TrackConfig, tmp_path: Path
) -> None:
    api = _FakeApi({"sessions": SESSIONS, "laps": LAPS, "location": LOCATION})

    laps, source = load_laps_xy_openf1(suzuka, _client(cfg, tmp_path, api), 1)

    assert len(laps) == 1 and "pooled_laps" not in source
