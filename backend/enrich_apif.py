"""
enrich_apif.py — Enriquece player_club_map.json con datos de API-Football.

Arquitectura en DOS FASES para minimizar llamadas API (100 req/día, 10 req/min):

  FASE 1 — cache: descarga todos los jugadores de ligas específicas y los
  guarda localmente en apif_cache/. Una liga de 18 equipos usa ~15-30 req.

  FASE 2 — match: lee del caché local y cruza contra los jugadores del WC
  sin mapear. NO consume req de API.

Uso:
  cd backend && source venv/bin/activate

  # Fase 1 — descargar ligas (elige las relevantes para el día)
  python enrich_apif.py cache --leagues 262,253     # Liga MX + MLS  (~45 req)
  python enrich_apif.py cache --leagues 30,17,292   # Saudi+J1+KLeague (~65 req)
  python enrich_apif.py cache --leagues 233,200,12  # CAF: Egypt+Maroc+Tunisia

  # Fase 2 — cruzar y enriquecer (0 req de API)
  python enrich_apif.py match                       # todos los equipos
  python enrich_apif.py match --teams Mexico,Canada,USA
  python enrich_apif.py match --dry-run             # sin guardar

  # Ver qué ligas están en caché
  python enrich_apif.py status

Requiere en backend/.env:
  APIF_KEY=tu_clave   ← dashboard.api-football.com/register (plan gratuito)

Mapa de IDs de liga (API-Football) — IDs VERIFICADOS:
  CONCACAF: 262=Liga MX  253=MLS  261=CPL
  AFC:      307=Saudi    98=J1    292=K-League  305=Qatar  290=Iran  542=Iraq  369=Uzbek
  CAF:      233=Egypt    200=Morocco  403=Senegal  570=Ghana  411=Camerún  12=Tunisia
  UEFA 2ª:  40=Championship  179=Scottish  203=Türkiye  144=Bélgica  218=Austria
  CONMEBOL: 71=Brasileirão  128=Argentina  239=Chile  242=Colombia  13=Libertadores
  OFC:      188=A-League
"""

import argparse
import json
import logging
import os
import sys
import time
import unicodedata
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

# ─────────────────────────── Configuración API-Football ──────────────────────

APIF_KEY  = os.getenv("APIF_KEY", "")
APIF_BASE = "https://v3.football.api-sports.io"
APIF_HDRS = {"x-apisports-key": APIF_KEY}

RATE_PAUSE    = 6.5   # segundos entre llamadas (10 req/min → 6s; +0.5 margen)
SEARCH_SEASON = "2024"
PLAYERS_PER_PAGE = 20  # el API devuelve 20 jugadores por página

# ─────────────────────────── Rutas ───────────────────────────────────────────

_HERE     = Path(__file__).parent
MAP_PATH  = _HERE / "app" / "services" / "player_club_map.json"
SC_PATH   = _HERE / "app" / "services" / "squad_context_v3.json"
SUPP_PATH = _HERE / "app" / "services" / "squad_supplement.json"
CACHE_DIR = _HERE / "apif_cache"   # directorio donde se guardan los jugadores descargados

FD_BASE = os.getenv("FOOTBALL_API_URL", "https://api.football-data.org/v4")
FD_HDRS = {"X-Auth-Token": os.getenv("FOOTBALL_API_KEY", "")}

# ─────────────────────────── Mapeo de ligas ──────────────────────────────────

APIF_LEAGUE_TO_CODE: dict[int, str] = {
    # ── UEFA Top 5 ──────────────────────────────────────────────────────────────
    39: "PL", 140: "PD", 78: "BL1", 135: "SA", 61: "FL1",
    # ── UEFA secundaria ─────────────────────────────────────────────────────────
    88: "DED", 94: "PPL", 40: "EFL", 179: "SCO", 203: "TUR",
    144: "BEL", 218: "AUT", 235: "RUS", 197: "GRE",
    113: "SWE", 119: "DEN", 103: "NOR", 169: "SUI",
    # ── CONCACAF ────────────────────────────────────────────────────────────────
    262: "LMX", 253: "MLS", 261: "CPL",
    # ── CONMEBOL ────────────────────────────────────────────────────────────────
    13: "CLI",   # ← CONMEBOL Libertadores (no es liga doméstica, pero tiene datos)
    128: "ARG", 71: "BSA", 239: "CHI", 242: "COL", 99: "PAR",
    # ── AFC — IDs CORRECTOS ─────────────────────────────────────────────────────
    307: "SAU",  # Saudi Pro League           ← correcto (era 30, que es WC Qual)
    98:  "JPN",  # J1 League (Japan)          ← correcto (era 17, que es AFC CL)
    292: "KOR",  # K League 1 (South Korea)   ← correcto ✓
    305: "QAT",  # Qatar Stars League         ← correcto (era 26, vieja copa)
    290: "IRN",  # Iran Persian Gulf Pro      ← correcto (era 13, Libertadores)
    542: "IRQ",  # Iraqi League               ← correcto (era 23, EAFF)
    369: "UZB",  # Uzbekistan Super League    ← correcto (era 323, India ISL)
    17: "AFC_CL",  # AFC Champions League Elite (útil como suplemento)
    # ── CAF — IDs CORRECTOS ─────────────────────────────────────────────────────
    233: "EGY",  # Egypt Premier League       ← correcto ✓
    200: "MAR",  # Morocco Botola Pro         ← correcto ✓
    403: "SEN",  # Senegal Ligue 1            ← correcto (era 202, incorrecto)
    570: "GHA",  # Ghana Premier League       ← correcto (era 207, incorrecto)
    411: "CMR",  # Cameroon Elite One         ← correcto (era 60, incorrecto)
    12:  "TUN",  # Tunisia Ligue Pro
    188: "AUS",  # A-League (Australia)       ← correcto ✓
    # ── CAF adicionales ─────────────────────────────────────────────────────────
    288: "RSA",  # South Africa Premier Soccer League
    # ── AFC adicionales ─────────────────────────────────────────────────────────
    387: "JOR",  # Jordan Pro League
    # ── UEFA Balcanes ───────────────────────────────────────────────────────────
    315: "BIH",  # Bosnia Premijer Liga
    # ── UEFA Centroeuropa ───────────────────────────────────────────────────────
    345: "CZE",  # Czech Fortuna Liga
    # ── Competiciones internacionales (útiles como suplemento) ──────────────────
    2:   "CL",   # UEFA Champions League
}

APIF_LEAGUE_MATCHES: dict[int, int] = {
    # UEFA Top 5
    39: 38, 140: 38, 78: 34, 135: 38, 61: 34,
    # UEFA secundaria
    88: 34, 94: 34, 40: 46, 179: 36, 203: 34,
    144: 30, 218: 32, 235: 30, 197: 26,
    113: 30, 119: 22, 103: 30, 169: 36,
    # CONCACAF
    262: 17, 253: 34, 261: 28,
    # CONMEBOL
    13: 8, 128: 28, 71: 38, 239: 30, 242: 20, 99: 28,
    # AFC (IDs correctos)
    307: 30, 98: 34, 292: 38, 305: 26, 290: 30, 542: 26, 369: 26,
    17: 8,   # AFC Champions League Elite
    # CAF (IDs correctos)
    233: 26, 200: 26, 403: 20, 570: 30, 411: 26, 12: 26, 188: 27,
    288: 30,  # South Africa PSL
    # AFC adicionales
    387: 26,  # Jordan Pro League
    # UEFA Balcanes
    315: 22,  # Bosnia Premijer Liga
    # UEFA Centroeuropa
    345: 30,  # Czech Fortuna Liga
    # UCL
    2: 8,
}

APIF_LEAGUE_TIER: dict[int, float] = {
    # UEFA Top 5
    39: 1.0, 140: 1.0, 78: 1.0, 135: 1.0, 61: 1.0,
    # UEFA secundaria
    88: 2.0, 94: 2.0, 40: 2.0, 179: 2.0, 203: 2.0,
    144: 2.0, 218: 2.5, 235: 2.5, 197: 2.5,
    113: 2.5, 119: 2.5, 103: 2.5, 169: 2.5,
    # CONCACAF
    262: 3.0, 253: 3.0, 261: 3.5,
    # CONMEBOL
    13: 2.5, 128: 3.0, 71: 3.0, 239: 3.5, 242: 3.5, 99: 3.0,
    # AFC (IDs correctos)
    307: 3.0, 98: 3.0, 292: 3.0, 305: 4.0, 290: 4.0, 542: 4.5, 369: 4.5,
    17: 2.0,  # AFC Champions League Elite
    # CAF (IDs correctos)
    233: 4.0, 200: 4.0, 403: 4.5, 570: 4.5, 411: 4.5, 12: 4.0, 188: 3.5,
    288: 4.5,  # South Africa PSL
    # AFC adicionales
    387: 5.0,  # Jordan Pro League
    # UEFA Balcanes
    315: 3.5,  # Bosnia Premijer Liga
    # UEFA Centroeuropa
    345: 2.5,  # Czech Fortuna Liga
    # UCL
    2: 1.0,
}

TEAM_CONFED: dict[str, str] = {
    "Mexico": "CONCACAF", "United States": "CONCACAF", "Canada": "CONCACAF",
    "Panama": "CONCACAF", "Haiti": "CONCACAF", "Curaçao": "CONCACAF",
    "Honduras": "CONCACAF", "Costa Rica": "CONCACAF",
    "Saudi Arabia": "AFC", "Iran": "AFC", "Qatar": "AFC",
    "Iraq": "AFC", "Uzbekistan": "AFC", "Jordan": "AFC",
    "South Korea": "AFC", "Japan": "AFC", "Australia": "AFC",
    "Senegal": "CAF", "Morocco": "CAF", "Tunisia": "CAF",
    "Egypt": "CAF", "Ghana": "CAF", "Nigeria": "CAF",
    "Cameroon": "CAF", "Cape Verde Islands": "CAF",
    "South Africa": "CAF", "Algeria": "CAF", "Congo DR": "CAF",
    "Ivory Coast": "CAF",
    "New Zealand": "OFC",
    "Scotland": "UEFA", "Bosnia-Herzegovina": "UEFA",
    "Turkey": "UEFA", "Sweden": "UEFA", "Norway": "UEFA",
}

# Ligas domésticas + europeas donde es probable que jueguen jugadores de cada confed.
# Se usan en la Fase 2 para priorizar matches del caché.
CONFED_PREFERRED_LEAGUES: dict[str, list[int]] = {
    "CONCACAF": [262, 253, 261, 39, 140, 78, 135, 61, 88, 94, 203, 144],
    # AFC: ligas domésticas primero (IDs correctos), luego UEFA top
    "AFC":      [307, 98, 292, 305, 290, 542, 369, 387, 17, 39, 140, 78, 135, 61, 88, 203],
    # CAF: ligas domésticas primero (IDs correctos), luego UEFA
    "CAF":      [233, 200, 403, 570, 411, 12, 288, 188, 39, 140, 78, 135, 61, 88, 94, 203],
    "UEFA":     [39, 140, 78, 135, 61, 88, 94, 203, 144, 218, 315, 40, 179, 103, 113, 119],
    "CONMEBOL": [71, 128, 239, 242, 13, 39, 140, 78, 135, 61, 88, 94],
    "OFC":      [188, 39, 88, 94, 203, 144],
    "OTHER":    [39, 140, 78, 135, 61, 88, 94, 253, 262, 307],
}

# ─────────────────────────── Helpers ─────────────────────────────────────────

def _normalize(name: str) -> str:
    nfkd = unicodedata.normalize("NFKD", name)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def _ascii_name(name: str) -> str:
    """Quita acentos y caracteres especiales — API-Football solo acepta alfanumérico."""
    nfkd = unicodedata.normalize("NFKD", name)
    return "".join(
        c for c in nfkd if not unicodedata.combining(c) and (c.isalnum() or c == " ")
    ).strip()


def _name_score(api_name: str, query_name: str) -> float:
    """
    Compara un nombre de API-Football (posiblemente abreviado: 'A. Vega')
    con un nombre completo de football-data.org ('Alexis Vega').

    Maneja tres casos:
      1. Nombre abreviado "X. Apellido"  → compara inicial + apellidos
      2. Nombres idénticos normalizados  → 1.0
      3. Overlap de palabras estándar    → fracción de palabras en común
    """
    a_norm = _normalize(api_name)    # ej. "a. vega"  /  "alexis vega"
    q_norm = _normalize(query_name)  # ej. "alexis vega"

    if a_norm == q_norm:
        return 1.0

    a_parts = a_norm.replace(".", "").split()  # ["a", "vega"]
    q_parts = q_norm.replace(".", "").split()  # ["alexis", "vega"]

    if not a_parts or not q_parts:
        return 0.0

    # Detectar nombre abreviado: primer token de 1 letra en el nombre de API
    a_is_abbrev = len(a_parts[0]) == 1 and len(a_parts) >= 2
    q_is_abbrev = len(q_parts[0]) == 1 and len(q_parts) >= 2

    if a_is_abbrev or q_is_abbrev:
        # Si uno está abreviado, comparar inicial + apellidos
        a_init = a_parts[0]
        q_init = q_parts[0][0] if q_parts else ""
        a_last = " ".join(a_parts[1:])
        q_last = " ".join(q_parts[1:])

        last_match = (a_last == q_last)
        init_match = (a_init == q_init)

        if init_match and last_match:
            return 0.92  # inicial + apellido exactos → match muy confiable
        if last_match:
            return 0.75  # apellido exacto aunque inicial difiera (ej. segundo nombre)
        # Overlap de apellidos (palabras compuestas)
        a_last_w = set(a_parts[1:])
        q_last_w = set(q_parts[1:])
        overlap = len(a_last_w & q_last_w) / max(len(a_last_w), len(q_last_w))
        if init_match and overlap > 0:
            return 0.55 + 0.35 * overlap
        return 0.35 * overlap

    # Caso estándar: overlap de todas las palabras
    a_words = set(a_parts)
    q_words = set(q_parts)
    return len(a_words & q_words) / max(len(a_words), len(q_words))


# ─────────────────────────── API helper ──────────────────────────────────────

_req_count = 0


class _DailyLimitError(Exception):
    """Se lanza cuando API-Football indica que el límite diario está agotado."""


def _apif_get(path: str, params: dict | None = None) -> dict | None:
    """
    Hace una llamada GET a API-Football.
    - Retorna el dict de respuesta si todo está bien.
    - Retorna None si la página tiene un error recuperable (error de datos, página vacía).
    - Lanza _DailyLimitError si el límite diario de 100 req está agotado.
    """
    global _req_count
    url = f"{APIF_BASE}{path}"
    for attempt in range(3):
        try:
            r = httpx.get(url, headers=APIF_HDRS, params=params or {}, timeout=20)
            _req_count += 1
            remaining = r.headers.get("x-ratelimit-requests-remaining", "?")
            if r.status_code == 429:
                log.warning("Rate limit (429) — esperando 65s… (req restantes hoy: %s)", remaining)
                time.sleep(65)
                continue
            r.raise_for_status()
            data = r.json()
            errors = data.get("errors", [])
            if errors and errors != []:
                err_str = str(errors).lower()
                # Detectar límite diario (clave "requests" en el dict de errores)
                if isinstance(errors, dict) and "requests" in errors:
                    log.error("API-Football — límite diario agotado: %s", errors)
                    log.error("  Req diarias: %s/%s — se renuevan a medianoche UTC",
                              data.get("requests", {}).get("current", "?"),
                              data.get("requests", {}).get("limit_day", 100))
                    raise _DailyLimitError("Límite diario de API-Football agotado")
                elif "limit" in err_str and "day" in err_str:
                    log.error("API-Football — límite diario (mensaje): %s", errors)
                    raise _DailyLimitError("Límite diario de API-Football agotado")
                else:
                    log.info("  API error (página saltada): %s", errors)
                    return None
            log.debug("GET %s → %d resultados (restantes: %s)",
                      path, len(data.get("response", [])), remaining)
            return data
        except _DailyLimitError:
            raise  # propagar para que cmd_cache pueda abortar limpiamente
        except httpx.HTTPStatusError as e:
            log.error("HTTP %s en %s", e.response.status_code, path)
            return None
        except Exception as e:
            log.warning("Error (intento %d): %s", attempt + 1, e)
            time.sleep(5)
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# FASE 1 — CACHE: descargar todos los jugadores de una liga
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_league_players(league_id: int) -> list[dict]:
    """
    Descarga todos los jugadores de una liga (paginado, 20 por página).
    Retorna lista de entradas completas con player + statistics.
    Las páginas con errores recuperables se saltan (no abortan la descarga).
    Lanza _DailyLimitError si el límite diario está agotado.
    """
    players: list[dict] = []
    page = 1
    total_pages = 1  # se actualiza tras la primera llamada
    consecutive_errors = 0
    MAX_CONSECUTIVE_ERRORS = 3

    while page <= total_pages:
        try:
            data = _apif_get("/players", {
                "league": league_id,
                "season": SEARCH_SEASON,
                "page":   page,
            })
        except _DailyLimitError:
            log.error("  ⛔ Límite diario agotado en página %d — guardando %d jugadores obtenidos",
                      page, len(players))
            raise  # re-propagar para que cmd_cache guarde lo acumulado y pare

        time.sleep(RATE_PAUSE)

        if not data:
            consecutive_errors += 1
            log.warning("  Página %d/%d: sin datos — error %d/%d",
                        page, total_pages, consecutive_errors, MAX_CONSECUTIVE_ERRORS)
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                log.error("  Demasiados errores consecutivos — abortando liga %d", league_id)
                break
            page += 1
            continue

        consecutive_errors = 0  # reset contador de errores

        if page == 1:
            paging = data.get("paging", {})
            total_pages = paging.get("total", 1)
            league_code = APIF_LEAGUE_TO_CODE.get(league_id, f"APIF_{league_id}")
            log.info("  Liga %d [%s]: %d páginas (~%d jugadores)",
                     league_id, league_code, total_pages, total_pages * PLAYERS_PER_PAGE)

        batch = data.get("response", [])
        players.extend(batch)
        log.info("  Página %d/%d — %d jugadores acumulados (req #%d)",
                 page, total_pages, len(players), _req_count)
        page += 1

    return players


def cmd_cache(league_ids: list[int], dry_run: bool = False) -> None:
    """Fase 1: descarga jugadores de las ligas indicadas y guarda en caché local."""
    if dry_run:
        log.info("DRY-RUN activo: no se guardarán archivos (pero sí se harán llamadas API)")
    CACHE_DIR.mkdir(exist_ok=True)

    daily_limit_hit = False
    for league_id in league_ids:
        if daily_limit_hit:
            log.warning("Saltando liga %d — límite diario ya agotado", league_id)
            continue

        cache_file = CACHE_DIR / f"league_{league_id}.json"
        league_code = APIF_LEAGUE_TO_CODE.get(league_id, f"APIF_{league_id}")

        if cache_file.exists():
            existing = json.loads(cache_file.read_text(encoding="utf-8"))
            log.info("Liga %d [%s]: ya en caché (%d jugadores) — skip",
                     league_id, league_code, len(existing))
            log.info("  Para re-descargar: elimina %s", cache_file.name)
            continue

        log.info("Descargando liga %d [%s]…", league_id, league_code)
        players: list[dict] = []
        try:
            players = fetch_league_players(league_id)
        except _DailyLimitError:
            daily_limit_hit = True
            # Guardar lo que se descargó antes del límite (si hay algo)
            if players and not dry_run:
                cache_file.write_text(json.dumps(players, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
                log.warning("  ⚠ Guardado parcial: %d jugadores (descarga incompleta)", len(players))
            log.error("  Límite diario agotado — correr mañana para completar ligas restantes")
            break

        log.info("  Total: %d jugadores", len(players))

        if not dry_run and players:
            cache_file.write_text(json.dumps(players, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
            log.info("  ✓ Guardado en %s (%d jugadores)", cache_file.name, len(players))
        elif dry_run:
            log.info("  DRY-RUN: no se guardó (habrían sido %d jugadores)", len(players))

    log.info("Fase 1 completa. Req usadas esta sesión: %d", _req_count)
    if not daily_limit_hit:
        log.info("Ahora corre: python enrich_apif.py match")


# ═══════════════════════════════════════════════════════════════════════════════
# FASE 2 — MATCH: cruzar WC players sin mapear contra el caché local
# ═══════════════════════════════════════════════════════════════════════════════

def load_cache() -> dict[int, list[dict]]:
    """Lee todos los archivos de caché disponibles. Retorna {league_id: [players]}."""
    cache: dict[int, list[dict]] = {}
    if not CACHE_DIR.exists():
        return cache
    for f in sorted(CACHE_DIR.glob("league_*.json")):
        try:
            lid = int(f.stem.replace("league_", ""))
            cache[lid] = json.loads(f.read_text(encoding="utf-8"))
            log.info("  Caché cargado: liga %d [%s] → %d jugadores",
                     lid, APIF_LEAGUE_TO_CODE.get(lid, "?"), len(cache[lid]))
        except Exception as e:
            log.warning("  Error leyendo %s: %s", f.name, e)
    return cache


def build_name_index(cache: dict[int, list[dict]]) -> dict[str, list[tuple]]:
    """
    Construye índice {clave_normalizada: [(league_id, entry), ...]}
    con múltiples claves por jugador para manejar nombres abreviados:
      - nombre completo normalizado:  "a. vega"
      - solo apellidos (sin inicial): "vega"         ← permite buscar por apellido
      - inicial+apellidos sin punto:  "a vega"
    """
    index: dict[str, list[tuple]] = {}

    def _add(key: str, lid: int, entry: dict) -> None:
        if key:
            index.setdefault(key, []).append((lid, entry))

    for lid, players in cache.items():
        for entry in players:
            p = entry.get("player", {})
            name = p.get("name", "")
            if not name:
                continue

            norm = _normalize(name)          # "a. vega"
            parts = norm.replace(".", "").split()  # ["a", "vega"]

            _add(norm, lid, entry)           # clave principal

            if len(parts) >= 2 and len(parts[0]) == 1:
                # Nombre abreviado: también indexar por apellidos solos y por "init apellidos"
                last_key = " ".join(parts[1:])   # "vega"
                init_key = " ".join(parts)       # "a vega"
                _add(last_key, lid, entry)
                _add(init_key, lid, entry)
            else:
                # Nombre completo: también indexar por apellidos (todos los tokens menos el primero)
                if len(parts) >= 2:
                    last_key = " ".join(parts[1:])
                    _add(last_key, lid, entry)

    total_keys = len(index)
    log.info("  Índice: %d claves únicas", total_keys)
    return index


def resolve_from_cache(
    fd_name: str,
    confed: str,
    index: dict[str, list[tuple]],
    cache: dict[int, list[dict]],
) -> dict | None:
    """
    Busca fd_name en el índice local.
    Prioriza las ligas de la confederación del equipo.
    Retorna el mejor match o None si ninguno supera el umbral.
    """
    preferred = CONFED_PREFERRED_LEAGUES.get(confed.upper(),
                CONFED_PREFERRED_LEAGUES["OTHER"])

    best_score   = 0.0
    best_entry   = None
    best_lid     = 0

    # Construir claves de búsqueda para fd_name
    norm_query = _normalize(fd_name)
    q_parts    = norm_query.replace(".", "").split()
    # Clave por apellidos (ej. "alexis vega" → buscar "vega" para encontrar "a. vega")
    q_last_key = " ".join(q_parts[1:]) if len(q_parts) >= 2 else ""

    # Candidatos del índice: exacto + por apellidos
    candidate_entries: list[tuple[int, dict]] = []
    for key in [norm_query, q_last_key]:
        if key:
            candidate_entries.extend(index.get(key, []))

    # Si hay candidatos del índice, evaluar con _name_score
    if candidate_entries:
        for entry_lid, entry in candidate_entries:
            api_name = entry.get("player", {}).get("name", "")
            score = _name_score(api_name, fd_name)
            if score > best_score:
                best_score = score
                best_entry = entry
                best_lid   = entry_lid

    # Si no hay candidatos suficientes, hacer fuzzy completo sobre ligas prioritarias
    if best_score < 0.60:
        for lid in preferred:
            if lid not in cache:
                continue
            for entry in cache[lid]:
                api_name = entry.get("player", {}).get("name", "")
                score = _name_score(api_name, fd_name)
                if score > best_score:
                    best_score = score
                    best_entry = entry
                    best_lid   = lid

    if best_score < 0.88 or best_entry is None:
        return None

    # Extraer estadísticas del mejor entry
    stats = best_entry.get("statistics", [])
    if not stats:
        return None

    # Elegir el stat con más minutos
    stat = max(stats, key=lambda s: s.get("games", {}).get("minutes") or 0)

    league_info = stat.get("league", {})
    team_info   = stat.get("team", {})
    games_info  = stat.get("games", {})

    # Usar el league_id de la estadística (puede diferir del liga buscada)
    stat_lid      = league_info.get("id", best_lid)
    league_code   = APIF_LEAGUE_TO_CODE.get(stat_lid, f"APIF_{stat_lid}")
    total_matches = APIF_LEAGUE_MATCHES.get(stat_lid, 30)
    tier          = APIF_LEAGUE_TIER.get(stat_lid, 4.0)

    minutes     = games_info.get("minutes") or 0
    appearances = games_info.get("appearences") or 0
    min_pct     = round(max(0.05, min(1.0, minutes / (total_matches * 90))), 3) if minutes > 0 else None

    return {
        "name":           best_entry["player"].get("name", fd_name),
        "club":           team_info.get("name", ""),
        "league":         league_info.get("name", ""),
        "league_code":    league_code,
        "tier":           tier,
        "min_pct":        min_pct,
        "min_pct_source": "apif_minutes" if minutes > 0 else "apif_no_minutes",
        "_match_score":   round(best_score, 2),
        "_minutes":       minutes,
        "_appearances":   appearances,
        "_cache_league":  best_lid,
    }


def _extract_apif_entry(apif_entry: dict, hint_league_id: int) -> dict:
    """Convierte un resultado de API-Football en un dict compatible con player_club_map."""
    stats = apif_entry.get("statistics", [])
    stat  = max(stats, key=lambda s: s.get("games", {}).get("minutes") or 0) if stats else {}

    league_info = stat.get("league", {})
    team_info   = stat.get("team", {})
    games_info  = stat.get("games", {})

    stat_lid      = league_info.get("id", hint_league_id)
    league_code   = APIF_LEAGUE_TO_CODE.get(stat_lid, f"APIF_{stat_lid}")
    total_matches = APIF_LEAGUE_MATCHES.get(stat_lid, 30)
    tier          = APIF_LEAGUE_TIER.get(stat_lid, 4.0)

    minutes     = games_info.get("minutes") or 0
    min_pct     = round(max(0.05, min(1.0, minutes / (total_matches * 90))), 3) if minutes > 0 else None

    return {
        "name":           apif_entry["player"].get("name", ""),
        "club":           team_info.get("name", ""),
        "league":         league_info.get("name", ""),
        "league_code":    league_code,
        "tier":           tier,
        "min_pct":        min_pct,
        "min_pct_source": "apif_minutes" if minutes > 0 else "apif_no_minutes",
        "_minutes":       minutes,
        "_appearances":   games_info.get("appearences") or 0,
        "_stat_league_id": stat_lid,
    }


def search_player_live(
    fd_name: str,
    confed: str,
    min_score: float = 0.60,
) -> tuple[dict | None, float, int]:
    """
    Busca un jugador por nombre en API-Football (llamadas live).
    Prueba las ligas preferidas de la confederación en orden.
    Retorna (entry, match_score, league_id_used) o (None, 0.0, 0).
    Lanza _DailyLimitError si se agota el límite diario.
    """
    preferred = CONFED_PREFERRED_LEAGUES.get(confed.upper(),
                CONFED_PREFERRED_LEAGUES["OTHER"])
    ascii_q = _ascii_name(fd_name)
    if not ascii_q:
        return None, 0.0, 0

    for league_id in preferred:
        try:
            data = _apif_get("/players", {
                "search": ascii_q,
                "league": league_id,
                "season": SEARCH_SEASON,
            })
        except _DailyLimitError:
            raise
        time.sleep(RATE_PAUSE)

        if data is None:
            continue  # error de página, probar siguiente liga

        response = data.get("response", [])
        if not response:
            continue

        # Encontrar mejor match por nombre
        best_entry = None
        best_score = 0.0
        for entry in response:
            api_name = entry.get("player", {}).get("name", "")
            sc = _name_score(api_name, fd_name)
            if sc > best_score:
                best_score = sc
                best_entry = entry

        if best_score >= min_score and best_entry is not None:
            return _extract_apif_entry(best_entry, league_id), best_score, league_id

    return None, 0.0, 0


def cmd_search(
    target_teams: list[str] | None,
    dry_run: bool,
    min_score: float = 0.60,
) -> None:
    """
    Busca jugadores sin mapear en API-Football por nombre (llamadas live).
    Útil cuando el caché de liga está vacío o el plan gratuito limita las páginas.
    Usa ~1-3 req por jugador (una por liga intentada hasta encontrar match).
    """
    log.info("Cargando player_club_map.json…")
    pcm: dict = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    log.info("  %d jugadores mapeados", len(pcm))

    squads = load_wc_squads()

    # Recopilar jugadores sin mapear
    unmapped: list[tuple[str, int, str]] = []
    for team_name, squad in squads.items():
        if target_teams and team_name not in target_teams:
            continue
        for p in squad:
            if str(p["id"]) not in pcm:
                unmapped.append((team_name, p["id"], p["name"]))

    unmapped.sort(key=lambda x: (TEAM_CONFED.get(x[0], "ZZZ"), x[0], x[2]))
    log.info("Jugadores sin mapear (en equipos target): %d", len(unmapped))
    log.info("Estimado de req API: %d–%d (1-3 por jugador × %d jugadores)",
             len(unmapped), len(unmapped) * 3, len(unmapped))
    log.info("─" * 65)

    new_entries: dict[str, dict] = {}
    not_found = 0

    try:
        for team_name, fd_id, fd_name in unmapped:
            pid_str = str(fd_id)
            confed  = TEAM_CONFED.get(team_name, "OTHER")

            entry, match_score, lid_used = search_player_live(fd_name, confed, min_score)

            if entry is None:
                log.info("  ✗ %-28s (%s) — sin match", fd_name, team_name)
                not_found += 1
                continue

            new_entries[pid_str] = {
                "name":           entry["name"],
                "club":           entry["club"],
                "league":         entry["league"],
                "league_code":    entry["league_code"],
                "tier":           entry["tier"],
                "min_pct":        entry["min_pct"],
                "min_pct_source": entry["min_pct_source"],
            }
            log.info("  ✓ %-28s → %-22s @ %-5s  min=%.0f%%  match=%.0f%%  (req #%d)",
                     fd_name, entry["name"], entry["league_code"],
                     (entry["min_pct"] or 0) * 100,
                     match_score * 100,
                     _req_count)

    except _DailyLimitError:
        log.error("⛔ Límite diario agotado — %d jugadores buscados, %d encontrados",
                  len(new_entries) + not_found, len(new_entries))
        log.error("  Corre mañana para continuar. Guardando lo encontrado hasta ahora…")

    log.info("─" * 65)
    log.info("Resultado: %d encontrados  |  %d sin match  |  req usadas: %d",
             len(new_entries), not_found, _req_count)

    if dry_run:
        log.info("DRY-RUN — no se modificó player_club_map.json")
        return

    if not new_entries:
        log.info("Sin entradas nuevas.")
        return

    import shutil
    shutil.copy2(MAP_PATH, MAP_PATH.with_suffix(".json.bak"))
    pcm.update(new_entries)
    MAP_PATH.write_text(json.dumps(pcm, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("✓ player_club_map.json: %d jugadores (+%d nuevos)", len(pcm), len(new_entries))


def load_wc_squads() -> dict[str, list[dict]]:
    log.info("Obteniendo squads WC 2026 desde football-data.org…")
    r = httpx.get(f"{FD_BASE}/competitions/WC/teams",
                  headers=FD_HDRS, params={"season": "2026"}, timeout=20)
    r.raise_for_status()
    teams = r.json().get("teams", [])
    squads: dict[str, list[dict]] = {}
    for t in teams:
        name  = t.get("name", "TBD")
        squad = [{"id": p["id"], "name": p["name"]} for p in t.get("squad", [])]
        squads[name] = squad
    log.info("  %d equipos, %d jugadores totales",
             len(squads), sum(len(s) for s in squads.values()))
    return squads


def cmd_match(
    target_teams: list[str] | None,
    dry_run: bool,
    min_score: float = 0.60,
) -> None:
    """Fase 2: cruza jugadores sin mapear contra el caché local."""
    log.info("Cargando caché de ligas…")
    cache = load_cache()
    if not cache:
        log.error("Caché vacío — ejecuta primero: python enrich_apif.py cache --leagues 262,253,...")
        sys.exit(1)

    total_cached = sum(len(v) for v in cache.values())
    log.info("  Caché total: %d jugadores en %d ligas", total_cached, len(cache))

    log.info("Construyendo índice de nombres…")
    index = build_name_index(cache)
    log.info("  Índice: %d nombres únicos", len(index))

    log.info("Cargando player_club_map.json…")
    pcm: dict = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    log.info("  %d jugadores mapeados", len(pcm))

    squads = load_wc_squads()

    # Recopilar jugadores sin mapear
    unmapped: list[tuple[str, int, str]] = []
    for team_name, squad in squads.items():
        if target_teams and team_name not in target_teams:
            continue
        for p in squad:
            if str(p["id"]) not in pcm:
                unmapped.append((team_name, p["id"], p["name"]))

    unmapped.sort(key=lambda x: (TEAM_CONFED.get(x[0], "ZZZ"), x[0], x[2]))
    log.info("Jugadores sin mapear (en equipos target): %d", len(unmapped))
    log.info("─" * 65)

    new_entries: dict[str, dict] = {}
    not_found = 0

    for team_name, fd_id, fd_name in unmapped:
        pid_str = str(fd_id)
        confed  = TEAM_CONFED.get(team_name, "OTHER")
        resolved = resolve_from_cache(fd_name, confed, index, cache)

        if resolved is None or resolved["_match_score"] < min_score:
            log.info("  ✗ %s (%s) — sin match (necesita caché de más ligas)",
                     fd_name, team_name)
            not_found += 1
            continue

        entry = {
            "name":           resolved["name"],
            "club":           resolved["club"],
            "league":         resolved["league"],
            "league_code":    resolved["league_code"],
            "tier":           resolved["tier"],
            "min_pct":        resolved["min_pct"],
            "min_pct_source": resolved["min_pct_source"],
        }
        log.info("  ✓ %s (%s) → %s @ %s [%s]  min_pct=%s  match=%.0f%%",
                 fd_name, team_name,
                 resolved["name"], resolved["club"], resolved["league_code"],
                 f"{resolved['min_pct']:.3f}" if resolved["min_pct"] else "None",
                 resolved["_match_score"] * 100)
        new_entries[pid_str] = entry

    log.info("─" * 65)
    log.info("Resultado: %d encontrados  |  %d sin match", len(new_entries), not_found)

    if dry_run:
        log.info("DRY-RUN — no se modificó player_club_map.json")
        return

    if not new_entries:
        log.info("Sin entradas nuevas.")
        return

    import shutil
    shutil.copy2(MAP_PATH, MAP_PATH.with_suffix(".json.bak"))
    pcm.update(new_entries)
    MAP_PATH.write_text(json.dumps(pcm, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("✓ player_club_map.json: %d jugadores (+%d nuevos)", len(pcm), len(new_entries))


# ═══════════════════════════════════════════════════════════════════════════════
# STATUS
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_status() -> None:
    """Muestra qué ligas están en caché y cuántos jugadores sin mapear quedan."""
    pcm = json.loads(MAP_PATH.read_text(encoding="utf-8"))

    print("\n── Caché de ligas ───────────────────────────────────")
    if CACHE_DIR.exists():
        for f in sorted(CACHE_DIR.glob("league_*.json")):
            lid = int(f.stem.replace("league_", ""))
            players = json.loads(f.read_text(encoding="utf-8"))
            code = APIF_LEAGUE_TO_CODE.get(lid, "?")
            size_kb = f.stat().st_size // 1024
            print(f"  Liga {lid:4d} [{code:<5}]  {len(players):4d} jugadores  ({size_kb} KB)")
    else:
        print("  (vacío — ejecuta: python enrich_apif.py cache --leagues 262,253,...)")

    # Contar unmapped por confederación
    try:
        r = httpx.get(f"{FD_BASE}/competitions/WC/teams",
                      headers=FD_HDRS, params={"season": "2026"}, timeout=20)
        teams = r.json().get("teams", [])
        sc_data = json.loads(SC_PATH.read_text(encoding="utf-8")) if SC_PATH.exists() else []
        confed_map = {e["team"]: e.get("confed","?") for e in sc_data}

        from collections import defaultdict
        unmapped_by_confed: dict[str, int] = defaultdict(int)
        for t in teams:
            name = t.get("name","")
            conf = TEAM_CONFED.get(name, confed_map.get(name, "?"))
            for p in t.get("squad", []):
                if str(p["id"]) not in pcm:
                    unmapped_by_confed[conf] += 1

        print("\n── Jugadores sin mapear por confederación ───────────")
        total = 0
        for conf, n in sorted(unmapped_by_confed.items()):
            print(f"  {conf:<12}  {n:3d} jugadores")
            total += n
        print(f"  {'TOTAL':<12}  {total:3d} jugadores")
    except Exception as e:
        print(f"  (no se pudo consultar WC teams: {e})")

    print()


# ═══════════════════════════════════════════════════════════════════════════════
# GENERATE: regenerar squad_context_v3.json desde player_club_map.json actualizado
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_generate() -> None:
    """
    Regenera squad_context_v3.json para las 48 selecciones WC 2026.

    Lee player_club_map.json y llama a squad_context_score() de club_ratings.py
    para cada selección. Guarda el resultado en squad_context_v3.json.

    Formato de salida (compatible con forecasting.py):
      [{team, squad_context_score, raw_score, coverage, mapped, total,
        confed, affinity_score, top_players[{name, club, league, score, min_pct}]}, ...]
    Ordenado por squad_context_score descendente.
    """
    import sys as _sys
    _sys.path.insert(0, str(_HERE))
    from app.services.club_ratings import squad_context_score

    log.info("Regenerando squad_context_v3.json…")

    pcm  = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    log.info("  player_club_map.json: %d jugadores", len(pcm))

    squads = load_wc_squads()

    # Aplicar suplemento manual: jugadores que están en player_club_map.json
    # pero no aparecen en el squad oficial de la API (squad incompleto en fd.org)
    if SUPP_PATH.exists():
        supp = json.loads(SUPP_PATH.read_text(encoding="utf-8"))
        for team_name, extra_ids in supp.items():
            if team_name.startswith("_"):
                continue   # ignorar claves de comentario
            if team_name not in squads:
                log.warning("  squad_supplement: equipo '%s' no encontrado en WC squads", team_name)
                continue
            existing_ids = {p["id"] for p in squads[team_name]}
            added = 0
            for pid in extra_ids:
                if pid not in existing_ids and str(pid) in pcm:
                    squads[team_name].append({
                        "id":   pid,
                        "name": pcm[str(pid)].get("name", str(pid)),
                    })
                    added += 1
            if added:
                log.info("  squad_supplement: +%d jugadores añadidos a %s", added, team_name)

    results: list[dict] = []
    for team_name, squad in sorted(squads.items()):
        confed = TEAM_CONFED.get(team_name, "UEFA")
        ctx = squad_context_score(squad, pcm)

        # Filtrar top_players (detalles de los 5 mejores mapeados)
        top_players = [
            {
                "name":    d["name"],
                "club":    d["club"],
                "league":  d["league"],
                "score":   d["score"],
                "min_pct": d.get("min_pct"),
            }
            for d in ctx["details"][:5]
        ]

        raw_score = ctx["score"]
        # Ajuste de cobertura: penalizar fuertemente equipos con baja cobertura.
        # Con coverage=1.0 → factor=1.0 (sin penalización)
        # Con coverage=0.7 → factor=0.93 (penalización leve — mayoría mapeada)
        # Con coverage=0.3 → factor=0.70 (penalización moderada — datos parciales)
        # Con coverage=0.1 → factor=0.50 (penalización fuerte — casi sin datos)
        # Con coverage=0.0 → factor=0.0  (sin datos → score=0)
        # Fórmula: factor = coverage^0.45 (curva cóncava)
        cov = ctx["coverage"]
        coverage_factor = cov ** 0.45 if cov > 0 else 0.0
        adj_score = round(raw_score * coverage_factor, 2)

        results.append({
            "team":               team_name,
            "squad_context_score": adj_score,
            "raw_score":          raw_score,
            "coverage":           ctx["coverage"],
            "mapped":             ctx["mapped"],
            "total":              ctx["total"],
            "confed":             confed,
            "affinity_score":     ctx["affinity_score"],
            "top5_pct":           ctx["top5_pct"],
            "top_players":        top_players,
        })

    results.sort(key=lambda x: x["squad_context_score"], reverse=True)

    SC_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("✓ squad_context_v3.json: %d equipos", len(results))

    # Mostrar ranking resumido
    log.info("\n── Ranking de contexto de plantillas ──────────────────────")
    for i, r in enumerate(results, 1):
        log.info("  %2d. %-25s  score=%5.1f  raw=%5.1f  cov=%.0f%%  [%s]",
                 i, r["team"], r["squad_context_score"], r["raw_score"],
                 r["coverage"] * 100, r["confed"])


# ─────────────────────────── Main ────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enriquece player_club_map.json con API-Football (2 fases)"
    )
    sub = parser.add_subparsers(dest="cmd")

    # cache
    p_cache = sub.add_parser("cache", help="Fase 1: descargar jugadores de ligas")
    p_cache.add_argument("--leagues", required=True,
                         help="IDs de ligas separados por coma, e.g. 262,253")
    p_cache.add_argument("--dry-run", action="store_true")

    # match
    p_match = sub.add_parser("match", help="Fase 2: cruzar contra caché local (0 req API)")
    p_match.add_argument("--teams", default="",
                         help="Equipos a procesar, e.g. 'Mexico,Canada,USA'")
    p_match.add_argument("--dry-run", action="store_true")
    p_match.add_argument("--min-score", type=float, default=0.60,
                         help="Umbral de similitud de nombre (default: 0.60)")

    # search (búsqueda live por nombre, útil en plan gratuito o para equipos específicos)
    p_search = sub.add_parser("search",
        help="Busca jugadores por nombre en API-Football (llamadas live, ~1-3 req/jugador)")
    p_search.add_argument("--teams", default="",
                          help="Equipos a procesar, e.g. 'Mexico,Canada,USA'")
    p_search.add_argument("--dry-run", action="store_true")
    p_search.add_argument("--min-score", type=float, default=0.60,
                          help="Umbral de similitud de nombre (default: 0.60)")

    # status
    sub.add_parser("status", help="Ver caché disponible y jugadores sin mapear")

    # generate
    sub.add_parser("generate",
        help="Regenerar squad_context_v3.json desde player_club_map.json actualizado")

    args = parser.parse_args()

    if not args.cmd:
        parser.print_help()
        print("\nEjemplo rápido (plan Pro — sin límite de páginas):")
        print("  python enrich_apif.py cache --leagues 262,253,261   # CONCACAF")
        print("  python enrich_apif.py cache --leagues 30,17,292     # AFC")
        print("  python enrich_apif.py match                          # cruzar todo")
        print("\nEjemplo rápido (plan Free — 3 páginas/liga):")
        print("  python enrich_apif.py search --teams Mexico,Canada,USA")
        return

    if args.cmd in ("cache", "search") and not APIF_KEY:
        log.error("APIF_KEY no configurada en .env")
        sys.exit(1)

    if args.cmd == "cache":
        league_ids = [int(x.strip()) for x in args.leagues.split(",") if x.strip()]
        cmd_cache(league_ids, dry_run=args.dry_run)

    elif args.cmd == "match":
        target_teams = [t.strip() for t in args.teams.split(",") if t.strip()] or None
        cmd_match(target_teams, dry_run=args.dry_run, min_score=args.min_score)

    elif args.cmd == "search":
        target_teams = [t.strip() for t in args.teams.split(",") if t.strip()] or None
        cmd_search(target_teams, dry_run=args.dry_run, min_score=args.min_score)

    elif args.cmd == "status":
        cmd_status()

    elif args.cmd == "generate":
        cmd_generate()


if __name__ == "__main__":
    main()
