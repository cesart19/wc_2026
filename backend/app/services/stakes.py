"""Match-stakes engine — how pivotal each remaining group match is.

Foundation for the 'elite coasting' adjustment (Phase 1): before nudging a
favourite's effective strength down in a low-stakes match, we must MEASURE
the stakes rather than guess. For every remaining group match we Monte-Carlo
the rest of the group and compute, per team that plays it, the swing in its
qualification probability between winning and losing that match:

    swing_top2 = P(top 2 | team wins)  −  P(top 2 | team loses)

A near-zero swing with a high baseline P(top 2) means the team qualifies
almost regardless of the result — the structural pre-condition for coasting.
A near-zero swing with a low baseline means the team is already (almost)
eliminated. A large swing means the match is pivotal and intensity should be
full. ``swing_first`` does the same for winning the group (seeding stakes),
which can matter even once top-2 is secured (the bracket-avoidance angle).

The engine is pure: it takes already-parsed group state + remaining fixtures
and reuses the production goal sampler, so it runs offline (no live fetch).
Third-place qualification is cross-group (Annex C) and is NOT modelled here;
``p_top2`` is the direct-qualification probability, which is what matters for
elites (they rarely finish 3rd). ``p_third`` is reported for transparency.
"""

import random

from app.services.forecasting import _sim_group
from app.services.match_predictor import get_strength
from app.services.venues import get_venue

# swingTop2 at/above which a match is fully live (coast = 0). Below it, a
# SECURED/SEEDING favourite coasts proportionally (coast → 1 as swing → 0).
_COAST_SWING_REF: float = 0.15


def _rank(table: dict[int, list[float]], order: list[int]) -> list[int]:
    """Return team ids ranked by points, then GD, then GF (desc).

    ``order`` provides a stable, deterministic tiebreak for fully-equal rows
    (FIFA's later tiebreakers / draw of lots are out of scope for v1).
    """
    return sorted(
        order,
        key=lambda tid: (table[tid][0], table[tid][1], table[tid][2]),
        reverse=True,
    )


def compute_group_stakes(
    teams: list[dict],
    remaining: list[dict],
    n_sims: int = 20000,
) -> dict:
    """Monte-Carlo a group's remaining matches and score per-match stakes.

    Args:
        teams: One dict per team with keys ``id``, ``name``, ``pts``, ``gd``,
            ``gf``, ``ppg``. Current (post-played) standing.
        remaining: One dict per unplayed group match with keys ``matchId``,
            ``homeId``, ``awayId``, ``homeName``, ``awayName``, ``venue``.
        n_sims: Monte-Carlo iterations.

    Returns:
        Dict with per-team qualification probabilities and, for each team,
        the stakes of every remaining match it plays.
    """
    ids = [t['id'] for t in teams]
    name_of = {t['id']: t['name'] for t in teams}
    ppg_of = {t['id']: t['ppg'] for t in teams}
    base = {t['id']: [t['pts'], t['gd'], t['gf']] for t in teams}

    # Aggregates: overall placement counts, and per (match index, team id,
    # team-perspective outcome) the top-2 / first-place tallies.
    first = {tid: 0 for tid in ids}
    top2 = {tid: 0 for tid in ids}
    third = {tid: 0 for tid in ids}
    # bucket[(i, tid, outcome)] = [n, top2_count, first_count]
    bucket: dict[tuple[int, int, str], list[int]] = {}

    for _ in range(n_sims):
        table = {tid: list(base[tid]) for tid in ids}
        sim_out: list[str] = []
        for m in remaining:
            h, a = m['homeId'], m['awayId']
            pa, gda, gfa, pb, gdb, gfb = _sim_group(
                m['homeName'], m['awayName'],
                ppg_of[h], ppg_of[a], venue=m['venue'],
            )
            table[h][0] += pa
            table[h][1] += gda
            table[h][2] += gfa
            table[a][0] += pb
            table[a][1] += gdb
            table[a][2] += gfb
            sim_out.append('H' if pa == 3 else ('D' if pa == 1 else 'A'))

        ranked = _rank(table, ids)
        pos = {tid: i for i, tid in enumerate(ranked)}
        for tid in ids:
            if pos[tid] == 0:
                first[tid] += 1
            if pos[tid] <= 1:
                top2[tid] += 1
            if pos[tid] == 2:
                third[tid] += 1

        for i, m in enumerate(remaining):
            res = sim_out[i]
            for tid, won_char in ((m['homeId'], 'H'), (m['awayId'], 'A')):
                if res == 'D':
                    persp = 'D'
                elif res == won_char:
                    persp = 'W'
                else:
                    persp = 'L'
                b = bucket.setdefault((i, tid, persp), [0, 0, 0])
                b[0] += 1
                if pos[tid] <= 1:
                    b[1] += 1
                if pos[tid] == 0:
                    b[2] += 1

    def _cond(i: int, tid: int, persp: str, col: int) -> float | None:
        b = bucket.get((i, tid, persp))
        return b[col] / b[0] if b and b[0] else None

    out_teams = []
    for t in teams:
        tid = t['id']
        matches = []
        for i, m in enumerate(remaining):
            if tid not in (m['homeId'], m['awayId']):
                continue
            opp = name_of[m['awayId'] if tid == m['homeId'] else m['homeId']]
            p2_w = _cond(i, tid, 'W', 1)
            p2_l = _cond(i, tid, 'L', 1)
            p1_w = _cond(i, tid, 'W', 2)
            p1_l = _cond(i, tid, 'L', 2)
            swing_top2 = (
                (p2_w - p2_l) if p2_w is not None and p2_l is not None else 0.0
            )
            swing_first = (
                (p1_w - p1_l) if p1_w is not None and p1_l is not None else 0.0
            )
            stakes = swing_top2 + 0.5 * swing_first
            matches.append({
                'matchId': m['matchId'],
                'opponent': opp,
                'venue': m['venue'],
                'pTop2IfWin': round(p2_w, 3) if p2_w is not None else None,
                'pTop2IfLoss': round(p2_l, 3) if p2_l is not None else None,
                'swingTop2': round(swing_top2, 3),
                'swingFirst': round(swing_first, 3),
                'stakes': round(stakes, 3),
                'label': _label(top2[tid] / n_sims, swing_top2, swing_first),
            })
        out_teams.append({
            'id': tid,
            'name': t['name'],
            'pFirst': round(first[tid] / n_sims, 3),
            'pTop2': round(top2[tid] / n_sims, 3),
            'pThird': round(third[tid] / n_sims, 3),
            'matches': matches,
        })

    out_teams.sort(key=lambda x: x['pTop2'], reverse=True)
    return {'nSims': n_sims, 'teams': out_teams}


def _label(p_top2: float, swing_top2: float, swing_first: float) -> str:
    """Classify a match's stakes for a team.

    SECURED  — qualifies almost regardless (coast candidate, seeding aside).
    DOOMED   — almost eliminated regardless.
    PIVOTAL  — qualification hinges on this match.
    SEEDING  — top-2 safe but the group win (bracket path) still swings.
    LIVE     — in between.
    """
    if swing_top2 >= 0.15:
        return 'PIVOTAL'
    if p_top2 >= 0.90:
        return 'SEEDING' if swing_first >= 0.15 else 'SECURED'
    if p_top2 <= 0.10:
        return 'DOOMED'
    return 'LIVE'


def coast_for_match(
    home: str,
    away: str,
    groups: list[dict],
    n_sims: int = 8000,
) -> tuple[float, str, bool] | None:
    """Coasting intensity for the favourite of a group match.

    Args:
        home, away: Team names of the match to forecast.
        groups: Output of ``forecasting._build_groups`` — each with ``teams``
            (id/name/pts/gd/gf/ppg) and ``remaining`` as (home_id, away_id)
            tuples.
        n_sims: Monte-Carlo iterations (fewer than the report for live use).

    Returns:
        ``(coast, label, fav_is_home)`` where ``coast`` in [0, 1] is how
        secured the favourite is (0 if the match is still PIVOTAL/LIVE), or
        None if the group/match can't be resolved.
    """
    grp = next(
        (
            g for g in groups
            if {home, away} <= {t['name'] for t in g['teams']}
        ),
        None,
    )
    if grp is None or not grp.get('remaining'):
        return None

    name_of = {t['id']: t['name'] for t in grp['teams']}
    remaining = []
    for h_id, a_id in grp['remaining']:
        hn, an = name_of.get(h_id), name_of.get(a_id)
        if hn is None or an is None:
            continue
        remaining.append({
            'matchId': None,
            'homeId': h_id,
            'awayId': a_id,
            'homeName': hn,
            'awayName': an,
            'venue': get_venue(hn, an),
        })
    if not remaining:
        return None

    res = compute_group_stakes(grp['teams'], remaining, n_sims)

    fav_is_home = get_strength(home) >= get_strength(away)
    fav = home if fav_is_home else away
    opp = away if fav_is_home else home
    fav_row = next((t for t in res['teams'] if t['name'] == fav), None)
    if fav_row is None:
        return None
    m = next((x for x in fav_row['matches'] if x['opponent'] == opp), None)
    if m is None:
        return None

    if m['label'] not in ('SECURED', 'SEEDING'):
        return 0.0, m['label'], fav_is_home
    coast = max(0.0, 1.0 - m['swingTop2'] / _COAST_SWING_REF)
    return coast, m['label'], fav_is_home
