"""
Análisis pre-partido con XI probable y afinidad extendida.

Productiza el flujo validado en MX-SA y KOR-CZE (jornada 1):

  1. XI probable por equipo = los 11 titulares más frecuentes en los
     últimos 5 partidos de selección (alineaciones de API-Football).
  2. Afinidad base por club/liga (player_club_map.json) elevada por
     titularidades compartidas recientes (noisy-or, NT_W=0.85).
  3. Predictor de producción con afinidades extendidas + blend con
     momios de mercado.
  4. Distribución Poisson de marcadores condicionada al blended.
  5. Snapshot registrado en el forecast ledger.

Advertencia metodológica (validada en KOR-CZE): el XI por frecuencia es
ruidoso para equipos que rotan en amistosos — Corea dejó fuera del XI
probable a Son y Lee Kang-in y ambos fueron titulares. El reporte marca
los partidos amistosos para ponderar esa incertidumbre.

Las llamadas a API-Football se cachean en apif_cache/nt_last5_cache.json
(~12 requests por partido nuevo; cuota gratuita: 100/día).
"""

import json
import logging
import math
import os
import time
import unicodedata
from collections import Counter
from pathlib import Path

import httpx

from app.services.forecast_ledger import record_snapshot
from app.services.match_predictor import get_strength, predictor
from app.services.odds_api import get_match_odds
from app.services.team_data import TEAM_DATA, missing_ratings

log = logging.getLogger(__name__)

_APIF_BASE = "https://v3.football.api-sports.io"
_CACHE_PATH = (
    Path(__file__).parent.parent.parent / "apif_cache" / "nt_last5_cache.json"
)
_MAP_PATH = Path(__file__).parent / "player_club_map.json"

_RATE_PAUSE = 6.5  # 10 req/min en plan gratuito; +0.5 s de margen
_NT_W = 0.85  # peso de titularidades compartidas vs entrenar juntos
_BASE_GOALS = 1.3  # mismos parámetros de gol que forecasting.py
_GOAL_K = 1.5

# Equivalencias football-data ↔ API-Football para nombres de selección
_APIF_TEAM_ALIASES: dict[str, str] = {
    "Czechia": "Czech Republic",
    "Korea Republic": "South Korea",
    "Bosnia-Herzegovina": "Bosnia",
    "Cape Verde Islands": "Cape Verde",
    "Congo DR": "Congo DR",
    # APIF llama 'USA' a la selección; buscar 'United States' devuelve
    # un equipo equivocado (id 12522)
    "United States": "USA",
}

_last_call: list[float] = [0.0]


# ───────────────────────── API-Football con caché ──────────────────────────


def _apif(path: str, **params) -> dict:
    """GET cacheado a API-Football con rate-limit del plan gratuito."""
    cache: dict = {}
    if _CACHE_PATH.exists():
        cache = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    key = path + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    if key in cache:
        return cache[key]

    wait = _RATE_PAUSE - (time.time() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    r = httpx.get(
        _APIF_BASE + path,
        headers={"x-apisports-key": os.getenv("APIF_KEY", "")},
        params=params,
        timeout=20,
    )
    _last_call[0] = time.time()
    r.raise_for_status()
    data = r.json()
    if data.get("errors"):
        raise RuntimeError(f"APIF error en {key}: {data['errors']}")
    cache[key] = data
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(cache), encoding="utf-8")
    return data


def find_team_id(name: str) -> int:
    """Resuelve el id de selección en API-Football por nombre.

    Usa búsqueda parcial (los nombres difieren entre proveedores, p.ej.
    'Bosnia-Herzegovina' vs 'Bosnia and Herzegovina') y filtra por
    equipos nacionales.
    """
    apif_name = _APIF_TEAM_ALIASES.get(name, name)
    resp = _apif("/teams", search=apif_name)["response"]
    nationals = [
        t
        for t in resp
        if t["team"].get("national")
        # Excluir selecciones femeniles (sufijo ' W' en API-Football)
        and not t["team"]["name"].endswith(" W")
    ]
    if not nationals:
        raise LookupError(f"Selección no encontrada en APIF: {name}")
    exact = [t for t in nationals if t["team"]["name"] == apif_name]
    return (exact or nationals)[0]["team"]["id"]


# ───────────────────────── Conciliación de nombres ─────────────────────────


def _toks(name: str) -> list[str]:
    s = "".join(
        c
        for c in unicodedata.normalize("NFD", name.lower())
        if unicodedata.category(c) != "Mn"
    )
    return [t for t in s.replace("-", " ").replace(".", "").split() if t]


def same_player(a: str, b: str) -> bool:
    """Compara nombres entre regímenes de romanización/abreviación.

    Cubre: orden invertido ('Young-woo Seol' vs 'Seol Young-Woo'),
    guiones ('Hee-Chan' vs 'Heechan' no — eso lo cubre lookup_club) y
    abreviaturas ('T. Soucek' vs 'Tomáš Souček') por apellido+inicial.
    """
    ta, tb = _toks(a), _toks(b)
    if set(ta) == set(tb):
        return True
    # Subconjunto con ≥2 tokens: 'Kerim Alajbegović' ⊂ 'Kerim-Sam
    # Alajbegović' (segundos nombres que un proveedor omite)
    if len(ta) >= 2 and set(ta) <= set(tb):
        return True
    if len(tb) >= 2 and set(tb) <= set(ta):
        return True
    if len(ta) == 2 and len(ta[0]) == 1:
        return ta[1] == tb[-1] and ta[0] == tb[0][0]
    if len(tb) == 2 and len(tb[0]) == 1:
        return tb[1] == ta[-1] and tb[0] == ta[0][0]
    return False


def _norm(s: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFD", s.lower())
        if unicodedata.category(c) != "Mn"
    ).replace("-", " ")


def lookup_club(player_name: str, pcm: dict[str, dict]) -> dict:
    """Busca un nombre de alineación APIF en player_club_map.

    El match exacto (token-sets / abreviatura) corre ANTES que el
    difuso: el solapamiento parcial de tokens produce falsos positivos
    (lección KOR-CZE: 'Alexandr Sojka' matcheaba un jugador de otro
    club).
    """
    for info in pcm.values():
        if same_player(player_name, info["name"]):
            return info

    target = _norm(player_name)
    target_joined = target.replace(" ", "")
    target_parts = target.split()
    best: tuple[int, dict] | None = None
    for info in pcm.values():
        cand = _norm(info["name"])
        cand_parts = cand.split()
        if cand.replace(" ", "") == target_joined:
            return info
        overlap = set(target_parts) & set(cand_parts)
        joined_hits = sum(
            1
            for tp in target_parts
            if any(
                tp != cp and (tp in cp or cp in tp) and len(tp) > 2
                for cp in cand_parts
            )
        )
        score = len(overlap) + joined_hits
        if score >= 2 and (best is None or score > best[0]):
            best = (score, info)
    return best[1] if best else {}


# ───────────────────────── XI probable y afinidad ──────────────────────────


def probable_xi(
    team_name: str, team_id: int, before_date: str
) -> tuple[list[dict], list[dict]]:
    """XI probable y últimos 5 partidos de una selección.

    Args:
        team_name: Nombre football-data de la selección.
        team_id: Id API-Football.
        before_date: Solo cuenta partidos anteriores a esta fecha
            (YYYY-MM-DD) — excluye el partido a pronosticar.

    Returns:
        (xi, matches): el XI probable (11 titulares más frecuentes, con
        club/liga mapeados) y los partidos con sus sets de titulares.
    """
    pcm = json.loads(_MAP_PATH.read_text(encoding="utf-8"))
    # Índice por id de API-Football: los nombres de alineación vienen
    # abreviados ('A. Fathi') y la transliteración árabe (Fathi/Fathy)
    # rompe el match por nombre; el id de jugador es estable entre
    # alineaciones y squads, así que es el puente fiable a club/liga.
    apif_index = {
        int(info["apif_id"]): info
        for info in pcm.values()
        if info.get("apif_id")
    }
    fixtures = _apif("/fixtures", team=team_id, last=8)["response"]
    done = [
        f
        for f in fixtures
        if f["fixture"]["status"]["short"] in ("FT", "AET", "PEN")
        and f["fixture"]["date"][:10] < before_date
    ][:5]

    starts: Counter = Counter()
    names: dict[int, str] = {}
    matches: list[dict] = []
    for f in done:
        lus = _apif("/fixtures/lineups", fixture=f["fixture"]["id"])[
            "response"
        ]
        mine = next((l for l in lus if l["team"]["id"] == team_id), None)
        started: set[int] = set()
        if mine:
            for p in mine.get("startXI", []):
                pid = p["player"]["id"]
                starts[pid] += 1
                names[pid] = p["player"]["name"]
                started.add(pid)
        opp_side = "away" if f["teams"]["home"]["id"] == team_id else "home"
        own_side = "home" if opp_side == "away" else "away"
        matches.append(
            {
                "date": f["fixture"]["date"][:10],
                "opponent": f["teams"][opp_side]["name"],
                "competition": f["league"]["name"],
                "friendly": "friendl" in f["league"]["name"].lower(),
                "score": f"{f['goals'][own_side]}-{f['goals'][opp_side]}",
                "started": started,
            }
        )

    ranked = sorted(starts.items(), key=lambda kv: (-kv[1], names[kv[0]]))
    xi = []
    for pid, n_starts in ranked[:11]:
        nm = names[pid]
        info = apif_index.get(pid) or lookup_club(nm, pcm)
        xi.append(
            {
                "name": nm,
                "club": info.get("club", ""),
                "league_code": info.get("league_code", ""),
                "min_pct": 1.0,
                "starts": n_starts,
                "apifId": pid,
            }
        )
    return xi, matches


def extended_affinity(xi: list[dict], matches: list[dict]) -> float:
    """Afinidad extendida [0-100] de un XI: club/liga + titularidades.

    aff_par = base + (1 - base) · NT_W · (compartidas / n_partidos),
    normalizada igual que squad_affinity_score() para ser comparable.
    """
    from app.services.club_ratings import _pair_affinity

    played = [m["started"] for m in matches if m["started"]]
    n_matches = len(played) or 1
    n = len(xi)
    if n < 2:
        return 50.0
    total = 0.0
    for i in range(n):
        for j in range(i + 1, n):
            a, b = xi[i], xi[j]
            base = _pair_affinity(a, b)
            shared = sum(
                1 for s in played if a["apifId"] in s and b["apifId"] in s
            )
            total += base + (1 - base) * _NT_W * (shared / n_matches)
    raw = total / (n * (n - 1) / 2)
    return round(max(0.0, min(100.0, (raw - 0.15) / 0.85 * 100.0)), 2)


# ───────────────────────── Marcadores condicionados ────────────────────────


def _poisson_pmf(k: int, lam: float) -> float:
    return math.exp(-lam) * lam**k / math.factorial(k)


def conditioned_scorelines(
    home: str, away: str, p_final: tuple[float, float, float]
) -> dict:
    """Distribución de marcadores Poisson condicionada a (pW, pX, pL)."""
    la = _BASE_GOALS * math.exp(
        _GOAL_K * (get_strength(home) - get_strength(away))
    )
    lb = _BASE_GOALS * math.exp(
        _GOAL_K * (get_strength(away) - get_strength(home))
    )
    grid = {
        (a, b): _poisson_pmf(a, la) * _poisson_pmf(b, lb)
        for a in range(9)
        for b in range(9)
    }
    mass = {
        "w": sum(p for (a, b), p in grid.items() if a > b),
        "d": sum(p for (a, b), p in grid.items() if a == b),
        "l": sum(p for (a, b), p in grid.items() if a < b),
    }
    target = {"w": p_final[0], "d": p_final[1], "l": p_final[2]}

    def _bucket(a: int, b: int) -> str:
        return "w" if a > b else "d" if a == b else "l"

    cond = {
        sc: p / mass[_bucket(*sc)] * target[_bucket(*sc)]
        for sc, p in grid.items()
    }
    top = sorted(cond.items(), key=lambda t: -t[1])[:8]
    return {
        "lambdas": {"home": round(la, 2), "away": round(lb, 2)},
        "topScorelines": [
            {"score": f"{a}-{b}", "prob": round(p, 4)} for (a, b), p in top
        ],
        "over25": round(sum(p for (a, b), p in cond.items() if a + b >= 3), 4),
        "btts": round(
            sum(p for (a, b), p in cond.items() if a > 0 and b > 0), 4
        ),
    }


# ───────────────────────── Orquestación ────────────────────────────────────


async def run_prematch(
    home: str,
    away: str,
    match_date: str,
    stage: str = "GROUP_STAGE",
    venue: str | None = None,
) -> dict:
    """Corre el análisis pre-partido completo y lo registra en el ledger.

    Args:
        home: Selección local (nombre football-data).
        away: Selección visitante.
        match_date: Fecha del partido (YYYY-MM-DD), para excluirlo del
            historial de últimos 5.
        stage: Etapa del torneo.
        venue: Sede; si None se auto-detecta para fase de grupos.

    Returns:
        Reporte completo: XIs probables, afinidades, probabilidades por
        capa, momios y marcadores condicionados.
    """
    from app.services.venues import get_venue

    resolved_venue = venue or (
        get_venue(home, away) if stage == "GROUP_STAGE" else None
    )

    teams: dict[str, dict] = {}
    affinities: dict[str, float] = {}
    friendly_shares: dict[str, float] = {}
    for name in (home, away):
        tid = find_team_id(name)
        xi, last5 = probable_xi(name, tid, match_date)
        aff = extended_affinity(xi, last5)
        affinities[name] = aff
        share = (
            sum(1 for m in last5 if m["friendly"]) / len(last5)
            if last5
            else None
        )
        friendly_shares[name] = share or 0.0
        unrated_sources = missing_ratings(name)
        teams[name] = {
            "apifId": tid,
            "probableXI": xi,
            "last5": [
                {k: v for k, v in m.items() if k != "started"} for m in last5
            ],
            "friendlyShare": share,
            "extendedAffinity": aff,
            "ratingCoverage": {
                "rated": not unrated_sources,
                "missingSources": unrated_sources,
            },
        }

    p_model = predictor.predict(
        home,
        away,
        stage=stage,
        venue=resolved_venue,
        affinity_a=affinities[home],
        affinity_b=affinities[away],
        friendly_share_a=friendly_shares[home],
        friendly_share_b=friendly_shares[away],
    )

    market = None
    p_final = p_model
    try:
        odds = await get_match_odds(known_names=set(TEAM_DATA.keys()))
        payload = odds.get((home, away)) or odds.get((away, home))
        if payload:
            p_mkt = (
                payload["homeWin"],
                payload["draw"] or 0.0,
                payload["awayWin"],
            )
            p_final = predictor.blend_with_market(p_model, p_mkt)
            market = {
                "bookmakerCount": payload["bookmakerCount"],
                "rawOdds": payload["rawOdds"],
                "probs": {
                    "homeWin": round(p_mkt[0], 4),
                    "draw": round(p_mkt[1], 4),
                    "awayWin": round(p_mkt[2], 4),
                },
            }
    except (httpx.HTTPError, RuntimeError, KeyError) as err:
        log.warning("Momios no disponibles: %s", err)

    report = {
        "home": home,
        "away": away,
        "stage": stage,
        "venue": resolved_venue,
        "teams": teams,
        "probs": {
            "model": {
                "homeWin": round(p_model[0], 4),
                "draw": round(p_model[1], 4),
                "awayWin": round(p_model[2], 4),
            },
            "market": (market or {}).get("probs"),
            "blended": {
                "homeWin": round(p_final[0], 4),
                "draw": round(p_final[1], 4),
                "awayWin": round(p_final[2], 4),
            },
        },
        "market": market,
        "scorelines": conditioned_scorelines(home, away, p_final),
    }

    record_snapshot(
        home,
        away,
        stage,
        resolved_venue,
        probs=report["probs"],
        extras={
            "method": "prematch_xi_extended",
            "affinity": affinities,
        },
    )
    return report
