from fastapi import APIRouter, HTTPException, Query
from app.services.football_api import get_matches, get_standings
from app.services.forecast_ledger import evaluate, record_snapshot
from app.services.forecasting import run_forecast, _get_affinity, _build_groups
from app.services.match_predictor import (
    predictor,
    apply_coast_damp,
    _BLEND_ALPHA,
    _STAKES_COAST_DAMP,
)
from app.services.stakes import coast_for_match
from app.services.team_data import get_team_data, get_crowd_support, get_trend_data
from app.services.venues import get_venue, get_host_country
from app.services.odds_api import get_match_odds
from app.services.team_data import TEAM_DATA

router = APIRouter()

_KNOCKOUT_STAGES = {"LAST_32", "LAST_16", "QUARTER_FINALS", "SEMI_FINALS", "THIRD_PLACE", "FINAL"}


@router.get("/forecast")
async def tournament_forecast():
    """
    Monte Carlo tournament win probability for every team in the competition.
    Results are cached for 5 minutes.
    """
    try:
        return await run_forecast()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/forecast/match")
async def match_forecast(
    home: str = Query(..., description="Home team name, e.g. 'Argentina'"),
    away: str = Query(..., description="Away team name, e.g. 'France'"),
    stage: str = Query(
        "GROUP_STAGE",
        description="GROUP_STAGE | LAST_32 | LAST_16 | QUARTER_FINALS | SEMI_FINALS | THIRD_PLACE | FINAL",
    ),
    venue: str = Query(
        None,
        description="Venue string, e.g. 'Estadio Azteca · Ciudad de México'. "
                    "Auto-detected from group-stage fixture table if omitted.",
    ),
    use_market: bool = Query(
        True,
        description="Si es true, incluye momios de mercado y probabilidades blended en la respuesta.",
    ),
):
    try:
        d_home = get_team_data(home)
        d_away = get_team_data(away)
        td_home = get_trend_data(home)
        td_away = get_trend_data(away)

        # Auto-detect venue for group stage if not provided
        resolved_venue = venue or (get_venue(home, away) if stage == "GROUP_STAGE" else None)
        host = get_host_country(resolved_venue) if resolved_venue else None
        crowd_home = get_crowd_support(home, host)
        crowd_away = get_crowd_support(away, host)

        # Afinidad real de plantel (squad_context_v3.json) — antes se
        # pasaba la neutral 50/50, anulando el factor de cohesión.
        aff_home = _get_affinity(home)
        aff_away = _get_affinity(away)

        is_knockout = stage in _KNOCKOUT_STAGES
        result = predictor.predict_both(
            home, away, stage=stage, venue=resolved_venue,
            affinity_a=aff_home, affinity_b=aff_away,
        )
        feats = predictor.build_features(
            home, away, stage=stage, venue=resolved_venue,
            affinity_a=aff_home, affinity_b=aff_away,
        )

        # ── Damp de coasting (stakes-aware) ──────────────────────────────────
        # APAGADO por defecto (_STAKES_COAST_DAMP=0.0): se omite todo el cálculo
        # de stakes, así que el resto de la ruta queda intacto. Al activarlo,
        # afloja la victoria del favorito en partidos que ya tiene casi resueltos.
        stakes_section = None
        if not is_knockout and _STAKES_COAST_DAMP > 0.0:
            try:
                groups = _build_groups(
                    await get_standings(), await get_matches()
                )
                coast = coast_for_match(home, away, groups)
                if coast is not None:
                    coast_val, label, fav_is_home = coast
                    intensity = _STAKES_COAST_DAMP * coast_val
                    wc = result["withCrowd"]
                    damped = apply_coast_damp(
                        (wc["aWin"], wc["draw"], wc["bWin"]),
                        fav_is_home, intensity,
                    )
                    result["withCrowd"] = {
                        "aWin": round(damped[0], 4),
                        "draw": round(damped[1], 4),
                        "bWin": round(damped[2], 4),
                    }
                    stakes_section = {
                        "label": label,
                        "coast": round(coast_val, 3),
                        "favorite": home if fav_is_home else away,
                        "dampApplied": round(intensity, 3),
                    }
            except Exception as stakes_exc:
                import logging
                logging.getLogger(__name__).warning(
                    "Damp de coasting omitido: %s", stakes_exc
                )

        # ── Integración de momios de mercado ─────────────────────────────────
        market_section = None
        if use_market:
            try:
                known = set(TEAM_DATA.keys())
                match_odds = await get_match_odds(known_names=known)
                if match_odds:
                    # Buscar en ambas orientaciones (home, away) y (away, home)
                    odds_payload = (
                        match_odds.get((home, away))
                        or match_odds.get((away, home))
                    )
                    if odds_payload:
                        draw_raw = odds_payload["draw"]

                        if is_knockout:
                            # Knockout: redistribuir probabilidad de empate a home/away
                            if draw_raw is not None:
                                ph_raw = odds_payload["homeWin"]
                                pa_raw = odds_payload["awayWin"]
                                total_ha = ph_raw + pa_raw
                                if total_ha > 0:
                                    ph_m = ph_raw / total_ha
                                    pa_m = pa_raw / total_ha
                                else:
                                    ph_m, pa_m = 0.5, 0.5
                                p_market = (ph_m, 0.0, pa_m)
                            else:
                                p_market = (odds_payload["homeWin"], 0.0, odds_payload["awayWin"])
                        else:
                            # Fase de grupos: usar empate del mercado, o 0 si no hay
                            p_market = (
                                odds_payload["homeWin"],
                                draw_raw if draw_raw is not None else 0.0,
                                odds_payload["awayWin"],
                            )

                        wc = result["withCrowd"]
                        p_model = (wc["aWin"], wc["draw"], wc["bWin"])
                        blended = predictor.blend_with_market(p_model, p_market)

                        market_section = {
                            "available":      True,
                            "source":         "the-odds-api.com",
                            "bookmakerCount": odds_payload["bookmakerCount"],
                            "rawOdds":        odds_payload["rawOdds"],
                            "marketProb": {
                                "homeWin": round(p_market[0], 4),
                                "draw":    round(p_market[1], 4) if not is_knockout else None,
                                "awayWin": round(p_market[2], 4),
                            },
                            "blended": {
                                "homeWin": round(blended[0], 4),
                                "draw":    round(blended[1], 4) if not is_knockout else None,
                                "awayWin": round(blended[2], 4),
                            },
                            "blendAlpha": _BLEND_ALPHA,
                        }
            except Exception as odds_exc:
                # Los momios son optativos — no interrumpir si fallan
                import logging
                logging.getLogger(__name__).warning("No se pudieron obtener momios: %s", odds_exc)

        # ── Registro en el ledger de pronósticos ─────────────────────────────
        model_probs = {
            "homeWin": result["withCrowd"]["aWin"],
            "draw": None if is_knockout else result["withCrowd"]["draw"],
            "awayWin": result["withCrowd"]["bWin"],
        }
        record_snapshot(
            home, away, stage, resolved_venue,
            probs={
                "model": model_probs,
                "market": (market_section or {}).get("marketProb"),
                "blended": (market_section or {}).get("blended"),
            },
            extras={"affinity": {"home": aff_home, "away": aff_away}},
        )

        return {
            "home": home,
            "away": away,
            "stage": stage,
            "venue": resolved_venue,
            "homeStats": {
                "elo": d_home["elo"],
                "fifaPoints": d_home["fifa_pts"],
                "marketValueM": d_home["market_value_m"],
                "crowdSupport": crowd_home,
                "affinity": aff_home,
                "trend18m": td_home["trend_18m"],
                "momentum": td_home["momentum"],
            },
            "awayStats": {
                "elo": d_away["elo"],
                "fifaPoints": d_away["fifa_pts"],
                "marketValueM": d_away["market_value_m"],
                "crowdSupport": crowd_away,
                "affinity": aff_away,
                "trend18m": td_away["trend_18m"],
                "momentum": td_away["momentum"],
            },
            "crowdSupport": {
                "home": crowd_home,
                "away": crowd_away,
                "netAdvantage": crowd_home - crowd_away,
            },
            "features": {k: round(v, 4) for k, v in feats.items()},
            "base": {
                "homeWin": result["base"]["aWin"],
                "draw": None if is_knockout else result["base"]["draw"],
                "awayWin": result["base"]["bWin"],
            },
            "withCrowd": {
                "homeWin": result["withCrowd"]["aWin"],
                "draw": None if is_knockout else result["withCrowd"]["draw"],
                "awayWin": result["withCrowd"]["bWin"],
            },
            "crowdImpact": result["crowdImpact"],
            "market": market_section,
            "stakes": stakes_section,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/forecast/ledger")
async def forecast_ledger():
    """
    Evalúa los pronósticos registrados contra los resultados reales.
    Brier score por capa (modelo / mercado / blended) — menor es mejor.
    """
    try:
        data = await get_matches()
        matches = [
            {
                "status": m.get("status"),
                "utcDate": m.get("utcDate"),
                "homeTeam": m.get("homeTeam", {}),
                "awayTeam": m.get("awayTeam", {}),
                "score": {
                    "home": m.get("score", {}).get("fullTime", {}).get("home"),
                    "away": m.get("score", {}).get("fullTime", {}).get("away"),
                },
            }
            for m in data.get("matches", [])
        ]
        return evaluate(matches)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
