"""Tests for the cross-group third-place qualification model.

The ranking logic (:class:`ThirdPlaceCutoff`) is tested deterministically
with hand-built worlds so the boundary behaviour is exact and independent of
the goal sampler. A separate smoke test exercises :func:`build_cutoff` end to
end against the production simulator.
"""

import random

from app.services.qualification import (
    THIRDS_ADVANCING,
    ThirdPlaceCutoff,
    build_cutoff,
)

# One world with 9 thirds in strict descending order. The 8th-best line is
# H = (2, 0, 0): a candidate must clear it to be drawn in.
_WORLD = {
    'A': (7, 0, 0),
    'B': (6, 0, 0),
    'C': (5, 0, 0),
    'D': (4, 0, 0),
    'E': (4, 0, 0),
    'F': (3, 0, 0),
    'G': (3, 0, 0),
    'H': (2, 0, 0),
    'I': (1, 0, 0),
}


def test_eight_thirds_advance_constant() -> None:
    """The model encodes the WC 2026 rule of 8 advancing thirds."""
    assert THIRDS_ADVANCING == 8


def test_candidate_above_the_line_qualifies() -> None:
    """A third ranked at the 8th line is drawn in (prob 1.0)."""
    # Arrange
    cutoff = ThirdPlaceCutoff([_WORLD])

    # Act / Assert: (2, 0, 0) has exactly 7 thirds strictly above it.
    assert cutoff.advance_prob((2, 0, 0)) == 1.0


def test_candidate_below_the_line_is_eliminated() -> None:
    """A third with 8 teams above it misses the cut (prob 0.0)."""
    # Arrange
    cutoff = ThirdPlaceCutoff([_WORLD])

    # Act / Assert: (1, 0, 0) has 8 thirds strictly above it.
    assert cutoff.advance_prob((1, 0, 0)) == 0.0


def test_exclude_group_drops_a_rival() -> None:
    """Excluding the candidate's own group frees one slot above it."""
    # Arrange
    cutoff = ThirdPlaceCutoff([_WORLD])

    # Act: (1, 0, 0) fails outright but qualifies once strong 'A' is dropped.
    without_exclude = cutoff.advance_prob((1, 0, 0))
    excluding_a = cutoff.advance_prob((1, 0, 0), exclude_group='A')

    # Assert
    assert without_exclude == 0.0
    assert excluding_a == 1.0


def test_goal_difference_breaks_point_ties() -> None:
    """Equal points fall back to GD, then GF, lexicographically."""
    # Arrange: a crowded world of eight thirds level on points and GF.
    crowded = {f'G{i}': (3, 9, 9) for i in range(8)}
    crowded_cutoff = ThirdPlaceCutoff([crowded])

    # Act / Assert: equal stats are drawn in (ties favour candidate); a
    # strictly worse goal difference with 8 above it is not.
    assert crowded_cutoff.advance_prob((3, 9, 9)) == 1.0
    assert crowded_cutoff.advance_prob((3, 8, 9)) == 0.0


def test_advances_sample_is_deterministic_with_one_world() -> None:
    """A single-world cutoff makes the sampled draw deterministic."""
    # Arrange
    cutoff = ThirdPlaceCutoff([_WORLD])
    rng = random.Random(0)

    # Act / Assert
    assert cutoff.advances_sample((2, 0, 0), None, rng) is True
    assert cutoff.advances_sample((1, 0, 0), None, rng) is False


def test_empty_cutoff_never_advances() -> None:
    """With no sampled worlds the cutoff degrades safely to 'out'."""
    # Arrange
    cutoff = ThirdPlaceCutoff([])

    # Act / Assert
    assert cutoff.advance_prob((9, 9, 9)) == 0.0
    assert cutoff.advances_sample((9, 9, 9), None) is False


def test_build_cutoff_smoke() -> None:
    """build_cutoff runs against the real sampler and yields valid probs."""
    # Arrange: two minimal groups of real teams, all matches unplayed.
    random.seed(0)
    groups = [
        {
            'name': 'X',
            'teams': [
                {
                    'id': 1,
                    'name': 'Brazil',
                    'pts': 0,
                    'gd': 0,
                    'gf': 0,
                    'ppg': 1.5,
                },
                {
                    'id': 2,
                    'name': 'Morocco',
                    'pts': 0,
                    'gd': 0,
                    'gf': 0,
                    'ppg': 1.5,
                },
                {
                    'id': 3,
                    'name': 'Haiti',
                    'pts': 0,
                    'gd': 0,
                    'gf': 0,
                    'ppg': 1.5,
                },
                {
                    'id': 4,
                    'name': 'Scotland',
                    'pts': 0,
                    'gd': 0,
                    'gf': 0,
                    'ppg': 1.5,
                },
            ],
            'remaining': [(1, 2), (3, 4), (1, 3), (2, 4), (1, 4), (2, 3)],
        },
        {
            'name': 'Y',
            'teams': [
                {
                    'id': 5,
                    'name': 'France',
                    'pts': 0,
                    'gd': 0,
                    'gf': 0,
                    'ppg': 1.5,
                },
                {
                    'id': 6,
                    'name': 'Senegal',
                    'pts': 0,
                    'gd': 0,
                    'gf': 0,
                    'ppg': 1.5,
                },
                {
                    'id': 7,
                    'name': 'Norway',
                    'pts': 0,
                    'gd': 0,
                    'gf': 0,
                    'ppg': 1.5,
                },
                {
                    'id': 8,
                    'name': 'Iraq',
                    'pts': 0,
                    'gd': 0,
                    'gf': 0,
                    'ppg': 1.5,
                },
            ],
            'remaining': [(5, 6), (7, 8), (5, 7), (6, 8), (5, 8), (6, 7)],
        },
    ]

    # Act
    cutoff = build_cutoff(groups, n_sims=40)

    # Assert
    assert len(cutoff) == 40
    prob = cutoff.advance_prob((3, 0, 0), exclude_group='X')
    assert 0.0 <= prob <= 1.0
