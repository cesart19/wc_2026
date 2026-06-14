"""
Monte Carlo tournament simulator for WC 2026.

Pipeline:
  1. Fetch current standings + fixtures from football-data.org
  2. Build group tables (actual results already applied via standings)
  3. For each simulation:
       a. Complete remaining group matches → simulate goals (Poisson) for GD/GF
       b. Determine 32 qualifiers using official FIFA bracket (Annex C for 3rd place)
       c. Run knockout bracket in official order using _KNOCKOUT_VENUES for crowd
  4. Aggregate win counts → tournament win probability per team

Precision improvements vs. original:
  - Real FIFA bracket (replaces random.shuffle) → eliminates biggest variance source
  - Venue-aware crowd in both group + knockout stages
  - Poisson goal simulation for correct GD/GF tiebreaking
  - n = 50 000 simulations (SE ≈ ±0.18 pp for a 20% win probability)
"""

import json
import math
import random
import time
from collections import defaultdict
from pathlib import Path

import asyncio

from app.services.football_api import get_standings, get_matches
from app.services.team_data import get_team_data, TEAM_DATA
from app.services.match_predictor import predictor, get_strength, _BLEND_ALPHA
from app.services.venues import get_venue, get_venue_by_id
from app.services.bracket import KNOCKOUT_BRACKET, BRACKET_ORDER, FINAL_MATCH_ID, resolve_slot
from app.services.third_place_lookup import THIRD_PLACE_LOOKUP
from app.services.odds_api import get_match_odds

_cache: dict = {}
CACHE_TTL = 300  # seconds

# ---------------------------------------------------------------------------
# Squad affinity lookup — cargado desde squad_context_v3.json al iniciar.
# Cada equipo nacional tiene un affinity_score [0-100] pre-computado que
# mide la cohesión entre pares de jugadores según club y liga compartida.
# Si el archivo no está disponible, todos los equipos usan 50.0 (neutral).
# ---------------------------------------------------------------------------
_AFFINITY_JSON = Path(__file__).parent / "squad_context_v3.json"
_TEAM_AFFINITY: dict[str, float] = {}

try:
    _sc_entries = json.loads(_AFFINITY_JSON.read_text(encoding="utf-8"))
    for _entry in _sc_entries:
        _name = _entry.get("team", "")
        _aff  = _entry.get("affinity_score")
        if _name and _aff is not None:
            _TEAM_AFFINITY[_name] = float(_aff)
except Exception:
    pass   # sin datos → se usará 50.0 (neutral) para todos los equipos


def _get_affinity(name: str) -> float:
    """Retorna el squad affinity score pre-computado. Default 50.0 si no hay dato."""
    return _TEAM_AFFINITY.get(name, 50.0)


# ---------------------------------------------------------------------------
# Poisson goal sampling
# ---------------------------------------------------------------------------

_BASE_GOALS = 1.3   # media de goles por equipo en WC (total ≈ 2.6)
_GOAL_K     = 1.5   # sensibilidad al diferencial de fuerza compuesta


def _poisson_sample(lam: float) -> int:
    """Muestra de distribución de Poisson por método de inversión (lam < 30)."""
    L = math.exp(-max(0.01, lam))
    k, p = 0, 1.0
    while p > L:
        k += 1
        p *= random.random()
    return k - 1


def _sample_goals(strength_a: float, strength_b: float, outcome: str) -> tuple[int, int]:
    """
    Muestrea goles (ga, gb) consistentes con el outcome dado.
    outcome: 'win' (A gana) | 'draw' | 'loss' (B gana).
    Usa rejection sampling; fallback determinista tras 30 intentos.
    """
    la = _BASE_GOALS * math.exp(_GOAL_K * (strength_a - strength_b))
    lb = _BASE_GOALS * math.exp(_GOAL_K * (strength_b - strength_a))
    for _ in range(30):
        ga, gb = _poisson_sample(la), _poisson_sample(lb)
        if outcome == "win"  and ga > gb: return ga, gb
        if outcome == "draw" and ga == gb: return ga, gb
        if outcome == "loss" and ga < gb: return ga, gb
    # Fallback determinista
    if outcome == "win":  return 1, 0
    if outcome == "draw": return 1, 1
    return 0, 1


# ---------------------------------------------------------------------------
# Per-match simulation helpers
# ---------------------------------------------------------------------------

def _sim_group(
    name_a: str, name_b: str,
    ppg_a: float, ppg_b: float,
    venue: str | None = None,
    market_probs: tuple[float, float, float] | None = None,
) -> tuple[int, int, int, int, int, int]:
    """
    Simula un partido de fase de grupos.
    Devuelve (pts_a, gd_a, gf_a, pts_b, gd_b, gf_b).

    Si market_probs se proporciona, mezcla las probabilidades del modelo con las
    del mercado usando _BLEND_ALPHA antes de samplear el resultado.
    """
    p_a, p_draw, p_b = predictor.predict(
        name_a, name_b, ppg_a, ppg_b, stage="GROUP_STAGE", venue=venue,
        affinity_a=_get_affinity(name_a), affinity_b=_get_affinity(name_b),
    )
    if market_probs is not None:
        blended = predictor.blend_with_market((p_a, p_draw, p_b), market_probs)
        p_a, p_draw = blended[0], blended[1]
    sa, sb = get_strength(name_a), get_strength(name_b)
    r = random.random()
    if r < p_a:
        ga, gb = _sample_goals(sa, sb, "win")
        return 3, ga - gb, ga,  0, gb - ga, gb
    if r < p_a + p_draw:
        ga, gb = _sample_goals(sa, sb, "draw")
        return 1, 0, ga,        1, 0, gb
    ga, gb = _sample_goals(sa, sb, "loss")
    return 0, ga - gb, ga,  3, gb - ga, gb


def _sim_knockout(name_a: str, name_b: str, venue: str | None = None) -> bool:
    """
    Simula un partido de fase eliminatoria.
    Devuelve True si A gana. El venue se usa para crowd-boost del co-anfitrión.
    """
    p_a, _, _ = predictor.predict(
        name_a, name_b, stage="KNOCKOUT", venue=venue,
        affinity_a=_get_affinity(name_a), affinity_b=_get_affinity(name_b),
    )
    return random.random() < p_a


# ---------------------------------------------------------------------------
# Group data builders
# ---------------------------------------------------------------------------

def _build_groups(standings_raw: dict, matches_raw: dict) -> list[dict]:
    """Parse API standings into group structures for simulation."""
    groups = []
    for grp in standings_raw.get("standings", []):
        if grp.get("stage") != "GROUP_STAGE":
            continue

        group_letter = grp.get("group", "").replace("GROUP_", "")
        teams = []
        for row in grp.get("table", []):
            t = row["team"]
            name = t.get("name", "TBD")
            td = get_team_data(name)
            played = row["playedGames"]
            pts = row["points"]
            teams.append({
                "id": t["id"],
                "name": name,
                "crest": t.get("crest", ""),
                "group": group_letter,
                "strength": get_strength(name),
                "elo": td["elo"],
                "fifaPoints": td["fifa_pts"],
                "marketValueM": td["market_value_m"],
                "pts": pts,
                "gd": row["goalDifference"],
                "gf": row["goalsFor"],
                "played": played,
                "ppg": pts / played if played else 1.5,
            })

        team_ids = {t["id"] for t in teams}
        remaining = [
            (m["homeTeam"]["id"], m["awayTeam"]["id"])
            for m in matches_raw.get("matches", [])
            if m.get("stage") == "GROUP_STAGE"
            and m.get("status") != "FINISHED"
            and m["homeTeam"].get("id") in team_ids
            and m["awayTeam"].get("id") in team_ids
        ]

        groups.append({"name": group_letter, "teams": teams, "remaining": remaining})
    return groups


def _build_groups_from_fixtures(matches_raw: dict) -> list[dict]:
    """Fallback when standings are unavailable (pre-tournament)."""
    groups_dict: dict[str, dict] = defaultdict(dict)
    for m in matches_raw.get("matches", []):
        if m.get("stage") != "GROUP_STAGE":
            continue
        letter = m.get("group", "").replace("GROUP_", "") or "?"
        for side in ("homeTeam", "awayTeam"):
            t = m[side]
            t_id = t.get("id")
            t_name = t.get("name") or "TBD"
            if t_id and t_id not in groups_dict[letter]:
                td = get_team_data(t_name)
                groups_dict[letter][t_id] = {
                    "id": t_id,
                    "name": t_name,
                    "crest": t.get("crest", ""),
                    "group": letter,
                    "strength": get_strength(t_name),
                    "elo": td["elo"],
                    "fifaPoints": td["fifa_pts"],
                    "marketValueM": td["market_value_m"],
                    "pts": 0,
                    "gd": 0,
                    "gf": 0,
                    "played": 0,
                    "ppg": 1.5,
                }

    groups = []
    for letter, team_map in sorted(groups_dict.items()):
        teams = list(team_map.values())
        team_ids = {t["id"] for t in teams}
        remaining = [
            (m["homeTeam"]["id"], m["awayTeam"]["id"])
            for m in matches_raw.get("matches", [])
            if m.get("stage") == "GROUP_STAGE"
            and m.get("status") != "FINISHED"
            and m.get("group", "").replace("GROUP_", "") == letter
            and m["homeTeam"].get("id") in team_ids
            and m["awayTeam"].get("id") in team_ids
        ]
        groups.append({"name": letter, "teams": teams, "remaining": remaining})
    return groups


# ---------------------------------------------------------------------------
# One tournament simulation
# ---------------------------------------------------------------------------

def _simulate_once(
    groups: list[dict],
    odds_lookup: dict[tuple[str, str], tuple[float, float, float]] | None = None,
) -> str | None:
    """
    Simula un torneo completo usando el bracket oficial FIFA WC 2026.
    Devuelve el nombre del campeón o None si el bracket queda incompleto.

    Si odds_lookup se proporciona (keyed por (name_a, name_b)), mezcla las
    probabilidades del modelo con las del mercado en los partidos de grupos.
    """
    # ── Fase de grupos ────────────────────────────────────────────────────
    group_results: dict[str, list[dict]] = {}       # letra → tabla ordenada
    third_placers: list[tuple[dict, str]] = []      # (team_dict, group_letter)

    for grp in groups:
        table = [dict(t) for t in grp["teams"]]
        id_to_team = {t["id"]: t for t in table}

        for id_a, id_b in grp["remaining"]:
            if id_a not in id_to_team or id_b not in id_to_team:
                continue
            a, b = id_to_team[id_a], id_to_team[id_b]
            venue = get_venue(a["name"], b["name"])
            market = (
                odds_lookup.get((a["name"], b["name"]))
                if odds_lookup else None
            )
            pa, gda, gfa, pb, gdb, gfb = _sim_group(
                a["name"], b["name"], a["ppg"], b["ppg"],
                venue=venue, market_probs=market,
            )
            a["pts"] += pa;  a["gd"] += gda;  a["gf"] += gfa
            b["pts"] += pb;  b["gd"] += gdb;  b["gf"] += gfb

        table.sort(key=lambda t: (-t["pts"], -t["gd"], -t["gf"], t["name"]))
        group_results[grp["name"]] = table
        if len(table) >= 3:
            third_placers.append((table[2], grp["name"]))

    # ── Slots del bracket ─────────────────────────────────────────────────
    slots: dict[str, dict] = {}
    for letter, table in group_results.items():
        if len(table) >= 1: slots[f"w_{letter}"] = table[0]
        if len(table) >= 2: slots[f"r_{letter}"] = table[1]

    # Annex C: mejores 8 terceros → asignar a sus slots t_XXX
    sorted_thirds = sorted(
        third_placers, key=lambda x: (-x[0]["pts"], -x[0]["gd"], -x[0]["gf"])
    )
    top8 = sorted_thirds[:8]
    thirds_key = "".join(sorted(t[1] for t in top8))
    for slot, letter in THIRD_PLACE_LOOKUP.get(thirds_key, {}).items():
        team = next((t[0] for t in top8 if t[1] == letter), None)
        if team:
            slots[slot] = team

    # ── Bracket knockout (orden oficial) ──────────────────────────────────
    match_results: dict[int, dict] = {}
    for match_id in BRACKET_ORDER:
        if match_id == 537389:   # 3er lugar: no necesario para el campeón
            continue
        entry = KNOCKOUT_BRACKET[match_id]
        home = resolve_slot(entry["home"], slots, match_results)
        away = resolve_slot(entry["away"], slots, match_results)
        if home is None or away is None:
            return None
        venue = get_venue_by_id(match_id)
        winner_is_home = _sim_knockout(home["name"], away["name"], venue=venue)
        match_results[match_id] = {
            "winner": home if winner_is_home else away,
            "loser":  away if winner_is_home else home,
        }

    final = match_results.get(FINAL_MATCH_ID)
    return final["winner"]["name"] if final else None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

import logging as _logging
_log = _logging.getLogger(__name__)


async def run_forecast(n: int = 50_000) -> list[dict]:
    """
    Run Monte Carlo simulation and return tournament win probabilities.
    Results are cached for CACHE_TTL seconds.

    Cuando ODDS_API_KEY está configurado y hay partidos próximos, las
    probabilidades de cada partido de grupos se mezclan con los momios del
    mercado usando _BLEND_ALPHA (ver match_predictor.py).
    """
    entry = _cache.get("forecast")
    if entry and time.time() - entry["ts"] < CACHE_TTL:
        return entry["data"]

    # Fetch paralelo de standings, matches y odds (odds viene del caché si está caliente)
    known = set(TEAM_DATA.keys())
    standings_raw, matches_raw, raw_odds = await asyncio.gather(
        get_standings(),
        get_matches(),
        get_match_odds(known_names=known),
    )

    # Construir lookup bidireccional (home, away) → (p_home, p_draw, p_away)
    odds_lookup: dict[tuple[str, str], tuple[float, float, float]] = {}
    if raw_odds:
        for (home, away), payload in raw_odds.items():
            ph = payload["homeWin"]
            pd = payload["draw"] if payload["draw"] is not None else 0.0
            pa = payload["awayWin"]
            odds_lookup[(home, away)] = (ph, pd, pa)
            odds_lookup[(away, home)] = (pa, pd, ph)  # orientación invertida
        _log.info(
            "Monte Carlo: usando momios de mercado para %d partidos (alpha=%.2f)",
            len(raw_odds), _BLEND_ALPHA,
        )
    else:
        _log.info("Monte Carlo: sin datos de mercado — usando solo modelo estadístico")

    groups = _build_groups(standings_raw, matches_raw)
    if not groups:
        groups = _build_groups_from_fixtures(matches_raw)

    if not groups:
        return []

    win_counts: dict[str, int] = defaultdict(int)
    for _ in range(n):
        champion = _simulate_once(groups, odds_lookup=odds_lookup or None)
        if champion:
            win_counts[champion] += 1

    all_teams = {t["name"]: t for grp in groups for t in grp["teams"]}
    market_data_used = bool(odds_lookup)
    result = [
        {
            "teamId": team["id"],
            "team": name,
            "crest": team.get("crest", ""),
            "group": team.get("group", ""),
            "elo": team["elo"],
            "fifaPoints": team["fifaPoints"],
            "marketValueM": team["marketValueM"],
            "strength": round(team["strength"], 4),
            "winProbability": round(win_counts.get(name, 0) / n, 4),
            "winPct": round(win_counts.get(name, 0) / n * 100, 2),
            "simulations": n,
            "marketDataUsed": market_data_used,
        }
        for name, team in all_teams.items()
    ]
    result.sort(key=lambda x: -x["winProbability"])

    _cache["forecast"] = {"data": result, "ts": time.time()}
    return result
