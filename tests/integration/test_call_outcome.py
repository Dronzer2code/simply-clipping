"""Sprint A-5 / day 4: paired forks at an alert, answered vs ignored.

The forks of one pair share the same overtake draws, so any difference between
them comes from the call. Measured with ``python -m pitwall_sim.engineer.
call_outcome`` (20 seeds x 5 forks, sprint day 5): ATTACK answered 33 % vs
ignored 7 % (+26 points), DEFEND 85 % vs 33 % (+52 points).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pitwall_sim.engineer.call_outcome import outcome

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


@pytest.mark.slow
def test_paired_forks_at_an_attack_alert() -> None:
    results = []
    for seed in range(6):
        r = outcome(seed, "GAS", "ATTACK", key=1, laps=1, variants=2, config_dir=CONFIG_DIR)
        if r is not None:
            results.append(r)
        if len(results) >= 2:
            break
    assert results  # ATTACK alerts are common enough
    for r in results:
        assert r.alert.type == "ATTACK" and r.alert.confidence >= 0.4
        assert 0 <= r.ahead_answered <= r.variants and 0 <= r.ahead_ignored <= r.variants
