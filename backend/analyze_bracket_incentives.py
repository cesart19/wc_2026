"""Quantify the 'elite coasting + bracket avoidance' hypothesis.

Two structural questions about WC 2026 that a static-strength model ignores:

1. Coast-ability: how far ahead is each group's favourite of its remaining
   rivals? A big gap means the favourite can secure qualification at reduced
   intensity (the Brazil-vs-Morocco hypothesis), so its EFFECTIVE strength in
   low-stakes matches may be below its rating.
2. Bracket avoidance: the R32 pairings are FIXED by group-finish slot, so
   finishing 1st vs 2nd sends a team to a pre-known quadrant/half. We resolve
   the official tree (bracket.py) to map which group winners are destined for
   the same quadrant (meet in R16/QF) or half (meet in SF), and compute, per
   elite, whether finishing 2nd would DODGE other elites.

Read-only analysis. Run from backend/ with the venv active.
"""

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / '.env')

from app.services.bracket import KNOCKOUT_BRACKET  # noqa: E402
from app.services.match_predictor import get_strength  # noqa: E402

# Group composition (football-data names), from /standings.
GROUPS: dict[str, list[str]] = {
    'A': ['Mexico', 'South Korea', 'Czechia', 'South Africa'],
    'B': ['Bosnia-Herzegovina', 'Canada', 'Qatar', 'Switzerland'],
    'C': ['Brazil', 'Morocco', 'Haiti', 'Scotland'],
    'D': ['United States', 'Australia', 'Turkey', 'Paraguay'],
    'E': ['Curaçao', 'Germany', 'Ecuador', 'Ivory Coast'],
    'F': ['Japan', 'Netherlands', 'Sweden', 'Tunisia'],
    'G': ['Egypt', 'Belgium', 'Iran', 'New Zealand'],
    'H': ['Cape Verde Islands', 'Saudi Arabia', 'Spain', 'Uruguay'],
    'I': ['France', 'Iraq', 'Norway', 'Senegal'],
    'J': ['Algeria', 'Argentina', 'Jordan', 'Austria'],
    'K': ['Congo DR', 'Colombia', 'Portugal', 'Uzbekistan'],
    'L': ['England', 'Ghana', 'Croatia', 'Panama'],
}

SF_HALF = {537387: 'TOP', 537388: 'BOTTOM'}
QF_QUAD = {537383: 'Q1', 537384: 'Q2', 537385: 'Q3', 537386: 'Q4'}


def ranked(group: list[str]) -> list[tuple[str, float]]:
    """Teams of a group sorted by model strength (desc), scaled to 0-100."""
    return sorted(
        ((t, get_strength(t) * 100) for t in group),
        key=lambda x: x[1],
        reverse=True,
    )


def build_slot_location() -> dict[str, tuple[str, str]]:
    """Map every group slot (w_X / r_X) to its (half, quadrant).

    Walks the bracket bottom-up: each match feeding ``win_<id>`` is the
    parent of ``<id>``; climb R32→R16→QF→SF to read the half/quadrant.
    """
    parent: dict[int, int] = {}
    for mid, sides in KNOCKOUT_BRACKET.items():
        for slot in sides.values():
            if slot.startswith('win_'):
                parent[int(slot.split('_', 1)[1])] = mid

    location: dict[str, tuple[str, str]] = {}
    for mid, sides in KNOCKOUT_BRACKET.items():
        group_slots = [
            s for s in sides.values()
            if s.startswith(('w_', 'r_'))
        ]
        if not group_slots:
            continue  # not an R32 group-fed match
        r16 = parent[mid]
        qf = parent[r16]
        sf = parent[qf]
        loc = (SF_HALF[sf], QF_QUAD[qf])
        for s in group_slots:
            location[s] = loc
    return location


def main() -> None:
    """Print the coast-ability table and the bracket-collision analysis."""
    # Elite set: top 14 teams by model strength.
    all_teams = [(t, get_strength(t) * 100) for g in GROUPS.values() for t in g]
    elite_cut = sorted(all_teams, key=lambda x: x[1], reverse=True)[13][1]
    elites = {t for t, s in all_teams if s >= elite_cut}

    print('=' * 72)
    print('1) COAST-ABILITY — favourite margin per group (strength 0-100)')
    print('   gap12 = #1 − #2 (bigger → favourite can secure spot at low gas)')
    print('=' * 72)
    rows = []
    for g, teams in GROUPS.items():
        r = ranked(teams)
        gap12 = r[0][1] - r[1][1]
        weak2 = (r[2][1] + r[3][1]) / 2
        rows.append((gap12, g, r, weak2))
    for gap12, g, r, weak2 in sorted(rows, reverse=True):
        fav = r[0][0]
        star = '⭐' if fav in elites else '  '
        print(
            f'  {g} {star} fav={fav:<14} {r[0][1]:4.0f} | '
            f'2nd={r[1][0]:<13} {r[1][1]:4.0f} | gap12={gap12:5.1f} | '
            f'weak-2 avg={weak2:4.0f}'
        )

    loc = build_slot_location()
    # Chalk: winner = strongest, runner = 2nd strongest of each group.
    win_of = {g: ranked(t)[0][0] for g, t in GROUPS.items()}
    run_of = {g: ranked(t)[1][0] for g, t in GROUPS.items()}

    print('\n' + '=' * 72)
    print('2) BRACKET STRUCTURE — where each group WINNER lands (chalk seeds)')
    print('   elites sharing a quadrant meet R16/QF; sharing a half meet by SF')
    print('=' * 72)
    by_quad: dict[str, list[str]] = {}
    by_half: dict[str, list[str]] = {}
    for g in GROUPS:
        half, quad = loc[f'w_{g}']
        w = win_of[g]
        by_quad.setdefault(quad, []).append(f'{w}{"⭐" if w in elites else ""}')
        if w in elites:
            by_half.setdefault(half, []).append(w)
    for quad in ('Q1', 'Q2', 'Q3', 'Q4'):
        half = 'TOP' if quad in ('Q1', 'Q2') else 'BOTTOM'
        print(f'  {quad} ({half:<6}) winners: {", ".join(by_quad.get(quad, []))}')
    print()
    for half in ('TOP', 'BOTTOM'):
        es = by_half.get(half, [])
        print(f'  {half:<6} half — elite group-winners ({len(es)}): {", ".join(es)}')

    print('\n' + '=' * 72)
    print('3) AVOIDANCE — does finishing 2nd move an elite to a softer path?')
    print('=' * 72)
    for g in GROUPS:
        w = win_of[g]
        if w not in elites:
            continue
        h1, q1 = loc[f'w_{g}']
        h2, q2 = loc[f'r_{g}']
        # Elite winners sharing the WINNER's quadrant vs the RUNNER's quadrant.
        share_win = [
            win_of[gg] for gg in GROUPS
            if gg != g and win_of[gg] in elites and loc[f'w_{gg}'][1] == q1
        ]
        moved = 'SAME' if (h1, q1) == (h2, q2) else f'{q1}/{h1[:3]}→{q2}/{h2[:3]}'
        print(
            f'  {w:<13} win→{q1}/{h1[:3]}  '
            f'elite winners in that quad: {share_win if share_win else "—"}'
        )
        print(f'                 if 2nd→{q2}/{h2[:3]}   [{moved}]')


if __name__ == '__main__':
    main()
