"""
enrich_minutes.py — Enriquece player_club_map.json con min_pct.

Estrategia:
  1. Llama a /competitions/{code}/scorers para cada liga (limit=100)
     → playedMatches = apariciones individuales del jugador en la competición
     → min_pct = playedMatches / total_matches_per_team_in_league
  2. Llama a /competitions/{code}/teams para cada liga
     → position = posición del jugador (Goalkeeper / Defence / Midfielder / Offence)
  3. Para jugadores no en scorers pero con posición conocida:
     → min_pct por defecto según posición (WC players son casi siempre titulares)
  4. Jugadores sin datos → min_pct = None (la fórmula usa 0.80 como default)

Presupuesto de API: ~18 llamadas (9 scorers + 9 teams) — tier gratuito (10 req/min)
Tiempo estimado: ~2.5 minutos (con pausa de 7s entre llamadas)

Uso:
  cd backend && source venv/bin/activate
  python enrich_minutes.py [--dry-run]
"""

import os
import sys
import json
import time
import logging
import argparse
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ─────────────────────────── Configuración ───────────────────────────────────

API_KEY  = os.getenv("FOOTBALL_API_KEY", "")
BASE_URL = os.getenv("FOOTBALL_API_URL", "https://api.football-data.org/v4")
HEADERS  = {"X-Auth-Token": API_KEY}

MAP_PATH = Path(__file__).parent / "app" / "services" / "player_club_map.json"

# Competiciones a consultar y partidos totales por equipo en 2024-25
# (total de jornadas de liga → denominador para min_pct)
COMPETITIONS: dict[str, int] = {
    "PL":  38,   # Premier League
    "PD":  38,   # La Liga
    "BL1": 34,   # Bundesliga
    "SA":  38,   # Serie A
    "FL1": 34,   # Ligue 1
    "BSA": 38,   # Brasileirão
    "DED": 34,   # Eredivisie
    "PPL": 34,   # Primeira Liga
    "CL":   8,   # UCL (fase de liga 2024-25; no incluye playoff/KO para evitar sesgo)
}

# Defaults de min_pct por posición para jugadores WC sin datos de scorers.
# Cubre tanto las categorías amplias del API como las sub-posiciones granulares.
# Los jugadores de Copa del Mundo son casi siempre titulares en sus clubes.
POSITION_DEFAULTS: dict[str | None, float] = {
    # Porteros
    "Goalkeeper":         0.82,
    # Defensas (amplio + sub-posiciones)
    "Defence":            0.78,
    "Centre-Back":        0.78,
    "Right-Back":         0.78,
    "Left-Back":          0.78,
    "Right Centre Back":  0.78,
    "Left Centre Back":   0.78,
    # Mediocampistas
    "Midfield":           0.74,
    "Midfielder":         0.74,
    "Central Midfield":   0.74,
    "Defensive Midfield": 0.74,
    "Right Midfield":     0.74,
    "Left Midfield":      0.74,
    # Mediapuntas / wingers (entre mediocampista y delantero)
    "Attacking Midfield": 0.73,
    "Left Winger":        0.73,
    "Right Winger":       0.73,
    "Second Striker":     0.72,
    # Delanteros
    "Offence":            0.72,
    "Centre-Forward":     0.72,
    "Striker":            0.72,
    None:                 0.76,   # posición desconocida
}

RATE_LIMIT_PAUSE = 7.0   # segundos entre llamadas (tier gratuito: 10 req/min)
SCORER_LIMIT     = 100   # máximo de scorers a pedir por competición

# ─────────────────────────── Helpers de API ──────────────────────────────────

def _get(path: str, params: dict | None = None) -> dict | list | None:
    """GET con reintentos simples y respeto al rate limit."""
    url = f"{BASE_URL}{path}"
    for attempt in range(3):
        try:
            r = httpx.get(url, headers=HEADERS, params=params or {}, timeout=15)
            remaining = r.headers.get("X-Requests-Available-Minute", "?")
            if r.status_code == 429:
                log.warning("Rate limit alcanzado, esperando 60s…")
                time.sleep(60)
                continue
            r.raise_for_status()
            log.debug("GET %s  →  %s  (quedan %s req/min)", path, r.status_code, remaining)
            return r.json()
        except httpx.HTTPStatusError as e:
            log.error("HTTP %s en %s: %s", e.response.status_code, path, e.response.text[:120])
            return None
        except Exception as e:
            log.warning("Error en %s (intento %d): %s", path, attempt + 1, e)
            time.sleep(5)
    return None


def _pause(msg: str = "") -> None:
    if msg:
        log.info(msg)
    time.sleep(RATE_LIMIT_PAUSE)


# ─────────────────────────── Paso 1: Scorers ─────────────────────────────────

def fetch_scorers(code: str, total_matches: int) -> dict[int, float]:
    """
    Retorna dict {player_id: min_pct} para la competición dada.
    min_pct = playedMatches / total_matches (clamped a [0.05, 1.0]).
    """
    log.info("Scorers %s (total_matches=%d)…", code, total_matches)
    data = _get(f"/competitions/{code}/scorers", {"season": "2024", "limit": SCORER_LIMIT})
    _pause()
    if not data:
        return {}

    result: dict[int, float] = {}
    for scorer in data.get("scorers", []):
        pid   = scorer.get("player", {}).get("id")
        pm    = scorer.get("playedMatches", 0)
        if pid is None or total_matches == 0:
            continue
        min_pct = round(max(0.05, min(1.0, pm / total_matches)), 3)
        result[pid] = min_pct

    log.info("  → %d jugadores con datos de apariciones", len(result))
    return result


# ─────────────────────────── Paso 2: Posiciones ──────────────────────────────

def fetch_positions(code: str) -> dict[int, str]:
    """
    Retorna dict {player_id: position} para todos los jugadores de la competición.
    Position valores: "Goalkeeper" | "Defence" | "Midfielder" | "Offence"
    """
    log.info("Equipos/posiciones %s…", code)
    data = _get(f"/competitions/{code}/teams", {"season": "2024"})
    _pause()
    if not data:
        return {}

    result: dict[int, str] = {}
    for team in data.get("teams", []):
        for player in team.get("squad", []):
            pid = player.get("id")
            pos = player.get("position")   # e.g. "Goalkeeper", "Defence", etc.
            if pid is not None and pos:
                result[pid] = pos

    log.info("  → %d jugadores con posición conocida", len(result))
    return result


# ─────────────────────────── Enriquecimiento ─────────────────────────────────

def enrich(player_map: dict, dry_run: bool = False) -> dict:
    """
    Enriquece player_map con min_pct calculado o estimado.
    Retorna el mapa enriquecido y un resumen de cobertura.
    """
    # Índices agregados de todas las competiciones
    all_scorer_data: dict[int, float] = {}      # pid → min_pct (real)
    all_positions:   dict[int, str]   = {}      # pid → position

    # Itera competiciones en orden para respetar el rate limit
    for code, total in COMPETITIONS.items():
        scorers   = fetch_scorers(code, total)
        positions = fetch_positions(code)
        all_scorer_data.update(scorers)
        # No sobreescribir posiciones ya conocidas (misma persona en varias competiciones)
        for pid, pos in positions.items():
            all_positions.setdefault(pid, pos)

    log.info("Datos recopilados: %d con apariciones reales, %d con posición",
             len(all_scorer_data), len(all_positions))

    # Enriquece cada jugador del mapa
    stats = {"real": 0, "position_default": 0, "global_default": 0, "total": len(player_map)}
    enriched = {}
    for pid_str, info in player_map.items():
        pid = int(pid_str)
        entry = dict(info)

        if pid in all_scorer_data:
            # Dato real de apariciones
            entry["min_pct"]         = all_scorer_data[pid]
            entry["min_pct_source"]  = "scorers_api"
            stats["real"] += 1
        elif pid in all_positions:
            # Default por posición (WC player = casi siempre titular)
            pos    = all_positions[pid]
            mp     = POSITION_DEFAULTS.get(pos, POSITION_DEFAULTS[None])
            entry["min_pct"]         = mp
            entry["min_pct_source"]  = f"position_default:{pos}"
            stats["position_default"] += 1
        else:
            # Sin datos — la fórmula usará 0.80 como default global
            entry["min_pct"]         = None
            entry["min_pct_source"]  = "global_default"
            stats["global_default"] += 1

        enriched[pid_str] = entry

    # Resumen de cobertura
    real_pct = stats["real"] / stats["total"] * 100
    pos_pct  = stats["position_default"] / stats["total"] * 100
    glob_pct = stats["global_default"] / stats["total"] * 100
    log.info(
        "Cobertura: %.1f%% real (%d)  |  %.1f%% pos-default (%d)  |  %.1f%% global-default (%d)",
        real_pct, stats["real"],
        pos_pct,  stats["position_default"],
        glob_pct, stats["global_default"],
    )

    return enriched, stats


# ─────────────────────────── Main ────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Enriquece player_club_map.json con min_pct")
    parser.add_argument("--dry-run", action="store_true",
                        help="No escribir el archivo — solo mostrar estadísticas")
    args = parser.parse_args()

    if not API_KEY:
        log.error("FOOTBALL_API_KEY no configurada en .env — abortando")
        sys.exit(1)

    log.info("Cargando %s …", MAP_PATH)
    with open(MAP_PATH, encoding="utf-8") as f:
        player_map = json.load(f)
    log.info("  %d jugadores cargados", len(player_map))

    log.info("Iniciando enriquecimiento (%d competiciones, ~%.0f min con rate limit)…",
             len(COMPETITIONS), len(COMPETITIONS) * 2 * RATE_LIMIT_PAUSE / 60)

    enriched, stats = enrich(player_map, dry_run=args.dry_run)

    # Mostrar muestra de resultados
    sample_names = [
        "3189",   # Kepa Arrizabalaga
        "3754",   # Mohamed Salah
        "44",     # Cristiano Ronaldo
        "73",     # Lionel Messi
        "9692",   # Vinicius Jr
        "129591", # Bellingham
    ]
    log.info("\n── Muestra de jugadores enriquecidos ──")
    for pid_str in sample_names:
        if pid_str in enriched:
            e = enriched[pid_str]
            log.info("  %s  (%s @ %s)  min_pct=%.3f  [%s]",
                     e["name"], e.get("league_code", "?"), e["club"],
                     e["min_pct"] if e["min_pct"] is not None else 0.80,
                     e["min_pct_source"])

    if args.dry_run:
        log.info("DRY-RUN: no se escribió ningún archivo")
        return

    # Guardar archivo enriquecido
    backup = MAP_PATH.with_suffix(".json.bak")
    import shutil
    shutil.copy2(MAP_PATH, backup)
    log.info("Backup guardado en %s", backup)

    with open(MAP_PATH, "w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)
    log.info("✓ %s actualizado con %d jugadores", MAP_PATH.name, len(enriched))
    log.info("  Real: %d | Pos-default: %d | Global-default: %d",
             stats["real"], stats["position_default"], stats["global_default"])


if __name__ == "__main__":
    main()
