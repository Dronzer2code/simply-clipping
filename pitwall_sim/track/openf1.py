"""OpenF1 REST client: backup source for track geometry (F01, PF-01).

FastF1 reads F1's live-timing archive, which now needs a Formula 1 account
login. OpenF1 (https://openf1.org, free, no auth, data from 2023) serves the
same car position samples, so the track builder falls back to it.

Every raw response is cached under ``paths.openf1_cache``, so a rebuild needs no
network, and live requests are throttled to the free-tier rate limit
(``openf1.max_requests_per_s`` / ``max_requests_per_min``). Real Race replay (R4)
may reuse this client for the same reason.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from pitwall_sim.config.models import OpenF1Config, TrackConfig

logger = logging.getLogger(__name__)

type FloatArray = npt.NDArray[np.float64]
type Rows = list[dict[str, Any]]
type Fetch = Callable[[str, float], Rows]

#: OpenF1 location x/y are in 1/10 m (same as FastF1 position data).
OPENF1_POS_UNIT_M = 0.1

#: FastF1 session identifiers (as in ``geometry_source.session``) -> OpenF1 session_name.
SESSION_NAMES = {
    "FP1": "Practice 1",
    "FP2": "Practice 2",
    "FP3": "Practice 3",
    "SQ": "Sprint Qualifying",
    "S": "Sprint",
    "Q": "Qualifying",
    "R": "Race",
}


class OpenF1Error(Exception):
    """OpenF1 has no usable data, or a request failed."""


class RateLimiter:
    """Block until another request fits within per-second and per-minute limits."""

    def __init__(
        self,
        per_second: int,
        per_minute: int,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Create a limiter; ``clock`` and ``sleep`` are injectable for tests."""
        self._per_second = per_second
        self._per_minute = per_minute
        self._clock = clock
        self._sleep = sleep
        self._sent: deque[float] = deque()

    def wait(self) -> None:
        """Sleep as needed, then record one request."""
        now = self._clock()
        while self._sent and now - self._sent[0] >= 60.0:
            self._sent.popleft()
        delay = 0.0
        if len(self._sent) >= self._per_minute:
            delay = max(delay, self._sent[-self._per_minute] + 60.0 - now)
        if len(self._sent) >= self._per_second:
            delay = max(delay, self._sent[-self._per_second] + 1.0 - now)
        if delay > 0.0:
            logger.debug("OpenF1 throttle: sleeping %.2f s", delay)
            self._sleep(delay)
        self._sent.append(self._clock())


def http_get_json(url: str, timeout_s: float) -> Rows:
    """GET ``url`` and decode a JSON list. OpenF1's 404 "No results found." is ``[]``."""
    request = urllib.request.Request(url, headers={"User-Agent": "pitwall_sim track builder"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return []
        raise OpenF1Error(f"OpenF1 HTTP {exc.code} for {url}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise OpenF1Error(f"OpenF1 request failed for {url}: {exc}") from exc
    if not isinstance(data, list):
        raise OpenF1Error(f"OpenF1 returned {type(data).__name__}, expected a list, for {url}")
    return data


class OpenF1Client:
    """Cached, throttled OpenF1 GET client."""

    def __init__(
        self,
        cfg: OpenF1Config,
        cache_dir: Path,
        limiter: RateLimiter | None = None,
        fetch: Fetch = http_get_json,
    ) -> None:
        """Create a client; ``fetch`` is injectable so tests never touch the network."""
        self._cfg = cfg
        self._cache_dir = cache_dir
        self._limiter = limiter or RateLimiter(cfg.max_requests_per_s, cfg.max_requests_per_min)
        self._fetch = fetch

    def get(self, endpoint: str, filters: Sequence[tuple[str, str]]) -> Rows:
        """Return rows of ``/<endpoint>`` matching ``filters``, from cache if present.

        Each filter is ``(field_and_operator, value)``, e.g. ``("session_key=", "11249")``
        or ``("date>=", "2026-03-28T06:49:01.042")``. Empty results are not
        cached, since OpenF1 may publish a session's data later.
        """
        query = "&".join(f"{op}{urllib.parse.quote(value, safe=':-.')}" for op, value in filters)
        url = f"{self._cfg.base_url}/{endpoint}?{query}"
        path = self._cache_dir / f"{endpoint}_{hashlib.sha1(url.encode()).hexdigest()[:16]}.json"
        if path.exists():
            logger.debug("OpenF1 cache hit %s", url)
            rows: Rows = json.loads(path.read_text(encoding="utf-8"))
            return rows
        self._limiter.wait()
        logger.info("OpenF1 GET %s", url)
        rows = self._fetch(url, self._cfg.timeout_s)
        if rows:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(rows), encoding="utf-8")
        return rows


def openf1_time(value: datetime) -> str:
    """UTC ISO time without offset (a '+' in a query string would decode as a space)."""
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]


def find_session(track: TrackConfig, client: OpenF1Client) -> dict[str, Any]:
    """Return the OpenF1 session for ``track.geometry_source`` (year, event, session)."""
    src = track.geometry_source
    name = SESSION_NAMES.get(src.session)
    if name is None:
        raise OpenF1Error(f"session {src.session!r} has no OpenF1 equivalent")
    sessions = client.get("sessions", [("year=", str(src.year)), ("session_name=", name)])
    event = track.fastf1_event.casefold()
    for field in ("location", "circuit_short_name", "country_name"):
        matches = [s for s in sessions if str(s.get(field, "")).casefold() == event]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise OpenF1Error(
                f"{len(matches)} {src.year} {name} sessions match {field}={track.fastf1_event!r}"
            )
    raise OpenF1Error(f"no {src.year} {name} session for {track.fastf1_event!r}")


def _driver_number(track: TrackConfig, client: OpenF1Client, session_key: str) -> str | None:
    """OpenF1 ``driver_number`` for ``geometry_source.driver``; ``None`` for "fastest"."""
    code = track.geometry_source.driver
    if code == "fastest":
        return None
    drivers = client.get("drivers", [("session_key=", session_key)])
    for driver in drivers:
        if driver.get("name_acronym") == code:
            return str(driver["driver_number"])
    raise OpenF1Error(f"driver {code!r} not in OpenF1 session {session_key}")


def fastest_lap(track: TrackConfig, client: OpenF1Client) -> tuple[dict[str, Any], dict[str, Any]]:
    """Find the OpenF1 session and fastest timed lap named by ``track.geometry_source``.

    Out laps and laps without a duration or start time are skipped.

    Raises:
        OpenF1Error: No matching session or timed lap.

    """
    session = find_session(track, client)
    session_key = str(session["session_key"])
    driver_number = _driver_number(track, client, session_key)

    lap_filters = [("session_key=", session_key)]
    if driver_number is not None:
        lap_filters.append(("driver_number=", driver_number))
    laps = [
        lap
        for lap in client.get("laps", lap_filters)
        if lap.get("lap_duration") and lap.get("date_start") and not lap.get("is_pit_out_lap")
    ]
    if not laps:
        raise OpenF1Error(f"no timed laps in OpenF1 session {session_key}")
    return session, min(laps, key=lambda row: float(row["lap_duration"]))


def lap_samples(client: OpenF1Client, session_key: str, lap: dict[str, Any], endpoint: str) -> Rows:
    """Time-ordered ``/location`` or ``/car_data`` rows for one lap's window."""
    start = datetime.fromisoformat(str(lap["date_start"]))
    end = start + timedelta(seconds=float(lap["lap_duration"]))
    rows = client.get(
        endpoint,
        [
            ("session_key=", session_key),
            ("driver_number=", str(lap["driver_number"])),
            ("date>=", openf1_time(start)),
            ("date<=", openf1_time(end)),
        ],
    )
    rows.sort(key=lambda row: str(row["date"]))
    return rows


def load_laps_xy_openf1(
    track: TrackConfig, client: OpenF1Client, n_laps: int
) -> tuple[list[tuple[FloatArray, FloatArray]], dict[str, str]]:
    """X/Y in metres for the ``n_laps`` fastest clean laps, one per driver (T-029).

    Clean: a timed lap that is not an out lap. With a named
    ``geometry_source.driver`` or ``n_laps`` = 1 this is that driver's / the
    session's fastest lap only. Laps are returned fastest first.

    Raises:
        OpenF1Error: No matching session, timed lap or location samples.

    """
    if n_laps <= 1 or track.geometry_source.driver != "fastest":
        x, y, source = load_lap_xy_openf1(track, client)
        return [(x, y)], source
    session = find_session(track, client)
    session_key = str(session["session_key"])
    best: dict[int, dict[str, Any]] = {}
    for lap in client.get("laps", [("session_key=", session_key)]):
        if not (lap.get("lap_duration") and lap.get("date_start")) or lap.get("is_pit_out_lap"):
            continue
        car = int(lap["driver_number"])
        if car not in best or float(lap["lap_duration"]) < float(best[car]["lap_duration"]):
            best[car] = lap
    chosen = sorted(best.values(), key=lambda row: float(row["lap_duration"]))[:n_laps]
    laps: list[tuple[FloatArray, FloatArray]] = []
    used: list[str] = []
    for lap in chosen:
        samples = lap_samples(client, session_key, lap, "location")
        if len(samples) < 20:
            logger.warning("car %s: only %d location samples; lap skipped", lap["driver_number"],
                           len(samples))  # fmt: skip
            continue
        laps.append(
            (
                np.array([r["x"] for r in samples], dtype=np.float64) * OPENF1_POS_UNIT_M,
                np.array([r["y"] for r in samples], dtype=np.float64) * OPENF1_POS_UNIT_M,
            )
        )
        used.append(f"{lap['driver_number']}:{float(lap['lap_duration']):.3f}")
    if not laps:
        raise OpenF1Error(f"no OpenF1 location samples for the fastest laps of {session_key}")
    first = chosen[0]
    source = {
        "provider": "openf1",
        "year": str(track.geometry_source.year),
        "event": track.fastf1_event,
        "session": track.geometry_source.session,
        "session_key": session_key,
        "driver_number": str(first["driver_number"]),
        "lap_number": str(first["lap_number"]),
        "lap_time_s": f"{float(first['lap_duration']):.3f}",
        "pooled_laps": ";".join(used),
    }
    return laps, source


def load_lap_xy_openf1(
    track: TrackConfig, client: OpenF1Client
) -> tuple[FloatArray, FloatArray, dict[str, str]]:
    """Load X/Y in metres for the fastest timed lap named by ``track.geometry_source``.

    Raises:
        OpenF1Error: No matching session, timed lap or location samples.

    """
    session, lap = fastest_lap(track, client)
    session_key = str(session["session_key"])
    samples = lap_samples(client, session_key, lap, "location")
    if not samples:
        raise OpenF1Error(f"no OpenF1 location samples for the fastest lap of {session_key}")

    x = np.array([row["x"] for row in samples], dtype=np.float64) * OPENF1_POS_UNIT_M
    y = np.array([row["y"] for row in samples], dtype=np.float64) * OPENF1_POS_UNIT_M
    source = {
        "provider": "openf1",
        "year": str(track.geometry_source.year),
        "event": track.fastf1_event,
        "session": track.geometry_source.session,
        "session_key": session_key,
        "driver_number": str(lap["driver_number"]),
        "lap_number": str(lap["lap_number"]),
        "lap_time_s": f"{float(lap['lap_duration']):.3f}",
    }
    return x, y, source
