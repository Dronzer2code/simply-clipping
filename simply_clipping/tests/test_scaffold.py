"""SC-0: the scaffold honours the bridge contract and the spec rules (SC-R01, R02, R04, R05)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import simply_clipping
from simply_clipping.alerts import ALERT_COLUMNS
from simply_clipping.energy import ESTIMATE_COLUMNS, STATES
from simply_clipping.loader import const, load_config, load_own

PACKAGE = Path(simply_clipping.__file__).parent


def _feed(folder: Path) -> Path:
    """Write a 2-car, 5 s public feed at 4 Hz, like an export's feed/ folder."""
    feed = folder / "feed"
    feed.mkdir()
    t = np.arange(0.0, 5.0, 0.25)
    cars = pd.concat(
        pd.DataFrame({
            "driver": code, "time": t + offset, "distance": 80.0 * (t + offset),
            "speed": 288.0, "throttle": throttle, "brake": t > 4.0, "gear": 8,
            "x": t, "y": 0.0,
        })
        for code, offset, throttle in (("AAA", 0.0, 100), ("BBB", 0.1, 10))
    )  # fmt: skip
    cars.to_parquet(feed / "cars.parquet", index=False)
    pd.DataFrame({"Driver": ["AAA"], "LapNumber": [1]}).to_parquet(feed / "laps.parquet")
    pd.DataFrame({"Driver": ["AAA"], "LapNumber": [1]}).to_parquet(feed / "gaps.parquet")
    return feed


def _layout(folder: Path) -> Path:
    path = folder / "layout.json"
    path.write_text(json.dumps({"track_id": "t", "length_m": 1000.0, "centreline": {},
                                "zones": [], "corners": []}))  # fmt: skip
    return path


def test_config_has_every_section_and_names_missing_keys() -> None:
    cfg = load_config()
    for section in ("signal", "car", "fuel", "taper", "states", "cda_fit", "energy", "anchor",
                    "confidence", "battles", "alerts", "output"):  # fmt: skip
        assert section in cfg, section
    assert const(cfg, "alerts.attack_margin_mj") == 0.8
    with pytest.raises(KeyError, match="alerts.nope"):
        const(cfg, "alerts.nope")


@pytest.mark.parametrize("our", ["AAA", None])
def test_run_writes_the_bridge_files(tmp_path: Path, our: str | None) -> None:
    out = tmp_path / "out"
    out.mkdir()
    simply_clipping.run(_feed(tmp_path), out, our, None, _layout(tmp_path))
    est = pd.read_parquet(out / "estimates.parquet")
    assert tuple(est.columns[: len(ESTIMATE_COLUMNS)]) == ESTIMATE_COLUMNS
    assert set(est["driver"]) == {"AAA", "BBB"}
    assert est.groupby("driver").size().max() == 5  # once a second
    assert set(est["state"]) <= set(STATES)
    cfg = load_config()
    assert (
        est["energy_mj"].between(const(cfg, "energy.e_min_mj"), const(cfg, "energy.e_max_mj")).all()
    )
    assert est["confidence"].between(0.0, 1.0).all()
    alerts = out / "alerts.parquet"
    assert alerts.exists() == (our is not None)
    if our is not None:
        assert tuple(pd.read_parquet(alerts).columns) == ALERT_COLUMNS


def test_own_file_gives_our_rows_only(tmp_path: Path) -> None:
    own_file = tmp_path / "ground_truth.parquet"
    pd.DataFrame({
        "driver": ["AAA", "BBB", "AAA"], "time_s": [0.0, 0.0, 0.1], "lap": 1,
        "lap_distance_m": 0.0, "speed_kmh": 300.0, "throttle": 1.0, "brake": False,
        "battery_mj": [3.0, 1.0, 2.9], "p_ice_kw": 400.0,
    }).to_parquet(own_file, index=False)  # fmt: skip
    own = load_own(own_file, "AAA")
    assert set(own["driver"]) == {"AAA"} and len(own) == 2
    assert "p_ice_kw" not in own.columns  # only our listed channels


def test_package_never_names_the_answer_sheet() -> None:
    """SC-R02: no module mentions an export's truth/, baseline/ or run.json."""
    answer_sheet = re.compile(r"truth/|ground_truth|events\.parquet|car_params|baseline/|"
                              r"builtin_alerts|run\.json")  # fmt: skip
    for path in PACKAGE.glob("*.py"):
        assert not answer_sheet.search(path.read_text(encoding="utf-8")), path.name


def test_live_provider_returns_alerts() -> None:
    track = {"track_id": "t", "length_m": 1000.0, "zones": [], "corners": []}
    provider = simply_clipping.create(cfg=None, track=track)
    our_car = SimpleNamespace(driver_id="US", lap=1, s_m=10.0, v_ms=50.0, battery_mj=3.0,
                              throttle=1.0, brake=0.0)  # fmt: skip
    assert provider.update(SimpleNamespace(t_s=5.0, our_car=our_car, rival_feed={})) == []
