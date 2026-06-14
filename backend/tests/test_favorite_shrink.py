"""Tests for the always-on favourite-shrink calibration layer.

:func:`apply_favorite_shrink` recalibrates the final W/D/L by moving a bounded
fraction of an over-confident favourite's win mass toward draw + underdog. The
cases below pin the four invariants the layer must hold — identity below the
anchor, mass conservation, the favourite staying the most likely outcome, and
the draw-dominant / cap / knockout behaviour — with hand-computed expectations.
"""

from pytest import approx

from app.services.match_predictor import (
    _FAV_SHRINK_ANCHOR,
    _FAV_SHRINK_CAP,
    _FAV_SHRINK_TO_DRAW,
    apply_favorite_shrink,
)


def test_at_or_below_anchor_is_identity() -> None:
    """A favourite at/below the parity anchor is left untouched."""
    # Arrange: home favourite exactly at the anchor → zero excess.
    probs = (_FAV_SHRINK_ANCHOR, 0.25, 1.0 - _FAV_SHRINK_ANCHOR - 0.25)

    # Act / Assert: same object returned, no mass moved.
    assert apply_favorite_shrink(probs) == probs


def test_mass_is_conserved() -> None:
    """The recalibrated probabilities still sum to 1.0."""
    # Arrange / Act
    out = apply_favorite_shrink((0.75, 0.10, 0.15))

    # Assert
    assert sum(out) == approx(1.0)


def test_favourite_stays_the_most_likely_outcome() -> None:
    """The cap guarantees the favourite remains the maximum after shrinking."""
    # Arrange / Act: a heavy favourite where the move binds on the cap.
    home, draw, away = apply_favorite_shrink((0.90, 0.04, 0.06))

    # Assert
    assert home > draw and home > away


def test_shifts_toward_draw_and_underdog() -> None:
    """Win mass drops; both draw and underdog gain (draw more, split 0.7)."""
    # Arrange
    p_home, p_draw, p_away = 0.75, 0.10, 0.15

    # Act
    home, draw, away = apply_favorite_shrink((p_home, p_draw, p_away))

    # Assert: favourite shrinks, others grow, draw gains the larger share.
    assert home < p_home
    assert draw > p_draw and away > p_away
    assert (draw - p_draw) > (away - p_away)
    assert (draw - p_draw) == approx(
        (away - p_away) * _FAV_SHRINK_TO_DRAW / (1.0 - _FAV_SHRINK_TO_DRAW)
    )


def test_cap_bounds_the_move() -> None:
    """Beyond the cap, the move equals exactly p_fav * _FAV_SHRINK_CAP."""
    # Arrange: excess large enough that lambda * excess exceeds the cap.
    p_home = 0.95

    # Act
    home, _, _ = apply_favorite_shrink((p_home, 0.02, 0.03))

    # Assert
    assert home == approx(p_home * (1.0 - _FAV_SHRINK_CAP))


def test_knockout_routes_all_mass_to_underdog() -> None:
    """With no draw, the shifted mass goes entirely to the underdog."""
    # Arrange / Act
    home, draw, away = apply_favorite_shrink(
        (0.75, 0.0, 0.25), is_knockout=True
    )

    # Assert: draw stays at zero, underdog absorbs the full move.
    assert draw == approx(0.0)
    assert away > 0.25
    assert sum((home, draw, away)) == approx(1.0)


def test_away_favourite_is_handled_symmetrically() -> None:
    """An away favourite shrinks just like a home one (mirror image)."""
    # Arrange / Act: away side is the favourite.
    home, draw, away = apply_favorite_shrink((0.15, 0.10, 0.75))

    # Assert
    assert away < 0.75
    assert away > home and away > draw
    assert sum((home, draw, away)) == approx(1.0)


def test_move_grows_with_favourite_strength() -> None:
    """Below the cap, a heavier favourite loses more win mass (monotonic)."""
    # Arrange / Act
    drop_low = 0.60 - apply_favorite_shrink((0.60, 0.20, 0.20))[0]
    drop_high = 0.65 - apply_favorite_shrink((0.65, 0.175, 0.175))[0]

    # Assert
    assert 0.0 < drop_low < drop_high
