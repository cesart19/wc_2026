"""
map_squads.py — Completa player_club_map.json para selecciones WC 2026.

Aplica la receta validada en KOR/CZE (jornada 1) con el camino de menor
cuota: baja el squad nacional de API-Football (1 req por equipo),
concilia nombres contra el squad de football-data y resuelve el club de
cada faltante por id de jugador (1-3 req c/u). Evita las trampas
conocidas: búsqueda por nombre con homónimos paginados, mínimo de 4
caracteres y variantes de romanización.

Al final regenera squad_context_v3.json (afinidades por plantel).

Uso:
  cd backend && source venv/bin/activate
  python map_squads.py "Canada" "Bosnia-Herzegovina"
  python map_squads.py "Mexico" --dry-run
"""

import argparse
import json
import logging
import shutil
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("map_squads")
logging.getLogger("httpx").setLevel(logging.WARNING)

_SEASONS = ("2025", "2026", "2024")


def parse_args() -> argparse.Namespace:
    """Define y parsea los argumentos del CLI."""
    parser = argparse.ArgumentParser(
        description="Completa el mapeo de convocados WC 2026"
    )
    parser.add_argument(
        "teams", nargs="+", help="Selecciones (nombre football-data)"
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def fd_squads(team_names: list[str]) -> dict[str, list[dict]]:
    """Squads oficiales WC 2026 desde football-data.org."""
    import os

    r = httpx.get(
        os.getenv("FOOTBALL_API_URL", "") + "/competitions/WC/teams",
        headers={"X-Auth-Token": os.getenv("FOOTBALL_API_KEY", "")},
        params={"season": "2026"},
        timeout=20,
    )
    r.raise_for_status()
    return {
        t["name"]: t.get("squad", [])
        for t in r.json().get("teams", [])
        if t["name"] in team_names
    }


_NT_LEAGUE_MARKERS = (
    "friendlies",
    "world cup",
    "qualification",
    "nations league",
    "euro championship",
    "copa america",
    "gold cup",
    "afc asian cup",
    "africa cup",
)


def _drop_national_blocks(entry: dict) -> dict:
    """Filtra bloques de selección/juveniles de las stats de un jugador.

    Sin esto, _extract_apif_entry puede elegir el bloque con más minutos
    aunque sea de selección (caso Eustáquio → 'Canada' en Friendlies) y
    mapear al jugador a su selección en vez de a su club.
    """
    stats = [
        s
        for s in entry.get("statistics", [])
        if not any(
            m in (s.get("league", {}).get("name") or "").lower()
            for m in _NT_LEAGUE_MARKERS
        )
        and not (s.get("team", {}).get("name") or "").endswith(
            ("U17", "U19", "U20", "U21", "U23")
        )
    ]
    return {**entry, "statistics": stats}


def resolve_player(apif_id: int, ea) -> dict | None:
    """Resuelve club/liga de un jugador APIF probando temporadas.

    Último recurso: historial de transferencias (sin minutos).
    """
    for season in _SEASONS:
        data = ea._apif_get("/players", {"id": apif_id, "season": season})
        time.sleep(ea.RATE_PAUSE)
        if not data or not data.get("response"):
            continue
        raw = ea._extract_apif_entry(
            _drop_national_blocks(data["response"][0]), 0
        )
        if raw["club"]:
            raw["_season"] = season
            return raw
    tdata = ea._apif_get("/transfers", {"player": apif_id})
    time.sleep(ea.RATE_PAUSE)
    transfers = (tdata or {}).get("response", [])
    if transfers and transfers[0].get("transfers"):
        latest = sorted(
            transfers[0]["transfers"], key=lambda t: t["date"], reverse=True
        )[0]
        return {
            "name": "",
            "club": latest["teams"]["in"]["name"],
            "league": "",
            "league_code": "UNK",
            "tier": 4.0,
            "min_pct": None,
            "min_pct_source": f"apif_transfers:{latest['date']}",
            "_season": "transfers",
        }
    return None


def main() -> None:
    """Punto de entrada del CLI."""
    args = parse_args()
    sys.path.insert(0, str(Path(__file__).parent))
    import enrich_apif as ea
    from app.services.prematch_analysis import find_team_id, same_player

    pcm = json.loads(ea.MAP_PATH.read_text(encoding="utf-8"))
    squads = fd_squads(args.teams)
    new_entries: dict[str, dict] = {}

    for team in args.teams:
        squad = squads.get(team, [])
        if not squad:
            log.warning("%s: sin squad en football-data — salto", team)
            continue
        missing = [p for p in squad if str(p["id"]) not in pcm]
        log.info(
            "\n=== %s: %d convocados, %d sin mapear",
            team, len(squad), len(missing),
        )
        if not missing:
            continue

        apif_team_id = find_team_id(team)
        sq = ea._apif_get("/players/squads", {"team": apif_team_id})
        time.sleep(ea.RATE_PAUSE)
        apif_players = (
            sq["response"][0].get("players", [])
            if sq and sq.get("response")
            else []
        )

        for p in missing:
            fd_name = p["name"]
            cand = next(
                (a for a in apif_players if same_player(fd_name, a["name"])),
                None,
            )
            if cand is None:
                # Fallback: apellido exacto único dentro del squad
                surname = fd_name.split()[-1].lower()
                by_surname = [
                    a
                    for a in apif_players
                    if a["name"].split()[-1].lower() == surname
                ]
                cand = by_surname[0] if len(by_surname) == 1 else None
            if cand is None:
                # Fallback final: búsqueda global por apellido (perfiles).
                # APIF solo acepta búsquedas ASCII — fold de diacríticos.
                surname = ea._ascii_name(fd_name.split()[-1]).lower()
                prof = ea._apif_get(
                    "/players/profiles", {"search": surname}
                )
                time.sleep(ea.RATE_PAUSE)
                profs = (prof or {}).get("response", [])
                matches = [
                    pr["player"]
                    for pr in profs
                    if same_player(fd_name, pr["player"].get("name", ""))
                ]
                cand = matches[0] if len(matches) == 1 else None
            if cand is None:
                log.info("  ✗ %-26s sin match en squad APIF", fd_name)
                continue
            entry = resolve_player(cand["id"], ea)
            if entry is None:
                log.info("  ✗ %-26s (APIF %d) sin datos de club",
                         fd_name, cand["id"])
                continue
            new_entries[str(p["id"])] = {
                "name": entry["name"] or cand["name"],
                "club": entry["club"],
                "league": entry["league"],
                "league_code": entry["league_code"],
                "tier": entry["tier"],
                "min_pct": entry["min_pct"],
                "min_pct_source": entry["min_pct_source"],
            }
            log.info(
                "  ✓ %-26s → %-24s [%s] min=%s (temp %s)",
                fd_name, entry["club"], entry["league_code"],
                entry["min_pct"], entry["_season"],
            )

    log.info(
        "\nEncontrados %d — req APIF usadas: %d",
        len(new_entries), ea._req_count,
    )
    if args.dry_run:
        log.info("DRY-RUN — no se modificó player_club_map.json")
        return
    if new_entries:
        shutil.copy2(ea.MAP_PATH, ea.MAP_PATH.with_suffix(".json.bak"))
        pcm.update(new_entries)
        ea.MAP_PATH.write_text(
            json.dumps(pcm, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log.info("✓ player_club_map.json actualizado (+%d)", len(new_entries))
        ea.cmd_generate()
        log.info("✓ squad_context_v3.json regenerado")


if __name__ == "__main__":
    main()
