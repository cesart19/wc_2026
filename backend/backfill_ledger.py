"""Backfill model-layer forecasts for jornada-1 matches into the ledger.

MX-SA and KOR-CZE were played before the forecast ledger existed, so they
were never snapshotted. This records the CURRENT model's forecast (model
layer only — live market odds are gone post-match) with a pre-kickoff
timestamp so evaluate() scores them. Idempotent guard: skips a match that
already has a backfill snapshot. Run from backend/ with the venv active.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("backfill")
logging.getLogger("httpx").setLevel(logging.WARNING)

# (home, away, last5-cutoff date, kickoff UTC, venue) — names must match the
# football-data /fixtures feed so evaluate() can join on them.
_MATCHES = [
    (
        "Mexico", "South Africa", "2026-06-11",
        "2026-06-11T19:00:00Z", "Estadio Azteca · Ciudad de México",
    ),
    (
        "South Korea", "Czechia", "2026-06-12",
        "2026-06-12T02:00:00Z", "Estadio Akron · Guadalajara",
    ),
]

_BACKFILL_METHOD = "prematch_xi_extended_backfill"


def _already_backfilled(home: str, away: str) -> bool:
    """True if this match already has a backfill snapshot in the ledger."""
    from app.services.forecast_ledger import _key, _load

    entry = _load().get(_key(home, away))
    if not entry:
        return False
    return any(
        s.get("extras", {}).get("method") == _BACKFILL_METHOD
        for s in entry.get("snapshots", [])
    )


async def _model_probs(
    home: str, away: str, date: str, venue: str
) -> tuple[dict[str, float], dict[str, float]]:
    """Compute the model-layer 1X2 and per-team affinity for a match."""
    from app.services.match_predictor import predictor
    from app.services.prematch_analysis import (
        extended_affinity,
        find_team_id,
        probable_xi,
    )

    affinities: dict[str, float] = {}
    shares: dict[str, float] = {}
    for name in (home, away):
        xi, last5 = probable_xi(name, find_team_id(name), date)
        affinities[name] = extended_affinity(xi, last5)
        shares[name] = (
            sum(1 for m in last5 if m["friendly"]) / len(last5)
            if last5
            else 0.0
        )
    p_a, p_draw, p_b = predictor.predict(
        home, away, stage="GROUP_STAGE", venue=venue,
        affinity_a=affinities[home], affinity_b=affinities[away],
        friendly_share_a=shares[home], friendly_share_b=shares[away],
    )
    model = {
        "homeWin": round(p_a, 4),
        "draw": round(p_draw, 4),
        "awayWin": round(p_b, 4),
    }
    return model, affinities


def _backdated(kickoff_utc: str) -> datetime:
    """Kickoff minus one hour, as a tz-aware UTC datetime (pre-kickoff)."""
    kickoff = datetime.fromisoformat(kickoff_utc.replace("Z", "+00:00"))
    return (kickoff - timedelta(hours=1)).astimezone(timezone.utc)


async def main() -> None:
    """Backfill each configured match into the ledger (model layer only)."""
    from app.services.forecast_ledger import record_snapshot

    for home, away, date, kickoff, venue in _MATCHES:
        if _already_backfilled(home, away):
            log.info("Ya backfilled, se omite: %s vs %s", home, away)
            continue
        model, affinities = await _model_probs(home, away, date, venue)
        record_snapshot(
            home, away, "GROUP_STAGE", venue,
            probs={"model": model, "market": None, "blended": None},
            extras={
                "method": _BACKFILL_METHOD,
                "affinity": affinities,
                "note": "retro-backfill: current model, no live market",
            },
            recorded_at=_backdated(kickoff),
        )
        log.info(
            "%s vs %s — modelo %.1f/%.1f/%.1f (afinidad %s)",
            home, away,
            model["homeWin"] * 100, model["draw"] * 100,
            model["awayWin"] * 100, affinities,
        )


if __name__ == "__main__":
    asyncio.run(main())
