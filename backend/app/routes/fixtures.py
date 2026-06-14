from fastapi import APIRouter, HTTPException
from app.services.football_api import get_matches
from app.services.venues import get_venue, get_venue_by_id

router = APIRouter()


@router.get("/fixtures")
async def fixtures():
    try:
        data = await get_matches()
        matches = data.get("matches", [])
        result = []
        for m in matches:
            result.append({
                "id": m["id"],
                "utcDate": m["utcDate"],
                "status": m["status"],
                "stage": m["stage"],
                "group": m.get("group"),
                "homeTeam": {
                    "id": m["homeTeam"].get("id"),
                    "name": m["homeTeam"].get("name") or "TBD",
                    "crest": m["homeTeam"].get("crest", ""),
                },
                "awayTeam": {
                    "id": m["awayTeam"].get("id"),
                    "name": m["awayTeam"].get("name") or "TBD",
                    "crest": m["awayTeam"].get("crest", ""),
                },
                "score": {
                    "home": m["score"]["fullTime"].get("home"),
                    "away": m["score"]["fullTime"].get("away"),
                },
                "venue": (
                    m.get("venue")
                    or get_venue(m["homeTeam"].get("name", ""), m["awayTeam"].get("name", ""))
                    or get_venue_by_id(m["id"])
                ),
            })
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
