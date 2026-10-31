"""Sprint S-4: the batch runs, scores, writes partial results and resumes."""

from __future__ import annotations

from pathlib import Path

import pytest

from pitwall_sim.evaluate.batch import aggregate, markdown
from pitwall_sim.export.__main__ import main


@pytest.mark.slow
def test_batch_writes_results_and_resumes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out, md = tmp_path / "batch", tmp_path / "SC_RESULTS.md"
    args = ["--seeds", "5-6", "--scenario", "normal", "--laps", "2", "--out", str(out),
            "--results", str(md)]  # fmt: skip
    assert main(args) == 0
    text = md.read_text(encoding="utf-8")
    assert "## TEST SET (seeds 6-10)" in text and "## TUNE SET (seeds 1-5)" in text
    assert "| energy MAE MJ |" in text and "built-in" in text and "dumb rule" in text
    agg = aggregate(out)
    assert agg["tune"]["normal"]["built-in"]["seeds"] == [5]
    assert agg["test"]["normal"]["built-in"]["energy MAE MJ"]["n"] == 1
    capsys.readouterr()
    assert main(args) == 0  # resumes: nothing exported again
    assert capsys.readouterr().out.count("exists, skipped") == 2
    assert markdown(agg).startswith("# SC_RESULTS.md")
