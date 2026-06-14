"""
Endpoints de momios de casas de apuestas.

GET /odds           — momios h2h actuales para partidos próximos del Mundial
GET /odds/outrights — momios de ganador del torneo por equipo

Ambos endpoints sirven desde caché y retornan available: false en lugar de
error 5xx cuando la API no está disponible o la key no está configurada.
"""

from fastapi import APIRouter, HTTPException
from app.services.odds_api import get_match_odds, get_outright_odds
from app.services.team_data import TEAM_DATA

router = APIRouter()


@router.get("/odds")
async def match_odds():
    """
    Momios h2h actuales del Mundial con probabilidades justas (sin vig).

    Respuesta cuando hay datos:
      available: true
      matches: [{home, away, homeWin, draw, awayWin, rawOdds, commence, bookmakerCount}]

    Respuesta cuando no hay datos (key ausente, pre-torneo, error de red):
      available: false
      matches: []
      note: razón
    """
    try:
        known = set(TEAM_DATA.keys())
        data = await get_match_odds(known_names=known)

        if data is None:
            return {
                "available": False,
                "matches": [],
                "note": "Sin momios disponibles (key no configurada, pre-torneo o error de red)",
            }

        matches = [
            {
                "home":           home,
                "away":           away,
                "homeWin":        payload["homeWin"],
                "draw":           payload["draw"],
                "awayWin":        payload["awayWin"],
                "rawOdds":        payload["rawOdds"],
                "commence":       payload["commence"],
                "bookmakerCount": payload["bookmakerCount"],
            }
            for (home, away), payload in sorted(
                data.items(), key=lambda x: x[1].get("commence") or ""
            )
        ]

        return {"available": True, "count": len(matches), "matches": matches}

    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.get("/odds/outrights")
async def outright_odds():
    """
    Momios de ganador del torneo convertidos a probabilidades justas (sin vig).
    Ordenados de mayor a menor probabilidad implícita de mercado.

    Respuesta cuando hay datos:
      available: true
      teams: [{team, prob, bestOdds}]

    Respuesta cuando no hay datos:
      available: false
      teams: []
    """
    try:
        data = await get_outright_odds()

        if data is None:
            return {
                "available": False,
                "teams": [],
                "note": "Sin momios de campeón disponibles",
            }

        teams = sorted(
            [{"team": name, **payload} for name, payload in data.items()],
            key=lambda x: -x["prob"],
        )

        return {"available": True, "count": len(teams), "teams": teams}

    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
