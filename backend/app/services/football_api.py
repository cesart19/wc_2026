import os
import time
import httpx

COMPETITION = "WC"

# Simple in-memory cache to respect the 10 req/min free tier limit
_cache: dict = {}
CACHE_TTL = 120  # seconds


def _headers() -> dict:
    return {"X-Auth-Token": os.getenv("FOOTBALL_API_KEY", "")}


def _api_url() -> str:
    return os.getenv("FOOTBALL_API_URL", "https://api.football-data.org/v4")


def _cached(key: str, ttl: int = CACHE_TTL):
    entry = _cache.get(key)
    if entry and time.time() - entry["ts"] < ttl:
        return entry["data"]
    return None


def _store(key: str, data):
    _cache[key] = {"data": data, "ts": time.time()}
    return data


async def get_standings() -> dict:
    key = "standings"
    if cached := _cached(key):
        return cached
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{_api_url()}/competitions/{COMPETITION}/standings",
            headers=_headers(),
            timeout=10,
        )
        r.raise_for_status()
        return _store(key, r.json())


async def get_matches() -> dict:
    key = "matches"
    if cached := _cached(key):
        return cached
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{_api_url()}/competitions/{COMPETITION}/matches",
            headers=_headers(),
            timeout=10,
        )
        r.raise_for_status()
        return _store(key, r.json())
