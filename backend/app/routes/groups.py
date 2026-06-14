from fastapi import APIRouter, HTTPException
from app.services.football_api import get_standings

router = APIRouter()


@router.get("/groups")
async def groups():
    try:
        data = await get_standings()
        standings = data.get("standings", [])
        result = []
        for group in standings:
            result.append({
                "group": group.get("group", ""),
                "stage": group.get("stage", ""),
                "table": [
                    {
                        "position": row["position"],
                        "teamId": row["team"]["id"],
                        "team": row["team"]["name"],
                        "crest": row["team"].get("crest", ""),
                        "played": row["playedGames"],
                        "won": row["won"],
                        "draw": row["draw"],
                        "lost": row["lost"],
                        "gf": row["goalsFor"],
                        "ga": row["goalsAgainst"],
                        "gd": row["goalDifference"],
                        "points": row["points"],
                    }
                    for row in group.get("table", [])
                ],
            })
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
