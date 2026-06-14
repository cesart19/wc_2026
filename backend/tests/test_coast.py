"""Tests for the advancement-aware coasting model (Phase 2).

The behavioural core (:func:`_coast_value`) is tested deterministically with
hand-built match-stakes dicts so the survival/seeding split is exact. A smoke
test wires :func:`coast_for_match` end to end through ``build_cutoff`` and the
stakes engine.
"""

import random

from pytest import approx

from app.services.qualification import build_cutoff
from app.services.stakes import (
    _COAST_SWING_REF,
    _SEEDING_RETENTION,
    _coast_value,
    coast_for_match,
)


def _match(label: str, swing_advance: float, swing_first: float) -> dict:
    """A minimal favourite's match-stakes dict for ``_coast_value``."""
    return {
        'advanceLabel': label,
        'swingAdvance': swing_advance,
        'swingFirst': swing_first,
    }


def test_live_for_advancement_does_not_coast() -> None:
    """PIVOTAL / LIVE / DOOMED matches yield zero coast."""
    for label in ('PIVOTAL', 'LIVE', 'DOOMED'):
        assert _coast_value(_match(label, 0.4, 0.0)) == 0.0


def test_fully_secured_coasts_completely() -> None:
    """Advancement locked and group win settled → maximal coast."""
    # Arrange / Act
    coast = _coast_value(_match('SECURED', 0.0, 0.0))

    # Assert
    assert coast == approx(1.0)


def test_survival_swing_scales_down_coast() -> None:
    """A half-reference advancement swing halves the coast."""
    # Arrange: swingAdvance = half of the reference.
    coast = _coast_value(_match('SECURED', _COAST_SWING_REF / 2, 0.0))

    # Assert
    assert coast == approx(0.5)


def test_partial_seeding_holds_back_some_intensity() -> None:
    """A settled-but-not-fixed group win damps via _SEEDING_RETENTION."""
    # Arrange: seed_live = 0.5 → coast = 1 * (1 - retention * 0.5).
    coast = _coast_value(_match('SECURED', 0.0, _COAST_SWING_REF / 2))

    # Assert
    assert coast == approx(1.0 - _SEEDING_RETENTION * 0.5)


def test_full_seeding_swing_clamps_retention() -> None:
    """A group win that fully swings caps the seeding hold-back at 1."""
    # Arrange: swingFirst beyond the reference → seed_live clamps to 1.
    coast = _coast_value(_match('SEEDING', 0.0, _COAST_SWING_REF * 2))

    # Assert
    assert coast == approx(1.0 - _SEEDING_RETENTION)


def test_coast_decreases_with_survival_swing() -> None:
    """More advancement at stake means less coasting (monotonic)."""
    # Arrange / Act
    low = _coast_value(_match('SECURED', 0.02, 0.0))
    high = _coast_value(_match('SECURED', 0.10, 0.0))

    # Assert
    assert 0.0 <= high < low <= 1.0


def _two_groups() -> list[dict]:
    """Two minimal groups of real teams, all matches unplayed."""

    def grp(name: str, ids_names: list[tuple[int, str]]) -> dict:
        teams = [
            {'id': i, 'name': n, 'pts': 0, 'gd': 0, 'gf': 0, 'ppg': 1.5}
            for i, n in ids_names
        ]
        a, b, c, d = (i for i, _ in ids_names)
        return {
            'name': name,
            'teams': teams,
            'remaining': [
                (a, b),
                (c, d),
                (a, c),
                (b, d),
                (a, d),
                (b, c),
            ],
        }

    return [
        grp(
            'X', [(1, 'Brazil'), (2, 'Morocco'), (3, 'Haiti'), (4, 'Scotland')]
        ),
        grp('Y', [(5, 'France'), (6, 'Senegal'), (7, 'Norway'), (8, 'Iraq')]),
    ]


def test_coast_for_match_smoke() -> None:
    """coast_for_match returns a well-formed verdict end to end."""
    # Arrange
    random.seed(0)
    groups = _two_groups()
    cutoff = build_cutoff(groups, n_sims=40)

    # Act
    result = coast_for_match(
        'Brazil', 'Morocco', groups, n_sims=200, third_cutoff=cutoff
    )

    # Assert
    assert result is not None
    coast, label, fav_is_home = result
    assert 0.0 <= coast <= 1.0
    assert label in {'SECURED', 'SEEDING', 'PIVOTAL', 'LIVE', 'DOOMED'}
    assert isinstance(fav_is_home, bool)


def test_coast_for_match_returns_none_off_group() -> None:
    """A pairing not contained in any group resolves to None."""
    # Arrange
    groups = _two_groups()

    # Act / Assert: Brazil (group X) vs France (group Y) share no group.
    assert coast_for_match('Brazil', 'France', groups) is None
