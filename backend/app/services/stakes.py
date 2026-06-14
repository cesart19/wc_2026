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

Third-place qualification is cross-group (Annex C). Pass a ``third_cutoff``
(see :mod:`app.services.qualification`) to ``compute_group_stakes`` and the
engine additionally reports *advancement* — top-2 OR best-third — via
``pAdvance`` / ``swingAdvance`` / ``pAdvanceIfDraw``. This matters because 8
of 12 thirds advance: a team "fighting for 2nd" (high ``swingTop2``) can be
near-locked to advance (``swingAdvance`` ≈ 0), so its true survival stakes —
as opposed to its seeding stakes — are low. Without a cutoff the engine
behaves as before (top-2 only): ``p_top2`` is the direct-qualification
probability and ``p_third`` is reported for transparency.
"""

from app.services.forecasting import _sim_group
from app.services.match_predictor import get_strength
from app.services.qualification import ThirdPlaceCutoff, build_cutoff
from app.services.venues import get_venue

# swingAdvance at/above which a match is fully live (coast = 0): below it, an
# advancement-SECURED/SEEDING favourite coasts proportionally (coast → 1 as
# the swing → 0). The same scale is reused for the seeding (group-win) swing.
_COAST_SWING_REF: float = 0.15

# How much an unsettled group win (seeding) holds back coasting, in [0, 1]:
# 1.0 = a side chasing top spot plays full intensity; 0.0 = seeding ignored.
# Behavioural and unvalidated — a tunable knob, not a measured constant.
_SEEDING_RETENTION: float = 0.5

# Simulations used to build the best-thirds cutoff when one isn't supplied.
_CUTOFF_SIMS: int = 2000


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


def _apply_result(
    teams: dict[int, dict], home_id: int, away_id: int, gh: int, ga: int
) -> None:
    """Fold one finished result into the running standings table."""
    h, a = teams[home_id], teams[away_id]
    h['gf'] += gh
    h['gd'] += gh - ga
    h['played'] += 1
    a['gf'] += ga
    a['gd'] += ga - gh
    a['played'] += 1
    h['pts'] += 3 if gh > ga else (1 if gh == ga else 0)
    a['pts'] += 3 if ga > gh else (1 if gh == ga else 0)


def build_group_state(matches_raw: dict) -> list[dict]:
    """Build per-group state from a fixtures feed, folding in results.

    Unlike ``forecasting._build_groups_from_fixtures`` (which zeroes the
    table), this counts FINISHED matches into points/GD/GF so stakes reflect
    the live standings. Output is the ``forecasting._build_groups`` shape:
    ``teams`` with id/name/pts/gd/gf/ppg and ``remaining`` as (home_id,
    away_id) tuples.

    Args:
        matches_raw: The ``football_api.get_matches`` payload (football-data
            ``{matches: [...]}`` format).
    """
    groups: dict[str, dict] = {}
    for m in matches_raw.get('matches', []):
        if m.get('stage') != 'GROUP_STAGE':
            continue
        letter = m.get('group', '').replace('GROUP_', '') or '?'
        grp = groups.setdefault(letter, {'teams': {}, 'remaining': []})
        home, away = m['homeTeam'], m['awayTeam']
        for side in (home, away):
            grp['teams'].setdefault(
                side['id'],
                {
                    'id': side['id'],
                    'name': side.get('name', 'TBD'),
                    'pts': 0,
                    'gd': 0,
                    'gf': 0,
                    'played': 0,
                },
            )
        ft = m.get('score', {}).get('fullTime', {})
        if m.get('status') == 'FINISHED' and ft.get('home') is not None:
            _apply_result(
                grp['teams'], home['id'], away['id'], ft['home'], ft['away']
            )
        else:
            grp['remaining'].append((home['id'], away['id']))

    out = []
    for letter, grp in sorted(groups.items()):
        for t in grp['teams'].values():
            t['ppg'] = t['pts'] / t['played'] if t['played'] else 1.5
        out.append(
            {
                'name': letter,
                'teams': list(grp['teams'].values()),
                'remaining': grp['remaining'],
            }
        )
    return out


def _remaining_dicts(grp: dict) -> list[dict]:
    """Convert a group's (home_id, away_id) tuples to match-stake dicts."""
    name_of = {t['id']: t['name'] for t in grp['teams']}
    out = []
    for h_id, a_id in grp['remaining']:
        hn, an = name_of.get(h_id), name_of.get(a_id)
        if hn is None or an is None:
            continue
        out.append(
            {
                'matchId': None,
                'homeId': h_id,
                'awayId': a_id,
                'homeName': hn,
                'awayName': an,
                'venue': get_venue(hn, an),
            }
        )
    return out


def compute_group_stakes(
    teams: list[dict],
    remaining: list[dict],
    n_sims: int = 20000,
    third_cutoff: ThirdPlaceCutoff | None = None,
    group_letter: str | None = None,
) -> dict:
    # A tight Monte-Carlo kernel: the many accumulators (per-team placement
    # tallies + per-(match, team, outcome) buckets) are inherent; splitting
    # the hot loop into helpers would hurt clarity and speed.
    # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    """Monte-Carlo a group's remaining matches and score per-match stakes.

    Args:
        teams: One dict per team with keys ``id``, ``name``, ``pts``, ``gd``,
            ``gf``, ``ppg``. Current (post-played) standing.
        remaining: One dict per unplayed group match with keys ``matchId``,
            ``homeId``, ``awayId``, ``homeName``, ``awayName``, ``venue``.
        n_sims: Monte-Carlo iterations.
        third_cutoff: Optional cross-group best-thirds model. When supplied,
            the result gains advancement (top-2 OR best-third) metrics:
            per-team ``pAdvance`` and per-match ``swingAdvance`` /
            ``pAdvanceIfDraw`` / ``advanceLabel``. When ``None`` the function
            behaves exactly as before (top-2 stakes only) -- so existing
            callers are unaffected.
        group_letter: This group's letter, used to drop the focal group from
            the cutoff so a third competes against the other 11 only. Ignored
            when ``third_cutoff`` is ``None``.

    Returns:
        Dict with per-team qualification probabilities and, for each team,
        the stakes of every remaining match it plays.
    """
    track_adv = third_cutoff is not None
    ids = [t['id'] for t in teams]
    name_of = {t['id']: t['name'] for t in teams}
    ppg_of = {t['id']: t['ppg'] for t in teams}
    base = {t['id']: [t['pts'], t['gd'], t['gf']] for t in teams}

    # Aggregates: overall placement counts, and per (match index, team id,
    # team-perspective outcome) the top-2 / first-place tallies.
    first = {tid: 0 for tid in ids}
    top2 = {tid: 0 for tid in ids}
    third = {tid: 0 for tid in ids}
    advance = {tid: 0 for tid in ids}
    # bucket[(i, tid, outcome)] = [n, top2_count, first_count, advance_count]
    bucket: dict[tuple[int, int, str], list[int]] = {}

    for _ in range(n_sims):
        table = {tid: list(base[tid]) for tid in ids}
        sim_out: list[str] = []
        for m in remaining:
            h, a = m['homeId'], m['awayId']
            pa, gda, gfa, pb, gdb, gfb = _sim_group(
                m['homeName'],
                m['awayName'],
                ppg_of[h],
                ppg_of[a],
                venue=m['venue'],
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

        # Does this world's third-placed team clear the best-thirds line?
        third_qualifies = False
        if track_adv and len(ranked) >= 3:
            line = table[ranked[2]]
            third_qualifies = third_cutoff.advances_sample(
                (line[0], line[1], line[2]), exclude_group=group_letter
            )
        advanced = {
            tid: pos[tid] <= 1 or (pos[tid] == 2 and third_qualifies)
            for tid in ids
        }

        for tid in ids:
            if pos[tid] == 0:
                first[tid] += 1
            if pos[tid] <= 1:
                top2[tid] += 1
            if pos[tid] == 2:
                third[tid] += 1
            if advanced[tid]:
                advance[tid] += 1

        for i, m in enumerate(remaining):
            res = sim_out[i]
            for tid, won_char in ((m['homeId'], 'H'), (m['awayId'], 'A')):
                if res == 'D':
                    persp = 'D'
                elif res == won_char:
                    persp = 'W'
                else:
                    persp = 'L'
                b = bucket.setdefault((i, tid, persp), [0, 0, 0, 0])
                b[0] += 1
                if pos[tid] <= 1:
                    b[1] += 1
                if pos[tid] == 0:
                    b[2] += 1
                if advanced[tid]:
                    b[3] += 1

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
            match_entry = {
                'matchId': m['matchId'],
                'opponent': opp,
                'venue': m['venue'],
                'pTop2IfWin': round(p2_w, 3) if p2_w is not None else None,
                'pTop2IfLoss': round(p2_l, 3) if p2_l is not None else None,
                'swingTop2': round(swing_top2, 3),
                'swingFirst': round(swing_first, 3),
                'stakes': round(stakes, 3),
                'label': _label(top2[tid] / n_sims, swing_top2, swing_first),
            }
            if track_adv:
                pa_w = _cond(i, tid, 'W', 3)
                pa_d = _cond(i, tid, 'D', 3)
                pa_l = _cond(i, tid, 'L', 3)
                swing_adv = (
                    (pa_w - pa_l)
                    if pa_w is not None and pa_l is not None
                    else 0.0
                )
                match_entry.update(
                    {
                        'pAdvanceIfWin': (
                            round(pa_w, 3) if pa_w is not None else None
                        ),
                        'pAdvanceIfDraw': (
                            round(pa_d, 3) if pa_d is not None else None
                        ),
                        'pAdvanceIfLoss': (
                            round(pa_l, 3) if pa_l is not None else None
                        ),
                        'swingAdvance': round(swing_adv, 3),
                        'advanceLabel': _advance_label(
                            advance[tid] / n_sims, swing_adv, swing_first
                        ),
                    }
                )
            matches.append(match_entry)
        team_entry = {
            'id': tid,
            'name': t['name'],
            'pFirst': round(first[tid] / n_sims, 3),
            'pTop2': round(top2[tid] / n_sims, 3),
            'pThird': round(third[tid] / n_sims, 3),
            'matches': matches,
        }
        if track_adv:
            team_entry['pAdvance'] = round(advance[tid] / n_sims, 3)
        out_teams.append(team_entry)

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


def _advance_label(
    p_advance: float, swing_advance: float, swing_first: float
) -> str:
    """Classify a match by advancement (top-2 OR best-third) stakes.

    Advancement-aware twin of :func:`_label`. The key refinement: a favourite
    secured to advance even via the best-thirds path is a coast candidate,
    distinct from one whose qualification still hinges on the result -- a
    distinction ``swingTop2`` alone misses when 8 of 12 thirds advance.

    PIVOTAL — advancement swings on this match (intensity should be full).
    SECURED — advances almost regardless and the group win is settled too.
    SEEDING — advancement safe, but the group-win (bracket path) still swings.
    DOOMED  — almost out regardless.
    LIVE    — in between.
    """
    if swing_advance >= 0.15:
        return 'PIVOTAL'
    if p_advance >= 0.90:
        return 'SEEDING' if swing_first >= 0.15 else 'SECURED'
    if p_advance <= 0.10:
        return 'DOOMED'
    return 'LIVE'


def _coast_value(match: dict) -> float:
    """Coast intensity in [0, 1] for an advancement-secured favourite.

    Splits the two reasons a secured side eases off:
      * survival — advancement is locked, so the result barely moves it
        (``swingAdvance`` ≈ 0 → ``surv`` ≈ 1);
      * seeding — if the group win still swings (``swingFirst`` high), the
        bracket-avoidance incentive holds intensity back, scaled by
        ``_SEEDING_RETENTION``.

    Returns 0.0 for any match still live for advancement (PIVOTAL / LIVE /
    DOOMED): a side not yet through, or already out, does not coast.
    """
    if match['advanceLabel'] not in ('SECURED', 'SEEDING'):
        return 0.0
    surv = max(0.0, 1.0 - match['swingAdvance'] / _COAST_SWING_REF)
    seed_live = min(1.0, abs(match['swingFirst']) / _COAST_SWING_REF)
    return surv * (1.0 - _SEEDING_RETENTION * seed_live)


def coast_for_match(
    home: str,
    away: str,
    groups: list[dict],
    n_sims: int = 8000,
    third_cutoff: ThirdPlaceCutoff | None = None,
) -> tuple[float, str, bool] | None:
    # pylint: disable=too-many-locals
    """Coasting intensity for the favourite of a group match.

    Advancement-aware: a side already through (top-2 OR best-third) eases off
    even when its top-2 finish is contested, while one still fighting to
    advance plays full intensity. See :func:`_coast_value` for the
    survival/seeding split.

    No feedback loop: the stakes simulation here calls the predictor WITHOUT
    the coasting damp (the damp lives in the route, post-prediction, via
    ``match_predictor.apply_coast_damp``). Keep it that way — applying the damp
    inside ``predict`` / ``_sim_group`` would make this recurse.

    Args:
        home, away: Team names of the match to forecast.
        groups: Output of ``forecasting._build_groups`` — each with ``teams``
            (id/name/pts/gd/gf/ppg) and ``remaining`` as (home_id, away_id)
            tuples. Pass ALL groups so the best-thirds cutoff is accurate.
        n_sims: Monte-Carlo iterations (fewer than the report for live use).
        third_cutoff: Prebuilt best-thirds cutoff; built from ``groups`` when
            omitted. Cache and reuse it across calls before enabling the damp,
            as building runs a full group-stage simulation.

    Returns:
        ``(coast, advance_label, fav_is_home)`` where ``coast`` in [0, 1] is
        how secured-and-idle the favourite is (0 if still live to advance), or
        None if the group/match can't be resolved.
    """
    grp = next(
        (g for g in groups if {home, away} <= {t['name'] for t in g['teams']}),
        None,
    )
    if grp is None or not grp.get('remaining'):
        return None

    remaining = _remaining_dicts(grp)
    if not remaining:
        return None

    cutoff = third_cutoff or build_cutoff(groups, _CUTOFF_SIMS)
    res = compute_group_stakes(
        grp['teams'],
        remaining,
        n_sims,
        third_cutoff=cutoff,
        group_letter=grp['name'],
    )

    fav_is_home = get_strength(home) >= get_strength(away)
    fav = home if fav_is_home else away
    opp = away if fav_is_home else home
    fav_row = next((t for t in res['teams'] if t['name'] == fav), None)
    if fav_row is None:
        return None
    m = next((x for x in fav_row['matches'] if x['opponent'] == opp), None)
    if m is None:
        return None

    return _coast_value(m), m['advanceLabel'], fav_is_home


def _match_view(res: dict, team: str, opp: str) -> dict | None:
    """Pull one team's stakes for a single opponent out of a group result."""
    row = next((t for t in res['teams'] if t['name'] == team), None)
    if row is None:
        return None
    m = next((x for x in row['matches'] if x['opponent'] == opp), None)
    if m is None:
        return None
    return {
        'pTop2': row['pTop2'],
        'pAdvance': row.get('pAdvance'),
        'advanceLabel': m.get('advanceLabel'),
        'swingTop2': m['swingTop2'],
        'swingAdvance': m.get('swingAdvance'),
        'pAdvanceIfWin': m.get('pAdvanceIfWin'),
        'pAdvanceIfDraw': m.get('pAdvanceIfDraw'),
        'pAdvanceIfLoss': m.get('pAdvanceIfLoss'),
    }


def match_stakes(
    home: str,
    away: str,
    matches_raw: dict,
    n_sims: int = 8000,
    cutoff_sims: int = _CUTOFF_SIMS,
) -> dict | None:
    """Advancement stakes of one group match, from each team's view.

    Builds live group state from ``matches_raw``, simulates the focal group
    against an all-groups best-thirds cutoff, and returns each team's
    advancement label and swings for this fixture.

    Returns:
        ``{team_name: {...}}`` for ``home`` and ``away``, or None if the pair
        isn't an unplayed group match in the current state.
    """
    groups = build_group_state(matches_raw)
    grp = next(
        (g for g in groups if {home, away} <= {t['name'] for t in g['teams']}),
        None,
    )
    if grp is None or not grp.get('remaining'):
        return None
    remaining = _remaining_dicts(grp)
    if not any(
        {r['homeName'], r['awayName']} == {home, away} for r in remaining
    ):
        return None  # already played, or not scheduled

    cutoff = build_cutoff(groups, cutoff_sims)
    res = compute_group_stakes(
        grp['teams'],
        remaining,
        n_sims,
        third_cutoff=cutoff,
        group_letter=grp['name'],
    )
    out: dict = {}
    for team, opp in ((home, away), (away, home)):
        view = _match_view(res, team, opp)
        if view is not None:
            out[team] = view
    return out or None


def group_stakes_report(
    matches_raw: dict,
    group: str | None = None,
    n_sims: int = 8000,
    cutoff_sims: int = _CUTOFF_SIMS,
) -> dict:
    """Advancement-aware stakes for every remaining group match.

    Builds live group state, a single all-groups best-thirds cutoff, then runs
    the stakes engine per group.

    Args:
        matches_raw: The ``football_api.get_matches`` payload.
        group: Optional group letter (A-L) to restrict the report; all groups
            when omitted. The cutoff is always built from every group.
        n_sims: Monte-Carlo iterations per group.
        cutoff_sims: Simulations for the shared best-thirds cutoff.

    Returns:
        ``{cutoffWorlds, groups: {letter: compute_group_stakes(...)}}``.
    """
    groups = [g for g in build_group_state(matches_raw) if g['remaining']]
    if not groups:
        return {'cutoffWorlds': 0, 'groups': {}}
    cutoff = build_cutoff(groups, cutoff_sims)
    wanted = group.upper() if group else None
    out = {}
    for g in groups:
        if wanted and g['name'] != wanted:
            continue
        out[g['name']] = compute_group_stakes(
            g['teams'],
            _remaining_dicts(g),
            n_sims,
            third_cutoff=cutoff,
            group_letter=g['name'],
        )
    return {'cutoffWorlds': len(cutoff), 'groups': out}
