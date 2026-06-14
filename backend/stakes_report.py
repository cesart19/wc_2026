"""CLI: report per-match stakes for every group (or one team/group).

Builds group state from a ``{standings, fixtures}`` snapshot (the backend /
MCP shape) and runs the Monte-Carlo stakes engine. Reads the snapshot from
``--data <file>``; if omitted, tries the running backend on localhost:8000.

Usage (from backend/, venv active):
  python stakes_report.py --data /tmp/wc_state.json
  python stakes_report.py --data /tmp/wc_state.json --group C
  python stakes_report.py --data /tmp/wc_state.json --team Brazil --sims 40000
"""

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / '.env')

from app.services.stakes import compute_group_stakes  # noqa: E402

BACKEND = 'http://localhost:8000'


def _letter(raw: str) -> str:
    """Normalize 'Group C' / 'GROUP_C' / 'C' to the bare letter."""
    return raw.replace('GROUP_', '').replace('Group ', '').strip()


def _load_snapshot(path: str | None) -> tuple[list, list]:
    """Return (standings, fixtures) from a file or the running backend."""
    if path:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        return data['standings'], data['fixtures']
    import httpx

    standings = httpx.get(f'{BACKEND}/groups', timeout=10).json()
    fixtures = httpx.get(f'{BACKEND}/fixtures', timeout=10).json()
    if not isinstance(fixtures, list):
        raise RuntimeError(f'backend /fixtures returned: {fixtures}')
    return standings, fixtures


def _build_groups(standings: list, fixtures: list) -> dict[str, dict]:
    """Assemble per-group {teams, remaining} from the snapshot."""
    groups: dict[str, dict] = {}
    for g in standings:
        letter = _letter(g['group'])
        teams = []
        for r in g['table']:
            played = r['played']
            teams.append({
                'id': r['teamId'],
                'name': r['team'],
                'pts': r['points'],
                'gd': r['gd'],
                'gf': r['gf'],
                'ppg': r['points'] / played if played else 1.5,
            })
        groups[letter] = {'teams': teams, 'remaining': []}

    for m in fixtures:
        if m.get('stage') != 'GROUP_STAGE' or m.get('status') == 'FINISHED':
            continue
        letter = _letter(m.get('group', ''))
        if letter not in groups:
            continue
        groups[letter]['remaining'].append({
            'matchId': m['id'],
            'homeId': m['homeTeam']['id'],
            'awayId': m['awayTeam']['id'],
            'homeName': m['homeTeam']['name'],
            'awayName': m['awayTeam']['name'],
            'venue': m.get('venue'),
        })
    return groups


def main() -> None:
    """Parse args, run the engine, print the stakes report."""
    ap = argparse.ArgumentParser(description='Per-match group stakes report')
    ap.add_argument('--data', help='snapshot JSON {standings, fixtures}')
    ap.add_argument('--group', help='single group letter, e.g. C')
    ap.add_argument('--team', help='filter to one team (substring match)')
    ap.add_argument('--sims', type=int, default=20000)
    args = ap.parse_args()

    standings, fixtures = _load_snapshot(args.data)
    groups = _build_groups(standings, fixtures)

    letters = [args.group.upper()] if args.group else sorted(groups)
    for letter in letters:
        g = groups.get(letter)
        if not g or not g['remaining']:
            continue
        res = compute_group_stakes(g['teams'], g['remaining'], args.sims)
        print(f"\n{'='*74}\nGROUP {letter}  (n={res['nSims']} sims)")
        print(f"  {'team':<16}{'P(1st)':>8}{'P(top2)':>9}{'P(3rd)':>8}")
        for t in res['teams']:
            print(
                f"  {t['name']:<16}{t['pFirst']*100:7.1f}%{t['pTop2']*100:8.1f}%"
                f"{t['pThird']*100:7.1f}%"
            )
        print('  ── stakes per remaining match '
              '(swing = ΔP(top2) win vs loss) ──')
        for t in res['teams']:
            if args.team and args.team.lower() not in t['name'].lower():
                continue
            for m in t['matches']:
                print(
                    f"    {t['name']:<14} vs {m['opponent']:<14} "
                    f"swingTop2={m['swingTop2']:+.2f} "
                    f"swingFirst={m['swingFirst']:+.2f} "
                    f"stakes={m['stakes']:.2f}  [{m['label']}]"
                )


if __name__ == '__main__':
    main()
