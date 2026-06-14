"""Tests for the forecast ledger scoring and calibration layer.

The scoring rules (:func:`_brier`, :func:`_log_loss`, :func:`_rps`) are
tested deterministically against hand-computed values, including the RPS
ordinal property (failing "near" beats failing "far"). :func:`evaluate` is
wired end to end over a temporary ledger with three finished matches whose
outcomes are chosen to exercise the maturity layer, the skill scores and the
favourite/underdog stratification.
"""

import json
import math

from pytest import approx

from app.services import forecast_ledger as fl
from app.services.forecast_ledger import (
    _brier,
    _favorite_view,
    _log_loss,
    _rps,
    _score,
    _stratum,
    evaluate,
)


def test_brier_perfect_and_worst() -> None:
    """Brier is 0 for a perfect call and 2 for the worst possible one."""
    assert _brier((1.0, 0.0, 0.0), (1, 0, 0)) == approx(0.0)
    assert _brier((0.0, 0.0, 1.0), (1, 0, 0)) == approx(2.0)


def test_log_loss_uses_realized_category() -> None:
    """Log-loss is -log of the probability mass on the actual outcome."""
    assert _log_loss((0.6, 0.2, 0.2), (1, 0, 0)) == approx(-math.log(0.6))


def test_rps_rewards_being_close_in_the_ordinal_scale() -> None:
    """When the home team wins, predicting a draw beats predicting an away win.

    This is the property Brier misses: home > draw > away is ordinal, so a
    draw prediction is "closer" to a home win than an away prediction.
    """
    # Arrange: home actually won.
    onehot = (1, 0, 0)

    # Act
    near = _rps((0.0, 1.0, 0.0), onehot)  # predicted draw
    far = _rps((0.0, 0.0, 1.0), onehot)  # predicted away win

    # Assert
    assert near == approx(0.5)
    assert far == approx(1.0)
    assert near < far


def test_rps_perfect_is_zero() -> None:
    """A perfect ordinal forecast scores zero RPS."""
    assert _rps((1.0, 0.0, 0.0), (1, 0, 0)) == approx(0.0)


def test_score_returns_all_three_metrics() -> None:
    """_score bundles brier, logLoss and rps together."""
    sc = _score((0.5, 0.25, 0.25), (1, 0, 0))
    assert set(sc) == {'brier', 'logLoss', 'rps'}


def test_stratum_buckets() -> None:
    """Favourite probabilities land in the expected mismatch buckets."""
    assert _stratum(0.40) == 'tossUp'
    assert _stratum(0.50) == 'lean'
    assert _stratum(0.60) == 'clearFavorite'
    assert _stratum(0.72) == 'heavyFavorite'


def test_favorite_view_picks_the_stronger_side() -> None:
    """The favourite is the higher win probability; flag tracks home/away."""
    home_fav = _favorite_view({'homeWin': 0.7, 'draw': 0.2, 'awayWin': 0.1})
    away_fav = _favorite_view({'homeWin': 0.2, 'draw': 0.3, 'awayWin': 0.5})

    assert home_fav == (0.7, True)
    assert away_fav == (0.5, False)


def test_favorite_view_none_without_signal() -> None:
    """A layer with no win mass (e.g. absent) yields None."""
    assert (
        _favorite_view({'homeWin': 0.0, 'draw': 0.0, 'awayWin': 0.0}) is None
    )


def _seed_ledger(path) -> None:
    """Write a three-match ledger: a home win, an upset and a draw."""
    before = '2025-12-31T00:00:00+00:00'
    ledger = {
        'A|B': {
            'home': 'A',
            'away': 'B',
            'stage': 'GROUP_STAGE',
            'snapshots': [
                {
                    'recordedAtUtc': before,
                    'probs': {
                        'model': {
                            'homeWin': 0.6,
                            'draw': 0.2,
                            'awayWin': 0.2,
                        },
                        'market': {
                            'homeWin': 0.55,
                            'draw': 0.25,
                            'awayWin': 0.2,
                        },
                        'blended': {
                            'homeWin': 0.6,
                            'draw': 0.2,
                            'awayWin': 0.2,
                        },
                        'maturity': {
                            'homeWin': 0.5,
                            'draw': 0.25,
                            'awayWin': 0.25,
                        },
                    },
                    'extras': {},
                }
            ],
        },
        'C|D': {
            'home': 'C',
            'away': 'D',
            'stage': 'GROUP_STAGE',
            'snapshots': [
                {
                    'recordedAtUtc': before,
                    'probs': {
                        'model': {
                            'homeWin': 0.7,
                            'draw': 0.2,
                            'awayWin': 0.1,
                        },
                        'market': None,
                        'blended': {
                            'homeWin': 0.7,
                            'draw': 0.2,
                            'awayWin': 0.1,
                        },
                    },
                    'extras': {},
                }
            ],
        },
        'E|F': {
            'home': 'E',
            'away': 'F',
            'stage': 'GROUP_STAGE',
            'snapshots': [
                {
                    'recordedAtUtc': before,
                    'probs': {
                        'model': {
                            'homeWin': 0.4,
                            'draw': 0.3,
                            'awayWin': 0.3,
                        },
                        'market': None,
                        'blended': {
                            'homeWin': 0.4,
                            'draw': 0.3,
                            'awayWin': 0.3,
                        },
                    },
                    'extras': {},
                }
            ],
        },
    }
    path.write_text(json.dumps(ledger), encoding='utf-8')


def _fixtures() -> list[dict]:
    """Finished fixtures: A beats B, D upsets C, E draws F."""

    def fx(home: str, away: str, sh: int, sa: int) -> dict:
        return {
            'status': 'FINISHED',
            'utcDate': '2026-01-01T00:00:00Z',
            'homeTeam': {'name': home},
            'awayTeam': {'name': away},
            'score': {'home': sh, 'away': sa},
        }

    return [fx('A', 'B', 2, 0), fx('C', 'D', 0, 1), fx('E', 'F', 1, 1)]


def test_evaluate_scores_each_layer(tmp_path, monkeypatch) -> None:
    """summary carries Brier/log-loss/RPS per layer over finished matches."""
    # Arrange
    ledger_file = tmp_path / 'ledger.json'
    _seed_ledger(ledger_file)
    monkeypatch.setattr(fl, 'LEDGER_PATH', ledger_file)

    # Act
    result = evaluate(_fixtures())

    # Assert: model saw all three; means are present.
    assert result['summary']['model']['matches'] == 3
    assert result['summary']['model']['meanBrier'] == approx(0.7733, abs=1e-4)
    assert result['summary']['model']['meanLogLoss'] is not None
    assert result['summary']['model']['meanRps'] is not None


def test_evaluate_scores_maturity_layer(tmp_path, monkeypatch) -> None:
    """The maturity layer is scored only on the match that carries it."""
    # Arrange
    ledger_file = tmp_path / 'ledger.json'
    _seed_ledger(ledger_file)
    monkeypatch.setattr(fl, 'LEDGER_PATH', ledger_file)

    # Act
    result = evaluate(_fixtures())

    # Assert: only A|B had a maturity snapshot; Brier of (.5,.25,.25) vs home.
    assert result['summary']['maturity']['matches'] == 1
    assert result['summary']['maturity']['meanBrier'] == approx(0.375)


def test_evaluate_skill_vs_climatology(tmp_path, monkeypatch) -> None:
    """Skill is reported vs climatology; here the model trails it slightly."""
    # Arrange
    ledger_file = tmp_path / 'ledger.json'
    _seed_ledger(ledger_file)
    monkeypatch.setattr(fl, 'LEDGER_PATH', ledger_file)

    # Act
    result = evaluate(_fixtures())

    # Assert: climatology is uniform here (one of each outcome), and the
    # model's bad miss on the upset drags its skill below zero.
    skill = result['skill']['vsClimatology']['model']['brier']
    assert skill == approx(-0.16, abs=1e-2)


def test_evaluate_strata_flags_the_upset(tmp_path, monkeypatch) -> None:
    """The heavy-favourite bucket records the underdog win (the upset)."""
    # Arrange
    ledger_file = tmp_path / 'ledger.json'
    _seed_ledger(ledger_file)
    monkeypatch.setattr(fl, 'LEDGER_PATH', ledger_file)

    # Act
    result = evaluate(_fixtures())

    # Assert: C|D was a 0.7 favourite that lost → underdog win rate 1.0.
    heavy = result['strata']['heavyFavorite']
    assert heavy['matches'] == 1
    assert heavy['obsFavWinRate'] == approx(0.0)
    assert heavy['obsUnderdogWinRate'] == approx(1.0)


def test_evaluate_keeps_legacy_keys(tmp_path, monkeypatch) -> None:
    """Existing consumers still find matches + per-match brier."""
    # Arrange
    ledger_file = tmp_path / 'ledger.json'
    _seed_ledger(ledger_file)
    monkeypatch.setattr(fl, 'LEDGER_PATH', ledger_file)

    # Act
    result = evaluate(_fixtures())

    # Assert
    assert len(result['matches']) == 3
    assert 'brier' in result['matches'][0]
    assert result['matches'][0]['brier']['model'] is not None


def test_evaluate_empty_ledger_is_safe(tmp_path, monkeypatch) -> None:
    """No finished matches → empty but well-formed summary, no crash."""
    # Arrange
    ledger_file = tmp_path / 'ledger.json'
    ledger_file.write_text('{}', encoding='utf-8')
    monkeypatch.setattr(fl, 'LEDGER_PATH', ledger_file)

    # Act
    result = evaluate([])

    # Assert
    assert result['matches'] == []
    assert result['summary']['model']['matches'] == 0
    assert result['baselines']['climatology'] is None
