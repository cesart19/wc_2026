"""Backtest OLD vs NEW predictor over the three jornada-1 matches.

Compares the pre-change model (DRAW_SCALE=2.0, no friendly damping, flat
market blend) against the recalibrated one (DRAW_SCALE=1.4, friendly-share
affinity damping, extra market weight on the draw) using multiclass log-loss
and Brier score. Run from backend/ with the venv active.
"""

import math
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from app.services import match_predictor as mp  # noqa: E402
from app.services.prematch_analysis import (  # noqa: E402
    extended_affinity,
    find_team_id,
    probable_xi,
)

# (home, away, date, venue, market_probs|None, actual: 0=home 1=draw 2=away)
MATCHES = [
    (
        "Mexico", "South Africa", "2026-06-11",
        "Estadio Azteca · Ciudad de México", None, 0,
    ),
    (
        "South Korea", "Czechia", "2026-06-12",
        "Estadio Akron · Guadalajara", None, 0,
    ),
    (
        "Canada", "Bosnia-Herzegovina", "2026-06-12",
        "BMO Field · Toronto", (0.5196, 0.2733, 0.2071), 1,
    ),
]

OUTCOME = ["LOCAL gana", "EMPATE", "VISITANTE gana"]


def features(home: str, away: str, date: str) -> dict:
    """Compute affinity and friendly share for both teams (cached APIF)."""
    out: dict = {}
    for name in (home, away):
        tid = find_team_id(name)
        xi, last5 = probable_xi(name, tid, date)
        share = (
            sum(1 for m in last5 if m["friendly"]) / len(last5)
            if last5
            else 0.0
        )
        out[name] = (extended_affinity(xi, last5), share)
    return out


def predict(
    home: str,
    away: str,
    venue: str,
    feats: dict,
    market: tuple[float, float, float] | None,
    *,
    draw_scale: float,
    damp: float,
    draw_boost: float,
) -> tuple[float, float, float]:
    """Predict with the given (monkeypatched) calibration constants."""
    mp._DRAW_SCALE = draw_scale
    mp._FRIENDLY_DAMP = damp
    mp._DRAW_MARKET_BOOST = draw_boost
    aff_h, fs_h = feats[home]
    aff_a, fs_a = feats[away]
    p = mp.predictor.predict(
        home, away, stage="GROUP_STAGE", venue=venue,
        affinity_a=aff_h, affinity_b=aff_a,
        friendly_share_a=fs_h, friendly_share_b=fs_a,
    )
    if market:
        p = mp.predictor.blend_with_market(p, market, alpha=0.5)
    return p


def log_loss(p: tuple[float, float, float], actual: int) -> float:
    """Multiclass log-loss for a single observation."""
    return -math.log(max(1e-12, p[actual]))


def brier(p: tuple[float, float, float], actual: int) -> float:
    """Multiclass Brier score for a single observation."""
    return sum((p[i] - (1.0 if i == actual else 0.0)) ** 2 for i in range(3))


def main() -> None:
    """Run both calibrations over every match and print the scoreboard."""
    # NEW = damping de afinidad + boost de mercado al empate. DRAW_SCALE se
    # mantiene en 2.0: el backtest desaconsejó bajarlo (ver sweep en el análisis).
    configs = {
        "OLD": dict(draw_scale=2.0, damp=0.0, draw_boost=0.0),
        "NEW": dict(draw_scale=2.0, damp=1.0, draw_boost=0.2),
    }
    totals = {k: {"ll": 0.0, "br": 0.0} for k in configs}

    for home, away, date, venue, market, actual in MATCHES:
        feats = features(home, away, date)
        print(f"\n{'='*64}\n{home} vs {away}  →  {OUTCOME[actual]}")
        print(f"  afinidad/amistosos: {home} {feats[home]} | "
              f"{away} {feats[away]}")
        for tag, cfg in configs.items():
            p = predict(home, away, venue, feats, market, **cfg)
            ll, br = log_loss(p, actual), brier(p, actual)
            totals[tag]["ll"] += ll
            totals[tag]["br"] += br
            print(f"  {tag}: L {p[0]*100:5.1f}% | X {p[1]*100:5.1f}% | "
                  f"V {p[2]*100:5.1f}%   logloss {ll:.3f}  brier {br:.3f}")

    n = len(MATCHES)
    print(f"\n{'='*64}\nPROMEDIOS ({n} partidos)  — menor es mejor")
    for tag in configs:
        print(f"  {tag}: log-loss {totals[tag]['ll']/n:.4f} | "
              f"brier {totals[tag]['br']/n:.4f}")


if __name__ == "__main__":
    main()
