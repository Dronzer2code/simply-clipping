"""T-036 / MVP-05 / NFR-02: a full 22-car race runs headless in 10 s or less.

The race runs through the CLI in a fresh process, as a user would start it. A
one-lap warm-up run first fills Numba's on-disk cache, so the timed run measures
the simulation, not a one-off compile. The measured times are printed (NFR-02:
"the measured time MUST be reported"); run with ``pytest -s`` to see them.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BUDGET_S = 10.0
#: Until T-02B calibrates fuel_start_kg, the 70 kg placeholder runs dry near lap
#: 44 (cars at 0 kg retire), so the timed race carries enough for 53 laps.
FUEL_KG = "110"
WALL = re.compile(r"setup ([\d.]+) s \+ race ([\d.]+) s = ([\d.]+) s")


def _run(*extra: str) -> tuple[subprocess.CompletedProcess[str], float]:
    start = time.perf_counter()
    done = subprocess.run(
        [sys.executable, "-m", "pitwall_sim.race.engine", "--headless", "--track", "suzuka",
         "--rules", "2026_post_miami", "--seed", "42", "--fuel-kg", FUEL_KG, *extra],
        cwd=ROOT, capture_output=True, text=True, timeout=600,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )  # fmt: skip
    return done, time.perf_counter() - start


@pytest.mark.slow
def test_headless_runtime() -> None:
    warm, _ = _run("--laps", "1")
    assert warm.returncode == 0, warm.stderr

    # Owner round 16 tolerance: a laptop load spike can add seconds to one run, so
    # a miss is retried once and the faster run counts.
    runs = []
    for _ in range(2):
        done, process_s = _run()
        assert done.returncode == 0, done.stderr
        lines = done.stdout.strip().splitlines()
        assert len([line for line in lines if " laps " in line]) == 22
        match = WALL.search(lines[-1])
        assert match is not None, lines[-1]
        runs.append((*(float(g) for g in match.groups()), process_s))
        if runs[-1][2] <= BUDGET_S:
            break
    setup_s, race_s, total_s, process_s = min(runs, key=lambda r: r[2])
    print(
        f"\nNFR-02 headless Suzuka race: setup {setup_s:.2f} s + race {race_s:.2f} s = "
        f"{total_s:.2f} s simulated; whole process incl. interpreter start {process_s:.2f} s"
    )
    assert total_s <= BUDGET_S


def test_cli_needs_headless_and_reports_bad_config(capsys: pytest.CaptureFixture[str]) -> None:
    from pitwall_sim.race.engine import EXIT_INVALID, EXIT_OK, main

    with pytest.raises(SystemExit):
        main(["--laps", "1"])  # no --headless
    assert main(["--headless", "--track", "nowhere", "--laps", "1"]) == EXIT_INVALID
    assert main(["--headless", "--laps", "1", "--fuel-kg", FUEL_KG]) == EXIT_OK
    out = capsys.readouterr().out
    assert "race finished" in out and "NFR-02 budget 10 s" in out
