"""
Cliente para the-odds-api.com — momios de casas de apuestas.

Proporciona dos funciones principales:
  - get_match_odds()    → probabilidades h2h sin vig para partidos próximos
  - get_outright_odds() → probabilidades de campeón del torneo

Diseño:
  - Caché en memoria con TTL separado por tipo de endpoint
  - Graceful degradation: retorna None si la key no está configurada o hay error
  - Normalización de nombres de equipos (Odds-API ≠ football-data.org en algunos casos)
  - No-vig: elimina el overround del bookmaker para obtener probabilidades justas

Presupuesto de requests (tier gratuito: 500/mes):
  - Match odds:  caché 1800s (30 min) → ~48 llamadas/día durante el torneo
  - Outrights:   caché 21600s (6h) → ~4 llamadas/día
  Subir los TTLs para quedarse dentro del tier gratuito si se desea.
"""

import os
import time
import logging
import unicodedata

import httpx

logger = logging.getLogger(__name__)

_ODDS_BASE = "https://api.the-odds-api.com/v4"
_SPORT_MATCH    = "soccer_fifa_world_cup"         # h2h (1X2) por partido
_SPORT_OUTRIGHT = "soccer_fifa_world_cup_winner"  # campeón del torneo (sport separado)

# Cachés separados: match odds (30 min) y outrights (6 h)
_cache: dict = {}
MATCH_ODDS_TTL = 1800    # segundos — balance entre frescura y cuota de la API
OUTRIGHT_ODDS_TTL = 21600  # segundos

# Mapeo estático de nombres Odds-API → nombres canónicos (football-data.org)
# Ampliar si se detectan divergencias adicionales durante el torneo.
_ODDS_TO_CANONICAL: dict[str, str] = {
    "USA":                       "United States",
    "Czech Republic":            "Czechia",
    "Bosnia and Herzegovina":    "Bosnia-Herzegovina",
    "Bosnia & Herzegovina":      "Bosnia-Herzegovina",
    "DR Congo":                  "Congo DR",
    "Ivory Coast":               "Côte d'Ivoire",
    "Korea Republic":            "South Korea",
    "Korea DPR":                 "Korea DPR",
    "IR Iran":                   "Iran",
    "China PR":                  "China PR",
    "Cape Verde":                "Cape Verde Islands",
    "Trinidad And Tobago":       "Trinidad and Tobago",
    "Central African Republic":  "Central African Republic",
    "Equatorial Guinea":         "Equatorial Guinea",
}


def _api_key() -> str | None:
    return os.getenv("ODDS_API_KEY") or None


def _normalize_str(name: str) -> str:
    """Lowercase + eliminar diacríticos para comparación fuzzy."""
    nfkd = unicodedata.normalize("NFKD", name)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def _canonical_name(odds_name: str, known_names: set[str]) -> str:
    """
    Convierte un nombre de equipo de the-odds-api a nuestro nombre canónico.
    Nivel 1: diccionario estático de mapeos conocidos.
    Nivel 2: coincidencia exacta con los nombres conocidos.
    Nivel 3: coincidencia fuzzy (sin diacríticos, minúsculas).
    Nivel 4: retorna el nombre sin cambios.
    """
    if odds_name in _ODDS_TO_CANONICAL:
        return _ODDS_TO_CANONICAL[odds_name]
    if odds_name in known_names:
        return odds_name
    norm = _normalize_str(odds_name)
    for k in known_names:
        if _normalize_str(k) == norm:
            return k
    logger.debug("Nombre no reconocido de Odds-API: %r", odds_name)
    return odds_name


def no_vig_probs(odds_list: list[float]) -> list[float]:
    """
    Convierte lista de momios decimales a probabilidades justas (sin vig).
    El overround (sum > 1.0) se elimina normalizando las probabilidades implícitas.

    Ejemplo: [2.10, 3.40, 3.60] → overround ≈ 1.085 → probs normalizadas suman 1.0
    """
    if not odds_list:
        return []
    raw = [1.0 / o for o in odds_list if o > 0]
    total = sum(raw)
    if total == 0:
        n = len(odds_list)
        return [1.0 / n] * n
    return [r / total for r in raw]


def _average_book_odds(event: dict, market: str) -> dict[str, float]:
    """
    Promedia los momios decimales de todos los bookmakers para un mercado dado.
    Retorna dict nombre_outcome → momio_promedio.
    """
    accumulated: dict[str, list[float]] = {}
    for book in event.get("bookmakers", []):
        for mkt in book.get("markets", []):
            if mkt["key"] != market:
                continue
            for outcome in mkt.get("outcomes", []):
                name = outcome["name"]
                price = float(outcome["price"])
                if price > 1.0:  # momio válido
                    accumulated.setdefault(name, []).append(price)

    return {name: sum(prices) / len(prices) for name, prices in accumulated.items()}


def _extract_h2h_odds(
    event: dict,
    known_names: set[str],
) -> dict | None:
    """
    Extrae y convierte las probabilidades h2h de un evento.
    Retorna None si no hay suficientes datos.
    """
    avg = _average_book_odds(event, "h2h")
    if not avg:
        return None

    raw_home = event.get("home_team", "")
    raw_away = event.get("away_team", "")
    home = _canonical_name(raw_home, known_names)
    away = _canonical_name(raw_away, known_names)

    home_odds = avg.get(raw_home)
    away_odds = avg.get(raw_away)
    draw_odds = avg.get("Draw")

    if home_odds is None or away_odds is None:
        return None

    if draw_odds is not None:
        odds_vals = [home_odds, draw_odds, away_odds]
        probs = no_vig_probs(odds_vals)
        return {
            "home": home,
            "away": away,
            "homeWin": round(probs[0], 4),
            "draw":    round(probs[1], 4),
            "awayWin": round(probs[2], 4),
            "rawOdds": {
                "home": round(home_odds, 3),
                "draw": round(draw_odds, 3),
                "away": round(away_odds, 3),
            },
            "commence":       event.get("commence_time"),
            "bookmakerCount": len(event.get("bookmakers", [])),
        }
    else:
        odds_vals = [home_odds, away_odds]
        probs = no_vig_probs(odds_vals)
        return {
            "home": home,
            "away": away,
            "homeWin": round(probs[0], 4),
            "draw":    None,
            "awayWin": round(probs[1], 4),
            "rawOdds": {
                "home": round(home_odds, 3),
                "draw": None,
                "away": round(away_odds, 3),
            },
            "commence":       event.get("commence_time"),
            "bookmakerCount": len(event.get("bookmakers", [])),
        }


async def get_match_odds(known_names: set[str] | None = None) -> dict | None:
    """
    Obtiene momios h2h para todos los partidos próximos del Mundial.

    Retorna un dict keyed por tupla (home_canonical, away_canonical) con:
      homeWin, draw (o None), awayWin, rawOdds, commence, bookmakerCount

    Retorna None si:
      - ODDS_API_KEY no está configurado
      - Error de red / API
      - Pre-torneo (no hay partidos programados aún)

    Caché TTL: MATCH_ODDS_TTL segundos.
    """
    cache_key = "match_odds"
    cached = _cache.get(cache_key)
    if cached and time.time() - cached["ts"] < MATCH_ODDS_TTL:
        return cached["data"]

    api_key = _api_key()
    if not api_key:
        logger.debug("ODDS_API_KEY no configurado — omitiendo fetch de momios de partido")
        return None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{_ODDS_BASE}/sports/{_SPORT_MATCH}/odds",
                params={
                    "apiKey":     api_key,
                    "regions":    "us,eu",
                    "markets":    "h2h",
                    "oddsFormat": "decimal",
                },
            )
            # Loguear quota restante para monitoreo
            remaining = resp.headers.get("x-requests-remaining", "?")
            used = resp.headers.get("x-requests-used", "?")
            logger.info("Odds-API match odds — requests usados: %s, restantes: %s", used, remaining)
            resp.raise_for_status()
            events = resp.json()
    except httpx.HTTPStatusError as exc:
        logger.warning("Odds-API error HTTP %s: %s", exc.response.status_code, exc.response.text[:200])
        return None
    except Exception as exc:
        logger.warning("Odds-API match odds fetch falló: %s", exc)
        return None

    if not events:
        logger.info("No hay partidos próximos del Mundial en Odds-API (pre-torneo o fuera de temporada)")
        _cache[cache_key] = {"data": None, "ts": time.time()}
        return None

    names = known_names or set()
    result: dict = {}
    for event in events:
        payload = _extract_h2h_odds(event, names)
        if payload is None:
            continue
        home = payload.pop("home")
        away = payload.pop("away")
        result[(home, away)] = payload

    logger.info("Odds-API: %d partidos con momios h2h cargados", len(result))
    _cache[cache_key] = {"data": result or None, "ts": time.time()}
    return result or None


async def get_outright_odds() -> dict | None:
    """
    Obtiene momios de ganador del torneo (outrights).

    Retorna dict keyed por nombre canónico del equipo con:
      prob (float 0-1), bestOdds (mejor momio decimal disponible)

    Retorna None si la key no está configurada o hay error.
    Caché TTL: OUTRIGHT_ODDS_TTL segundos (6 horas).
    """
    cache_key = "outright_odds"
    cached = _cache.get(cache_key)
    if cached and time.time() - cached["ts"] < OUTRIGHT_ODDS_TTL:
        return cached["data"]

    api_key = _api_key()
    if not api_key:
        logger.debug("ODDS_API_KEY no configurado — omitiendo fetch de outrights")
        return None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{_ODDS_BASE}/sports/{_SPORT_OUTRIGHT}/odds",
                params={
                    "apiKey":     api_key,
                    "regions":    "us,eu",
                    "markets":    "outrights",
                    "oddsFormat": "decimal",
                },
            )
            remaining = resp.headers.get("x-requests-remaining", "?")
            logger.info("Odds-API outrights — requests restantes: %s", remaining)
            resp.raise_for_status()
            events = resp.json()
    except Exception as exc:
        logger.warning("Odds-API outrights fetch falló: %s", exc)
        return None

    if not events:
        _cache[cache_key] = {"data": None, "ts": time.time()}
        return None

    # Recopilar el mejor momio (más alto = más favorable al apostador) por equipo
    team_best: dict[str, float] = {}
    for event in events:
        for book in event.get("bookmakers", []):
            for mkt in book.get("markets", []):
                if mkt["key"] != "outrights":
                    continue
                for outcome in mkt.get("outcomes", []):
                    t_name = outcome["name"]
                    price = float(outcome["price"])
                    if price > 1.0:
                        if t_name not in team_best or price > team_best[t_name]:
                            team_best[t_name] = price

    if not team_best:
        _cache[cache_key] = {"data": None, "ts": time.time()}
        return None

    # Importar nombres canónicos para el mapeo
    try:
        from app.services.team_data import TEAM_DATA
        known = set(TEAM_DATA.keys())
    except ImportError:
        known = set()

    teams = list(team_best.keys())
    odds_vals = [team_best[t] for t in teams]
    probs = no_vig_probs(odds_vals)

    result = {
        _canonical_name(t, known): {
            "prob":     round(probs[i], 4),
            "bestOdds": round(team_best[t], 2),
        }
        for i, t in enumerate(teams)
    }

    logger.info("Odds-API outrights: %d equipos con probabilidades de campeonato", len(result))
    _cache[cache_key] = {"data": result, "ts": time.time()}
    return result


def clear_cache() -> None:
    """Limpia el caché manualmente (útil para testing)."""
    _cache.clear()
