"""Tests for feeding group-stage form into knockout predictions (P1-A).

Two pieces are covered: :func:`team_ppg_map` parses live standings into a
name→ppg lookup, and :meth:`MatchPredictor.predict` actually shifts the win
probability when that form is passed in (the ``_form_adjustment`` term, which
was dead code on the knockout path until now).
"""

from pytest import approx

from app.services.forecasting import team_ppg_map
from app.services.match_predictor import predictor


def _standings(rows: list[tuple[str, int, int]]) -> dict:
    """Minimal football-data standings for one group.

    Args:
        rows: ``(team_name, played, points)`` per team.
    """
    table = [
        {
            "team": {"id": i, "name": name, "crest": ""},
            "playedGames": played,
            "points": pts,
            "goalDifference": 0,
            "goalsFor": 0,
        }
        for i, (name, played, pts) in enumerate(rows, start=1)
    ]
    return {
        "standings": [
            {"stage": "GROUP_STAGE", "group": "GROUP_A", "table": table}
        ]
    }


def test_team_ppg_map_computes_points_per_game() -> None:
    """ppg = points / games played, keyed by team name."""
    # Arrange: a group winner (9/3) and a pointless side (0/3).
    standings = _standings([("Brazil", 3, 9), ("Haiti", 3, 0)])

    # Act
    ppg = team_ppg_map(standings, {"matches": []})

    # Assert
    assert ppg["Brazil"] == approx(3.0)
    assert ppg["Haiti"] == approx(0.0)


def test_team_ppg_map_omits_unplayed_teams_gracefully() -> None:
    """A team with zero games still maps (default 1.5), never divides by zero."""
    # Arrange / Act
    ppg = team_ppg_map(_standings([("Spain", 0, 0)]), {"matches": []})

    # Assert: builder falls back to neutral 1.5 when played == 0.
    assert ppg["Spain"] == approx(1.5)


def test_form_lifts_the_in_form_side_in_knockout() -> None:
    """Strong group form raises a team's knockout win probability."""
    # Arrange: same matchup, neutral form vs Brazil hot / opponent cold.
    p_neutral, _, _ = predictor.predict("Brazil", "Morocco", stage="LAST_32")

    # Act
    p_in_form, _, _ = predictor.predict(
        "Brazil", "Morocco", ppg_a=3.0, ppg_b=0.0, stage="LAST_32"
    )

    # Assert: the form adjustment is monotonic and non-trivial.
    assert p_in_form > p_neutral
