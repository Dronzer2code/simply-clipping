"""Hackathon E2: engineer score out of 100 from the H1 decision costs (TRD DEBRIEF AND SCORING)."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from pitwall_sim.config.loader import load_app
from pitwall_sim.debrief.scorer import BEST_TIE_S, engineer_score, score_from_loss
from pitwall_sim.engineer.records import CallCost

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
SCALE_S = 20.0


def _cost(k: int, delta_s: float, best: str = "Ignore") -> CallCost:
    return CallCost(f"snap{k}#{k}", 100.0 + delta_s, best, 100.0, delta_s, 5)


def test_best_calls_score_100() -> None:
    score = engineer_score([_cost(0, 0.0), _cost(1, 0.0), _cost(2, 0.0)], SCALE_S)
    assert score.score == 100.0
    assert score.n_calls == 3 and score.n_best == 3 and score.total_loss_s == 0.0
    assert score.worst_call_id is None


def test_costly_calls_score_lower_per_the_formula() -> None:
    costs = [_cost(0, 0.0), _cost(1, 3.0, "HOLD"), _cost(2, 2.0, "mode PUSH")]
    score = engineer_score(costs, SCALE_S)
    assert score.score == pytest.approx(100.0 * math.exp(-5.0 / SCALE_S))
    assert round(score.score) == 78  # owner decision 2026-10-19: 5 s lost -> 78 points
    assert score.n_best == 1 and score.total_loss_s == pytest.approx(5.0)
    assert score.worst_call_id == "snap1#1" and score.worst_best_option == "HOLD"
    assert score.worst_loss_s == pytest.approx(3.0)
    line = score.breakdown()
    assert "3 calls" in line and "5.0 s lost" in line and "HOLD" in line and "= 78" in line


@pytest.mark.parametrize(("loss_s", "points"), [(5.0, 78), (10.0, 61), (20.0, 37)])
def test_owner_scale_examples(loss_s: float, points: int) -> None:
    assert round(score_from_loss(loss_s, SCALE_S)) == points


def test_more_loss_never_scores_higher() -> None:
    scores = [engineer_score([_cost(0, d)], SCALE_S).score for d in (0.0, 0.5, 2.0, 8.0, 40.0)]
    assert scores == sorted(scores, reverse=True)
    assert 0.0 < scores[-1] < scores[0] == 100.0


def test_negative_delta_counts_as_no_loss() -> None:
    score = engineer_score([_cost(0, -0.01), _cost(1, 1.0)], SCALE_S)
    assert score.total_loss_s == pytest.approx(1.0)


def test_no_calls_is_100_with_nothing_scored() -> None:
    score = engineer_score([], SCALE_S)
    assert score.score == 100.0 and score.n_calls == 0 and score.worst_call_id is None
    assert "no calls" in score.breakdown()


def test_bad_scale_is_an_error() -> None:
    with pytest.raises(ValueError, match="score_scale_s"):
        engineer_score([_cost(0, 1.0)], 0.0)


def test_scale_and_tie_match_the_config_and_the_costs() -> None:
    from pitwall_sim.live import costs

    assert load_app(CONFIG_DIR).debrief.score_scale_s == SCALE_S
    assert costs.BEST_TIE_S == BEST_TIE_S
