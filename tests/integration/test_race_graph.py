"""Graphify track step 1: the race comparison graph (Our Car vs every Rival), after the flag."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from pitwall_sim.engineer.records import CallCost
from pitwall_sim.graph.dashboard import ACCURACY_SCALE_MJ, dashboard_data
from pitwall_sim.graph.race import graph_session, simulate
from pitwall_sim.graph.race_graph import (
    battle_groups,
    build_graph,
    led_to_confidence,
    pair_battle_s,
    race_totals,
    rival_stats,
    write_race_graph,
)
from pitwall_sim.graph.record import (
    RaceNotFinishedError,
    RaceRecord,
    find_battles,
    from_export,
    from_session,
    judge,
)
from pitwall_sim.live.session import LiveSession, LiveSetup

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
OUR = "GAS"
NODE_KEYS = {"id", "label", "file_type", "source_file", "source_location", "community",
             "community_name"}  # fmt: skip
LINK_KEYS = {"source", "target", "relation", "confidence", "confidence_score", "weight"}


@pytest.fixture(scope="module")
def race() -> Any:
    """Run a 3-lap live race (seed 2, Test mode) with an automatic engineer; fake one cost."""
    session = simulate(2, 3, OUR, CONFIG_DIR, radio_lap=2, costs=False, test_mode=True)
    assert session.call_log, "the race should have calls"
    session.costs[0] = CallCost(f"{session.call_log[0].snapshot_id}#0", 101.0, "HOLD", 99.5, 1.5, 5)
    record = from_session(session)
    yield session, record, build_graph(record)
    session.close()


def test_no_graph_before_the_flag(tmp_path: Path) -> None:
    s = LiveSession(LiveSetup(our_driver_id=OUR, laps=2), CONFIG_DIR)
    s.advance(30.0)
    assert s.reveal_samples() is None  # the recorder keeps the truth until the flag
    with pytest.raises(RaceNotFinishedError):
        from_session(s)
    with pytest.raises(RaceNotFinishedError):
        graph_session(s, tmp_path)
    assert not any(tmp_path.iterdir())
    s.close()


def test_schema_is_graphifys(race: Any) -> None:
    _, record, graph = race
    meta = graph["graph"]
    assert meta["schema_version"] == 1 and meta["graphify_version"]
    ids = [n["id"] for n in graph["nodes"]]
    assert len(ids) == len(set(ids))
    for n in graph["nodes"]:
        assert NODE_KEYS <= n.keys(), n
        assert meta["communities"][str(n["community"])] == n["community_name"]
    for link in graph["links"]:
        assert LINK_KEYS <= link.keys(), link
        assert link["source"] in ids and link["target"] in ids
        assert link["confidence"] in ("EXTRACTED", "INFERRED")
        assert 0.0 <= link["confidence_score"] <= 1.0
        assert (link["confidence"] == "INFERRED") == (link["relation"] == "led_to")
    kinds = Counter(n["file_type"] for n in graph["nodes"])
    assert kinds["car"] == len(record.cars) == 22
    for kind in ("battle", "alert", "truthcheck", "call", "outcome", "callcost"):
        assert kinds[kind] > 0, kind


def test_our_car_present_and_central(race: Any) -> None:
    _, record, graph = race
    ours = [n for n in graph["nodes"] if n.get("our_car")]
    assert [n["id"] for n in ours] == [f"car:{OUR}"]
    groups, group_of = battle_groups(record)
    assert group_of[OUR] == 0 and groups[0].name.startswith(OUR)  # "GAS-...-... battle"
    assert all(g.name.endswith("battle") or g.name == "no close battles" for g in groups)
    battled = {link["target"] if link["source"] == f"car:{OUR}" else link["source"]
               for link in graph["links"] if link["relation"] == "battled"
               and f"car:{OUR}" in (link["source"], link["target"])}  # fmt: skip
    assert battled  # Our Car is joined to the Rivals it raced


def test_every_alert_and_call_is_linked(race: Any) -> None:
    _, record, graph = race
    out: dict[str, set[str]] = {}
    for link in graph["links"]:
        out.setdefault(link["source"], set()).add(link["relation"])
    for a in record.alerts:
        assert {"about", "checked_by"} <= out[f"alert:{a.alert_id}"]
    for c in record.calls:
        rels = out[f"call:{c.index}"]
        assert "answers" in rels if c.alert_id else "about" in rels or c.rival is None
        if c.outcome:
            assert "led_to" in rels
    led = [link for link in graph["links"] if link["source"] == "call:0"
           and link["relation"] == "led_to"]  # fmt: skip
    if led:
        assert led[0]["confidence_score"] == led_to_confidence(1.5)
    assert any(n["id"] == "cost:0" and n["delta_s"] == 1.5 for n in graph["nodes"])


def test_stats_match_the_reveal_and_call_summary(race: Any) -> None:
    session, record, _ = race
    reveal, summary = session.reveal(), session.summary()
    stats = rival_stats(record)
    for series in reveal.rivals:  # the Reveal's "raced" seconds
        assert stats[series.driver_id]["time_within_1s_s"] == round(series.battle_s, 1)
        known = series.confidence > 0
        mae = float(np.abs(series.estimate_mj - series.truth_mj)[known].mean())
        assert stats[series.driver_id]["radar_mae_mj"] == round(mae, 2)
    assert record.radar_mae_mj == pytest.approx(reveal.radar_mae_mj)
    assert len(record.alerts) == summary.alerts and len(record.calls) == len(session.call_log)
    by_type = Counter((r.alert.rival, r.alert.type) for r in summary.records)
    for rival, s in stats.items():
        for kind, n in s["alerts"].items():
            assert by_type[(rival, kind)] == n
    for item, r in zip(record.alerts, summary.records, strict=True):  # Test mode's verdicts
        assert item.alert_id == r.alert.alert_id and item.outcome == r.outcome
        assert item.truth.right == r.correct
    assert sum(bool(a.truth.right) for a in record.alerts) == summary.correct


def test_files_offline_and_round_trip(race: Any, tmp_path: Path) -> None:
    _, record, graph = race
    paths = write_race_graph(record, tmp_path / record.run_id)
    html = paths.graph_html.read_text(encoding="utf-8")
    assert 'src="lib/vis-network.min.js"' in html and "https://" not in html.split("<style>")[0]
    assert (paths.folder / "lib" / "vis-network.min.js").stat().st_size > 100_000
    assert json.loads(paths.graph_json.read_text(encoding="utf-8")) == graph
    assert build_graph(RaceRecord.load(paths.record)) == graph  # a saved live race rebuilds
    report = paths.report.read_text(encoding="utf-8")
    assert "Rivals fought most" in report and "Battle groups" in report
    labels = json.loads((paths.folder / "labels.json").read_text(encoding="utf-8"))
    assert labels == graph["graph"]["communities"]


def test_dashboard_agrees_with_the_graph(race: Any, tmp_path: Path) -> None:
    _, record, _ = race
    data = dashboard_data(record)
    ids = [c["id"] for c in data["cars"]]
    assert ids[0] == OUR and data["cars"][0]["our"] and len(ids) == 22  # YOU at the top
    assert data["totals"] == race_totals(record)
    battles = data["matrices"]["battles"]
    assert all(battles[i][j] == battles[j][i] for i in range(22) for j in range(22))
    for (x, y), secs in pair_battle_s(record).items():
        assert battles[ids.index(x)][ids.index(y)] == round(secs, 1)
    assert sum(map(sum, data["matrices"]["passes"])) == len(record.passes)
    assert sum(data["matrices"]["alerts"][0]) == len(record.alerts)
    rows = data["accuracy"]
    assert rows and [r["battle_s"] for r in rows] == sorted((r["battle_s"] for r in rows),
                                                            reverse=True)  # fmt: skip
    stats = rival_stats(record)
    for r in rows:
        mae = stats[r["id"]]["radar_mae_mj"]
        if mae is not None:
            assert r["estimate_accuracy"] == round(max(0.0, 1.0 - mae / ACCURACY_SCALE_MJ), 3)
        assert r["alerts_right_pct"] == stats[r["id"]]["alerts_right_pct"]
    paths = write_race_graph(record, tmp_path / record.run_id)
    assert paths.dashboard is not None
    html = paths.dashboard.read_text(encoding="utf-8")
    assert 'src="lib/d3.min.js"' in html and "https://" not in html
    assert (paths.folder / "lib" / "d3.min.js").stat().st_size > 100_000


@pytest.mark.skipif(shutil.which("graphify") is None, reason="graphify CLI not installed")
def test_graphify_reads_our_graph(race: Any, tmp_path: Path) -> None:
    _, record, _ = race
    paths = write_race_graph(record, tmp_path / record.run_id)
    done = subprocess.run(["graphify", "explain", OUR, "--graph", str(paths.graph_json)],
                          capture_output=True, text=True, timeout=60, check=False)  # fmt: skip
    assert done.returncode == 0 and "battled" in done.stdout, done.stdout + done.stderr


def test_judge_and_battles_rules() -> None:
    assert judge("ATTACK", "energy", -1.0, 0.8) is True
    assert judge("ATTACK", "energy", -0.5, 0.8) is False
    assert judge("ATTACK", "observed clip", -0.1, 0.8) is True  # only the sign is claimed
    assert judge("DEFEND", "energy", 0.9, 0.8) is True
    assert judge("REPASS_RISK", None, 2.0, 0.8) is None
    t = np.arange(10.0)
    order = [["A", "B", "C"]] * 10
    gaps = [{"B": 0.5 if k not in (4, 5, 6) else 2.0, "C": 3.0} for k in range(10)]
    battles = find_battles(t, t / 5 + 1, order, gaps)
    assert [(b.ahead, b.behind, b.duration_s) for b in battles] == [("A", "B", 4.0),
                                                                    ("A", "B", 3.0)]  # fmt: skip


def _export(folder: Path) -> Path:
    """Write a tiny export: GAS 0.5 s behind OCO for 60 s, passes it at 30 s; ALB far back."""
    (folder / "truth").mkdir(parents=True)
    (folder / "feed").mkdir()
    (folder / "baseline").mkdir()
    t = np.round(np.arange(0.0, 60.0, 0.1), 1)
    v = 80.0  # m/s
    rows = []
    for d, offset, mj in (("OCO", 40.0, 2.0), ("GAS", 0.0, 3.0), ("ALB", -500.0, 2.5)):
        dist = v * t + offset + np.where((d == "GAS") & (t >= 30.0), 80.0, 0.0)
        rows.append(
            pd.DataFrame(
                {
                    "driver": d,
                    "time_s": t,
                    "distance_m": dist,
                    "speed_kmh": v * 3.6,
                    "battery_mj": mj,
                    "in_pit": False,
                }
            )
        )
    pd.concat(rows).to_parquet(folder / "truth" / "ground_truth.parquet")
    pd.DataFrame(
        {
            "type": ["overtake"],
            "t_start_s": [30.0],
            "t_end_s": [30.0],
            "car_a": ["GAS"],
            "car_b": ["OCO"],
            "blue_flag": [False],
        }
    ).to_parquet(folder / "truth" / "events.parquet")
    pd.DataFrame(
        {
            "time_s": [10.0],
            "lap": [1],
            "type": ["ATTACK"],
            "car_a": ["GAS"],
            "car_b": ["OCO"],
            "confidence": [0.8],
            "branch": ["energy"],
        }
    ).to_parquet(folder / "baseline" / "builtin_alerts.parquet")
    pd.DataFrame(
        {"driver": "OCO", "time_s": np.arange(60.0), "energy_mj": 1.0, "confidence": 0.9}
    ).to_parquet(folder / "baseline" / "builtin_estimates.parquet")
    pd.DataFrame(
        {
            "Driver": ["GAS", "OCO"],
            "LapNumber": [1.0, 1.0],
            "LapTime": pd.to_timedelta([90.0, 91.0], unit="s"),
        }
    ).to_parquet(folder / "feed" / "laps.parquet")
    (folder / "run.json").write_text(
        json.dumps(
            {
                "seed": 7,
                "rule_set": "2026_post_miami",
                "track": "suzuka",
                "laps": 1,
                "alert_pov": "GAS",
                "lap_length_m": 5807.0,
                "finished": True,
            }
        ),
        encoding="utf-8",
    )
    return folder  # fmt: skip


def test_graph_from_an_export(tmp_path: Path) -> None:
    record = from_export(_export(tmp_path / "suzuka_tiny_s7"), CONFIG_DIR)
    assert record.source == "export" and record.our == "GAS" and not record.calls
    gas_oco = [b for b in record.battles if b.cars == ("GAS", "OCO")]
    assert gas_oco and sum(b.duration_s for b in gas_oco) >= 55.0
    assert not [b for b in record.battles if "ALB" in b.cars]
    assert [(p.passer, p.passed) for p in record.passes] == [("GAS", "OCO")]
    (alert,) = record.alerts
    assert alert.truth.rival_true_mj == 2.0 and alert.truth.estimate_mj == 1.0
    assert alert.truth.right is True  # OCO really had 1.0 MJ less than GAS (margin 0.8)
    assert alert.outcome == "pass made"
    assert record.radar["OCO"].mae_mj == pytest.approx(1.0)
    stats = rival_stats(record)["OCO"]
    assert stats["passes_made"] == 1 and stats["alerts_right_pct"] == 100.0
    assert stats["lap_delta_s"] is None  # one lap only: no laps to compare
    graph = build_graph(record)
    assert graph["graph"]["communities"]["0"].startswith("GAS-OCO")
