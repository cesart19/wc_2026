"""Tests for the stakes surfacing helpers (Phase 3).

``build_group_state`` and ``_remaining_dicts`` are pure parsing and are
checked exactly. ``match_stakes`` and ``group_stakes_report`` are smoke-tested
end to end at small sim counts (real team names so the goal sampler resolves
strengths).
"""

import random

from app.services.stakes import (
    _remaining_dicts,
    build_group_state,
    group_stakes_report,
    match_stakes,
)

_LABELS = {'PIVOTAL', 'SECURED', 'SEEDING', 'LIVE', 'DOOMED'}


def _team(tid: int, name: str) -> dict:
    return {'id': tid, 'name': name}


def _match(
    mid: int,
    home: tuple[int, str],
    away: tuple[int, str],
    status: str,
    sh: int | None = None,
    sa: int | None = None,
) -> dict:
    return {
        'id': mid,
        'stage': 'GROUP_STAGE',
        'group': 'GROUP_Z',
        'homeTeam': _team(*home),
        'awayTeam': _team(*away),
        'status': status,
        'score': {'fullTime': {'home': sh, 'away': sa}},
    }


def _matches_raw() -> dict:
    """Group Z: Brazil beat Morocco 2-0; the other five are unplayed."""
    br, mo, ha, sc = (
        (1, 'Brazil'),
        (2, 'Morocco'),
        (3, 'Haiti'),
        (
            4,
            'Scotland',
        ),
    )
    return {
        'matches': [
            _match(1, br, mo, 'FINISHED', 2, 0),
            _match(2, ha, sc, 'TIMED'),
            _match(3, br, ha, 'TIMED'),
            _match(4, mo, sc, 'TIMED'),
            _match(5, br, sc, 'TIMED'),
            _match(6, mo, ha, 'TIMED'),
        ]
    }


def test_build_group_state_folds_results() -> None:
    """A finished match feeds points/GD/GF; the rest become remaining."""
    # Arrange / Act
    groups = build_group_state(_matches_raw())

    # Assert
    assert len(groups) == 1
    grp = groups[0]
    assert grp['name'] == 'Z'
    by_name = {t['name']: t for t in grp['teams']}

    assert by_name['Brazil']['pts'] == 3
    assert by_name['Brazil']['gd'] == 2
    assert by_name['Brazil']['gf'] == 2
    assert by_name['Brazil']['ppg'] == 3.0

    assert by_name['Morocco']['pts'] == 0
    assert by_name['Morocco']['gd'] == -2

    # Unplayed teams keep the neutral prior.
    assert by_name['Haiti']['played'] == 0
    assert by_name['Haiti']['ppg'] == 1.5

    # The finished match is excluded from remaining; the five others remain.
    assert (1, 2) not in grp['remaining']
    assert len(grp['remaining']) == 5


def test_remaining_dicts_shape() -> None:
    """Remaining tuples expand to the compute_group_stakes dict shape."""
    # Arrange
    grp = build_group_state(_matches_raw())[0]

    # Act
    dicts = _remaining_dicts(grp)

    # Assert
    assert len(dicts) == 5
    sample = dicts[0]
    assert set(sample) == {
        'matchId',
        'homeId',
        'awayId',
        'homeName',
        'awayName',
        'venue',
    }


def test_match_stakes_returns_both_teams() -> None:
    """match_stakes yields an advancement view for each side of the match."""
    # Arrange
    random.seed(0)

    # Act
    res = match_stakes(
        'Brazil', 'Haiti', _matches_raw(), n_sims=200, cutoff_sims=20
    )

    # Assert
    assert res is not None
    assert set(res) == {'Brazil', 'Haiti'}
    assert res['Brazil']['advanceLabel'] in _LABELS
    assert 0.0 <= res['Brazil']['pAdvance'] <= 1.0


def test_match_stakes_none_for_played_or_offgroup() -> None:
    """A finished match, or a cross-group pair, resolves to None."""
    # Arrange
    raw = _matches_raw()

    # Act / Assert: Brazil-Morocco already played; France isn't in the group.
    assert match_stakes('Brazil', 'Morocco', raw, cutoff_sims=20) is None
    assert match_stakes('Brazil', 'France', raw, cutoff_sims=20) is None


def test_group_stakes_report_structure() -> None:
    """The report carries the cutoff size and per-group stakes."""
    # Arrange
    random.seed(1)

    # Act
    report = group_stakes_report(_matches_raw(), n_sims=200, cutoff_sims=25)

    # Assert
    assert report['cutoffWorlds'] == 25
    assert set(report['groups']) == {'Z'}
    assert report['groups']['Z']['teams']


def test_group_stakes_report_filters_by_group() -> None:
    """An unknown group letter yields an empty group map."""
    # Arrange / Act
    report = group_stakes_report(
        _matches_raw(), group='A', n_sims=200, cutoff_sims=20
    )

    # Assert
    assert report['groups'] == {}
