"""Day 8: the bench runs an external plug-in (the docs' hello world) end to end."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pandas as pd
import pytest

from pitwall_sim.bench import BenchSetup, bench, scenarios_arg, seeds_arg
from pitwall_sim.export import export_race

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "docs" / "examples" / "hello_clipping.py"


@pytest.fixture
def plugin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    shutil.copy(TEMPLATE, tmp_path / "hello_clipping.py")
    monkeypatch.syspath_prepend(str(tmp_path))
    yield "hello_clipping"
    sys.modules.pop("hello_clipping", None)


@pytest.mark.slow
def test_bench_runs_the_template_plugin(tmp_path: Path, plugin: str) -> None:
    exports = tmp_path / "exports"
    export_race(exports / "normal_s6", seed=6, scenario="normal", laps=2)  # reused by the bench
    lines: list[str] = []
    setup = BenchSetup(plugin, ("normal",), (6,), exports, tmp_path / "sc_out")
    report = bench(setup, lines.append)
    est = pd.read_parquet(
        tmp_path / "sc_out" / "hello_clipping" / "normal_s6" / "estimates.parquet"
    )
    assert est["driver"].nunique() == 22
    text = report.read_text(encoding="utf-8")
    assert "| metric | built-in | dumb rule | hello_clipping |" in text
    assert "## TEST SET (seeds 6-10)" in text
    lines.clear()
    bench(setup, lines.append)
    assert lines == ["[1/1] normal_s6: hello_clipping output exists"]


def test_template_live_provider_plugs_into_the_pit_wall(plugin: str) -> None:
    from pitwall_sim.config.loader import load_app, load_track
    from pitwall_sim.observe.alerts import make_provider

    cfg = load_app().alerts.model_copy(update={"provider": f"external:{plugin}"})
    provider = make_provider(cfg, load_track("suzuka"))
    assert provider.update(None) == []  # type: ignore[arg-type]


def test_arguments() -> None:
    assert seeds_arg("6-10") == (6, 7, 8, 9, 10) and seeds_arg("1,4-5") == (1, 4, 5)
    assert scenarios_arg("normal,repass") == ("normal", "repass")
    assert len(scenarios_arg("all")) == 6
    with pytest.raises(ValueError, match="unknown scenario"):
        scenarios_arg("rain")
