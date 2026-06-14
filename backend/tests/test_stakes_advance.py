"""Tests for the advancement-aware extension of ``compute_group_stakes``.

Two hand-built cutoffs pin the behaviour at both extremes:
  * an "easy" cutoff where every third qualifies → advancement == top-2 plus
    third place;
  * a "hard" cutoff where no third qualifies → advancement == top-2.

Backward compatibility (no cutoff → no advancement fields) is checked too, so
existing callers such as ``coast_for_match`` stay unaffected.
"""

import random

from app.services.qualification import ThirdPlaceCutoff
from app.services.stakes import compute_group_stakes

# Always-qualify: a single weak rival the candidate cannot fail to beat.
_EASY_CUTOFF = ThirdPlaceCutoff([{'A': (0, -99, 0)}])
# Never-qualify: 11 unbeatable rivals, so no realistic third gets drawn in.
_HARD_CUTOFF = ThirdPlaceCutoff(
    [{chr(65 + k): (9, 99, 99) for k in range(11)}]
)


def _group() -> tuple[list[dict], list[dict]]:
    """A fresh 4-team group with all six matches unplayed."""
    teams = [
        {'id': 1, 'name': 'Brazil', 'pts': 0, 'gd': 0, 'gf': 0, 'ppg': 1.5},
        {'id': 2, 'name': 'Morocco', 'pts': 0, 'gd': 0, 'gf': 0, 'ppg': 1.5},
        {'id': 3, 'name': 'Haiti', 'pts': 0, 'gd': 0, 'gf': 0, 'ppg': 1.5},
        {'id': 4, 'name': 'Scotland', 'pts': 0, 'gd': 0, 'gf': 0, 'ppg': 1.5},
    ]
    nm = {t['id']: t['name'] for t in teams}
    pairs = [(1, 2), (3, 4), (1, 3), (2, 4), (1, 4), (2, 3)]
    remaining = [
        {
            'matchId': i,
            'homeId': h,
            'awayId': a,
            'homeName': nm[h],
            'awayName': nm[a],
            'venue': None,
        }
        for i, (h, a) in enumerate(pairs)
    ]
    return teams, remaining


def test_no_cutoff_is_backward_compatible() -> None:
    """Without a cutoff the result carries no advancement fields."""
    # Arrange
    random.seed(0)
    teams, remaining = _group()

    # Act
    res = compute_group_stakes(teams, remaining, n_sims=200)

    # Assert
    team = res['teams'][0]
    assert 'pAdvance' not in team
    assert 'pTop2' in team
    assert 'swingAdvance' not in team['matches'][0]


def test_cutoff_adds_advancement_fields() -> None:
    """With a cutoff every team and match gains advancement metrics."""
    # Arrange
    random.seed(1)
    teams, remaining = _group()

    # Act
    res = compute_group_stakes(
        teams,
        remaining,
        n_sims=300,
        third_cutoff=_EASY_CUTOFF,
        group_letter='C',
    )

    # Assert
    team = res['teams'][0]
    assert 'pAdvance' in team
    match = team['matches'][0]
    for key in (
        'pAdvanceIfWin',
        'pAdvanceIfDraw',
        'pAdvanceIfLoss',
        'swingAdvance',
        'advanceLabel',
    ):
        assert key in match


def test_easy_cutoff_advance_equals_top2_plus_third() -> None:
    """If every third qualifies, advancing == top-2 OR third place."""
    # Arrange
    random.seed(2)
    teams, remaining = _group()

    # Act
    res = compute_group_stakes(
        teams,
        remaining,
        n_sims=400,
        third_cutoff=_EASY_CUTOFF,
        group_letter='C',
    )

    # Assert
    for team in res['teams']:
        expected = team['pTop2'] + team['pThird']
        assert abs(team['pAdvance'] - expected) <= 0.002


def test_hard_cutoff_advance_equals_top2() -> None:
    """If no third qualifies, advancing collapses to direct top-2."""
    # Arrange
    random.seed(3)
    teams, remaining = _group()

    # Act
    res = compute_group_stakes(
        teams,
        remaining,
        n_sims=400,
        third_cutoff=_HARD_CUTOFF,
        group_letter='C',
    )

    # Assert
    for team in res['teams']:
        assert team['pAdvance'] == team['pTop2']


def test_advance_never_below_top2() -> None:
    """Advancement is a superset of top-2, so pAdvance >= pTop2 always."""
    # Arrange
    random.seed(4)
    teams, remaining = _group()

    # Act
    res = compute_group_stakes(
        teams,
        remaining,
        n_sims=400,
        third_cutoff=_EASY_CUTOFF,
        group_letter='C',
    )

    # Assert (small tolerance for independent rounding of each field)
    for team in res['teams']:
        assert team['pAdvance'] + 0.001 >= team['pTop2']
