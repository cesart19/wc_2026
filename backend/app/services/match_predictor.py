"""
Match outcome predictor — parametric composite-strength model.

Architecture is LightGBM-ready: swap MatchPredictor.predict() when a trained
model is available (serialize to model.json, load at startup, call booster.predict()).

Current model:
  strength_i  = 0.40·norm(elo) + 0.35·norm(fifa_pts) + 0.25·norm(log(mv))
  logit_adj   = crowd_delta + trend_delta + momentum_delta + affinity_delta
  P(A wins)   = σ(K·(s_A − s_B) + logit_adj)  where K=3.0
  crowd_delta    = (crowd_a − crowd_b) / 100 × CROWD_K      (venue/diaspora)
  trend_delta    = norm(trend_18m_a − trend_18m_b) × TREND_K (18-month FIFA pts growth)
  momentum_delta = norm(mom_a − mom_b) × MOMENTUM_K         (Jan→May 2026 change)
  affinity_delta = (affinity_a − affinity_b) / 100 × AFFINITY_K × damping
                   damping = 1 − FRIENDLY_DAMP × max(friendly_share_a, _b):
                   anula la cohesión cuando el XI viene de puros amistosos.
  P(draw)     = 0.245 × (1 − |p_a − 0.5| × DRAW_SCALE) — parity-scaled, 0 in knockout
                DRAW_SCALE=1.2 (bajado de 2.0 el 2026-06-13 tras el backtest de
                jornada 1+2): menor escala → más masa de empate en partidos
                desequilibrados, que es donde el modelo lo subvaluaba. El blend
                añade además peso de mercado al empate vía DRAW_MARKET_BOOST.

Feature weights reference:
  ELO 40% — captures historical head-to-head outcomes
  FIFA pts 35% — official measure of recent competitive results
  Market value 25% — proxy for squad talent depth (log-scaled)
  Crowd support — co-host/diaspora/sympathy advantage at WC 2026 (North America)
  Trend 18m — long-run momentum over qualifying cycle (FIFA ranking pts growth)
  Momentum — recent form entering the tournament (Jan → May 2026 delta)
  Affinity — squad cohesion: players sharing club > league > different league
             Computed by squad_affinity_score() in club_ratings.py.
             Scales on [0, 100]: ~37 England (PL-heavy) · ~32 Spain · ~31 Germany
             Effect: secondary (K=0.12) — 27-pt diff ≈ +0.8% win probability
"""

import math
import os
from app.services.team_data import TEAM_DATA, get_team_data, get_crowd_support, get_trend_data, warn_if_unrated

# Peso del mercado en el blend (0 = solo modelo, 1 = solo mercado).
# Configurable vía variable de entorno ODDS_BLEND_ALPHA.
# Subido 0.5→0.6 (2026-06-13): el mercado ganó en Brier los 2 partidos
# evaluados (CAN-BIH y USA-PAR). El barrido sobre esa muestra prefería 1.0,
# pero es sobreajuste a n=2 (tiraría el modelo); 0.6 es un paso moderado que
# mejora el Brier sin descartarlo. Revisar al acumular más jornada.
_BLEND_ALPHA: float = float(os.getenv("ODDS_BLEND_ALPHA", "0.6"))
# Extra de peso de mercado SOLO en la cuota de empate: el mercado calibra el
# empate mejor que el modelo (eficiencia + el modelo lo subvalúa). El empate
# se mezcla con alpha + este boost, acotado a 1.0. Configurable vía entorno.
_DRAW_MARKET_BOOST: float = float(os.getenv("ODDS_DRAW_MARKET_BOOST", "0.2"))
# Coasting damp (stakes-aware). En GROUP_STAGE, reduce la masa de victoria del
# favorito cuando el partido es de bajo riesgo para él (ya casi clasificado:
# label SECURED/SEEDING en stakes.py) — las elites bajan intensidad una vez
# asegurado el pase. 0.0 = APAGADO (default): /forecast omite por completo el
# cálculo de stakes, así que la ruta es idéntica a antes. Env STAKES_COAST_DAMP.
# Se calibrará con el primer caso SECURED real (~jornada 3).
_STAKES_COAST_DAMP: float = float(os.getenv("STAKES_COAST_DAMP", "0.0"))
# De la masa quitada al favorito que pasea, qué fracción va al empate (resto al
# underdog): un favorito que afloja empata más de lo que pierde.
_COAST_TO_DRAW: float = 0.6

# ── Calibración de favorito (always-on) ──────────────────────────────────────
# El ledger de jornada 1 muestra que el blended sobre-confía en favoritos
# amplios y subvalúa el empate (bucket heavyFavorite: predijo 74%, observó
# 50%). Esta capa encoge la masa de victoria del favorito hacia empate+underdog
# proporcional a su sobreconfianza (exceso sobre el ancla). Parámetros
# PROVISIONALES fijados desde priors, NO ajustados al óptimo: a n=8 la
# superficie de RPS no tiene mínimo interior (pide el borde → sobreajuste).
# Re-ajustar al acumular jornadas. Ver apply_favorite_shrink.
_FAV_SHRINK_LAMBDA: float = float(os.getenv("FAV_SHRINK_LAMBDA", "0.5"))
_FAV_SHRINK_CAP: float = float(os.getenv("FAV_SHRINK_CAP", "0.12"))
_FAV_SHRINK_ANCHOR: float = float(os.getenv("FAV_SHRINK_ANCHOR", "0.55"))
# Fracción de la masa quitada que va al empate (resto al underdog): los
# tropiezos del favorito son mayoritariamente empates, pero se deja masa al
# underdog para no sobreajustar a "todo bust es empate".
_FAV_SHRINK_TO_DRAW: float = 0.7

_K = 3.0             # logistic scale: higher → more decisive wins for stronger teams
_P_DRAW_GROUP = 0.245 # WC group-stage draw rate at perfect parity — promedio histórico WC2014-2022 ≈ 23.6%
# Escala de paridad del empate. A paridad (p_a=0.5) el empate vale
# _P_DRAW_GROUP; al aumentar el desequilibrio decae a
# _P_DRAW_GROUP·(1 − 0.5·_DRAW_SCALE) en el extremo. MENOR valor → MÁS masa
# de empate en partidos desequilibrados. Configurable vía ODDS_DRAW_SCALE.
# Bajado 2.0→1.2 (2026-06-13) tras el backtest de jornada 1+2 (n=6, 3 empates
# + 3 triunfos del favorito; backtest_drawscale.py): el barrido es monótono y
# a 1.2 el Brier del modelo baja 0.696→0.649 (empates 1.23→1.10) cediendo solo
# 0.16→0.20 en favoritos —gana ~4× lo que cuesta. No se baja más (0.6 seguía
# mejorando pero sobreajusta a 3 empates). El backtest de jornada 1 SOLO (n=3,
# 2 de 3 triunfos del favorito) lo desaconsejaba; la muestra balanceada lo
# invierte.
_DRAW_SCALE: float = float(os.getenv("ODDS_DRAW_SCALE", "1.2"))
_FORM_WEIGHT = 0.04  # pts/game shift vs expected 1.5 ppg
_CROWD_K = 0.5       # crowd logit delta: 100-pt diff → +12% win prob for home team
_TREND_K = 0.08      # logit delta per normalized 18-month trend unit
_MOMENTUM_K = 0.20   # logit delta per normalized momentum unit (recent form)
_TREND_SCALE = 20.0  # normalization denominator for 18-month change — max real diff en datos = 19.5 (24.0 − 4.5)
_MOMENTUM_SCALE = 7.0  # normalization denominator for recent momentum — max real diff = 7.0 (5.0 − (−2.0))
_AFFINITY_K = 0.12   # logit delta per unit affinity diff (escala 0-1)
                     # 60-pt diff → logit_adj=0.072 → +~1.8% win probability
                     # Calibrado para que la cohesión sea un factor secundario,
                     # no dominante: máx diff real ~40 pts → +1.2% win prob
_FRIENDLY_DAMP = 1.0 # cuánto se amortigua affinity_diff por amistosos recientes.
                     # El XI por frecuencia en amistosos rota mucho → la afinidad
                     # medida queda deflactada (artefacto, no menor cohesión real).
                     # Patrón jornada 1: los 3 locales tenían 100% amistosos y
                     # afinidad < rival en los 3 casos. affinity_diff se escala por
                     # (1 − DAMP·max(friendly_share_a, friendly_share_b)): si algún
                     # equipo viene de puros amistosos, la diferencia no es fiable.

# Venue-specific crowd boost: co-host playing in their own stadium
_HOST_TEAMS: dict[str, str] = {
    "USA":    "United States",
    "Mexico": "Mexico",
    "Canada": "Canada",
}
_VENUE_BOOST = 12  # extra crowd points (0-100 scale) for host team in home stadium


def _apply_venue_boost(team_name: str, base_crowd: int, host_country: str) -> int:
    """Amplifica el crowd si el equipo juega en el estadio de su propio país co-anfitrión."""
    if _HOST_TEAMS.get(host_country) == team_name:
        return min(100, base_crowd + _VENUE_BOOST)
    return base_crowd


def _compute_strengths() -> dict[str, float]:
    """Normalize each feature to [0,1] and compute composite strength."""
    names = list(TEAM_DATA.keys())
    all_data = [TEAM_DATA[n] for n in names]

    elos = [d["elo"] for d in all_data]
    fifas = [d["fifa_pts"] for d in all_data]
    mvs = [math.log(max(d["market_value_m"], 1)) for d in all_data]

    def _minmax(vals: list[float]) -> list[float]:
        lo, hi = min(vals), max(vals)
        span = hi - lo or 1.0
        return [(v - lo) / span for v in vals]

    elo_n = _minmax(elos)
    fifa_n = _minmax(fifas)
    mv_n = _minmax(mvs)

    return {
        name: 0.40 * elo_n[i] + 0.35 * fifa_n[i] + 0.25 * mv_n[i]
        for i, name in enumerate(names)
    }


_STRENGTHS: dict[str, float] = _compute_strengths()
# Media aritmética: equipos desconocidos reciben fuerza promedio, no la del peor equipo.
_DEFAULT_STRENGTH: float = sum(_STRENGTHS.values()) / len(_STRENGTHS)


def get_strength(name: str) -> float:
    return _STRENGTHS.get(name, _DEFAULT_STRENGTH)


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-20.0, min(20.0, x))))


def _logit(p: float) -> float:
    p = max(1e-9, min(1 - 1e-9, p))
    return math.log(p / (1.0 - p))


def _form_adjustment(pts_per_game: float) -> float:
    return (pts_per_game - 1.5) * _FORM_WEIGHT


def _norm_clamp(value: float, scale: float) -> float:
    """Normalize value to [-1, 1] using the given scale."""
    return max(-1.0, min(1.0, value / scale))


def _friendly_damping(friendly_share_a: float, friendly_share_b: float) -> float:
    """Factor [0-1] que amortigua la afinidad por amistosos recientes.

    El XI por frecuencia en amistosos rota, deflactando la afinidad medida;
    si cualquiera de los dos equipos viene de puros amistosos la diferencia de
    afinidad deja de ser comparable, así que se escala hacia 0.
    """
    max_share = max(friendly_share_a, friendly_share_b)
    return max(0.0, 1.0 - _FRIENDLY_DAMP * max_share)


def apply_coast_damp(
    probs: tuple[float, float, float],
    fav_is_home: bool,
    intensity: float,
) -> tuple[float, float, float]:
    """Shift a coasting favourite's win mass toward draw + underdog.

    Args:
        probs: (p_home, p_draw, p_away) del modelo (suman 1).
        fav_is_home: True si el favorito (equipo que pasea) es local.
        intensity: en [0, 1] = _STAKES_COAST_DAMP × coast. 0 → identidad.

    Returns:
        Probabilidades ajustadas; la masa se conserva (siguen sumando 1).
    """
    if intensity <= 0.0:
        return probs
    p_home, p_draw, p_away = probs
    move = (p_home if fav_is_home else p_away) * intensity
    to_draw = move * _COAST_TO_DRAW
    to_dog = move - to_draw
    p_draw += to_draw
    if fav_is_home:
        p_home -= move
        p_away += to_dog
    else:
        p_away -= move
        p_home += to_dog
    return p_home, p_draw, p_away


def apply_favorite_shrink(
    probs: tuple[float, float, float],
    is_knockout: bool = False,
) -> tuple[float, float, float]:
    """Recalibrate the final W/D/L by shrinking an over-confident favourite.

    Always-on companion of :func:`apply_coast_damp` in the GROUP STAGE only.
    Early group-stage data (n=8) showed wide favourites busting and draws
    under-priced, so this moves a bounded fraction of the favourite's win mass
    toward draw + underdog, proportional to how far its win probability exceeds
    parity (``_FAV_SHRINK_ANCHOR``). The cap (``_FAV_SHRINK_CAP``) keeps the
    favourite the most likely outcome; mass is conserved.

    Knockout no-op: over the full group stage (n=62) wide favourites instead
    win MORE than predicted (clearFavorite 71% observed vs 62% predicted;
    heavyFavorite 100% vs 74%), reversing the premise above. A knockout match
    has no draw, so the shrink could only move mass to the underdog — exactly
    the wrong direction given that evidence — so it is disabled there. The
    group-stage parameters are left as-is pending a ledger-driven A/B re-fit.

    Args:
        probs: (p_home, p_draw, p_away), summing to 1.0.
        is_knockout: When True the layer is a no-op (see above).

    Returns:
        Recalibrated (p_home, p_draw, p_away). Identity in knockout matches and
        whenever the favourite is at or below the parity anchor.
    """
    if is_knockout:
        return probs
    p_home, p_draw, p_away = probs
    fav_is_home = p_home >= p_away
    p_fav = p_home if fav_is_home else p_away
    intensity = min(
        _FAV_SHRINK_CAP,
        _FAV_SHRINK_LAMBDA * max(0.0, p_fav - _FAV_SHRINK_ANCHOR),
    )
    if intensity <= 0.0:
        return probs
    move = p_fav * intensity
    to_draw = move * _FAV_SHRINK_TO_DRAW
    to_dog = move - to_draw
    p_draw += to_draw
    if fav_is_home:
        p_home -= move
        p_away += to_dog
    else:
        p_away -= move
        p_home += to_dog
    return p_home, p_draw, p_away


class MatchPredictor:
    """
    Predict (p_home_win, p_draw, p_away_win) for any two national teams.

    To plug in a trained LightGBM model:
      1. Build feature dict: build_features(...)
      2. Replace the body of predict() with: booster.predict([list(feats.values())])
    """

    def build_features(
        self,
        name_a: str,
        name_b: str,
        ppg_a: float = 1.5,
        ppg_b: float = 1.5,
        stage: str = "GROUP_STAGE",
        apply_crowd: bool = True,
        venue: str | None = None,
        affinity_a: float = 50.0,
        affinity_b: float = 50.0,
        friendly_share_a: float = 0.0,
        friendly_share_b: float = 0.0,
    ) -> dict:
        d_a = get_team_data(name_a)
        d_b = get_team_data(name_b)
        host = None
        if venue:
            from app.services.venues import get_host_country
            host = get_host_country(venue)
        crowd_a = get_crowd_support(name_a, host) if apply_crowd else 50
        crowd_b = get_crowd_support(name_b, host) if apply_crowd else 50
        td_a = get_trend_data(name_a)
        td_b = get_trend_data(name_b)
        damping = _friendly_damping(friendly_share_a, friendly_share_b)
        return {
            "elo_diff":           d_a["elo"] - d_b["elo"],
            "fifa_pts_diff":      d_a["fifa_pts"] - d_b["fifa_pts"],
            "market_value_ratio": math.log(max(d_a["market_value_m"], 1))
                                  - math.log(max(d_b["market_value_m"], 1)),
            "form_diff":          ppg_a - ppg_b,
            "crowd_support_diff": crowd_a - crowd_b,
            "trend_18m_diff":     td_a["trend_18m"] - td_b["trend_18m"],
            "momentum_diff":      td_a["momentum"] - td_b["momentum"],
            "affinity_diff":      (affinity_a - affinity_b) * damping,
            "is_knockout":        0 if stage == "GROUP_STAGE" else 1,
        }

    def predict(
        self,
        name_a: str,
        name_b: str,
        ppg_a: float = 1.5,
        ppg_b: float = 1.5,
        stage: str = "GROUP_STAGE",
        apply_crowd: bool = True,
        venue: str | None = None,
        affinity_a: float = 50.0,
        affinity_b: float = 50.0,
        friendly_share_a: float = 0.0,
        friendly_share_b: float = 0.0,
    ) -> tuple[float, float, float]:
        """
        Returns (p_a_wins, p_draw, p_b_wins). Probabilities sum to 1.0.

        affinity_a / affinity_b: squad cohesion score [0-100] calculado por
        squad_affinity_score() en club_ratings.py. Mide la afinidad media ponderada
        entre todos los pares de jugadores (mismo club > misma liga > distinta liga).
        Un squad con alta afinidad tiene ventaja táctica marginal en cohesión.

        friendly_share_a / friendly_share_b: fracción [0-1] de los últimos
        partidos que fueron amistosos. La afinidad medida sobre amistosos está
        deflactada por rotación, así que affinity_diff se amortigua según el
        mayor de los dos shares (ver _FRIENDLY_DAMP).
        """
        # Guardrail: avisar (una vez por nombre) si alguna selección no está
        # rateada y caería al promedio por defecto — fallo silencioso evitado.
        warn_if_unrated(name_a)
        warn_if_unrated(name_b)

        s_a = get_strength(name_a) + _form_adjustment(ppg_a)
        s_b = get_strength(name_b) + _form_adjustment(ppg_b)
        p_base = _sigmoid(_K * (s_a - s_b))

        # Accumulate logit adjustments — all applied on logit scale to preserve [0,1]
        logit_adj = 0.0

        # Trend: long-run FIFA ranking growth over 18 months (qualifying cycle)
        td_a = get_trend_data(name_a)
        td_b = get_trend_data(name_b)
        logit_adj += (_norm_clamp(td_a["trend_18m"], _TREND_SCALE) - _norm_clamp(td_b["trend_18m"], _TREND_SCALE)) * _TREND_K

        # Momentum: recent form entering the tournament (Jan → May 2026)
        logit_adj += (_norm_clamp(td_a["momentum"], _MOMENTUM_SCALE) - _norm_clamp(td_b["momentum"], _MOMENTUM_SCALE)) * _MOMENTUM_K

        # Affinity: squad cohesion advantage (afinidad por club/liga compartida)
        # diff normalizado a [-1, 1]: 100-pt diff → logit_adj = ±_AFFINITY_K.
        # Amortiguado por amistosos: si algún equipo viene de puros amistosos
        # (XI rotado), la afinidad medida no es comparable y la diff se anula.
        affinity_diff = (affinity_a - affinity_b) / 100.0 * _friendly_damping(
            friendly_share_a, friendly_share_b
        )
        logit_adj += affinity_diff * _AFFINITY_K

        # Crowd/venue: diaspora + co-host advantage (WC 2026 North America)
        # If venue is provided, the crowd index becomes host-aware (per-venue
        # overrides) and the host country's team gets an extra stadium boost.
        if apply_crowd:
            host = None
            if venue:
                from app.services.venues import get_host_country
                host = get_host_country(venue)
            crowd_a = get_crowd_support(name_a, host)
            crowd_b = get_crowd_support(name_b, host)
            if host:
                crowd_a = _apply_venue_boost(name_a, crowd_a, host)
                crowd_b = _apply_venue_boost(name_b, crowd_b, host)
            logit_adj += (crowd_a - crowd_b) / 100.0 * _CROWD_K

        p_a_raw = _sigmoid(_logit(p_base) + logit_adj)

        if stage != "GROUP_STAGE":
            return p_a_raw, 0.0, 1.0 - p_a_raw

        # Draw probability scales with parity: max at p_a=0.5, zero when one side dominates
        p_draw = _P_DRAW_GROUP * (1.0 - abs(p_a_raw - 0.5) * _DRAW_SCALE)
        p_a = p_a_raw * (1.0 - p_draw)
        p_b = (1.0 - p_a_raw) * (1.0 - p_draw)
        return p_a, p_draw, p_b

    def blend_with_market(
        self,
        p_model: tuple[float, float, float],
        p_market: tuple[float, float, float],
        alpha: float | None = None,
    ) -> tuple[float, float, float]:
        """
        Mezcla probabilidades del modelo con probabilidades de mercado.

        Args:
            p_model:  (p_home_win, p_draw, p_away_win) del modelo estadístico
            p_market: (p_home_win, p_draw, p_away_win) del mercado (no-vig)
            alpha:    Peso del mercado (0=solo modelo, 1=solo mercado).
                      Si None, usa _BLEND_ALPHA del entorno (default 0.5).
                      El empate recibe alpha + _DRAW_MARKET_BOOST (acotado a 1)
                      porque el mercado lo calibra mejor que el modelo.

        Returns:
            Tupla normalizada de tres probabilidades que suman 1.0.
        """
        mkt_w = alpha if alpha is not None else _BLEND_ALPHA
        mkt_w_draw = min(1.0, mkt_w + _DRAW_MARKET_BOOST)
        weights = (mkt_w, mkt_w_draw, mkt_w)
        blended = tuple(
            (1.0 - w) * pm + w * pk
            for pm, pk, w in zip(p_model, p_market, weights)
        )
        total = sum(blended)
        if total <= 0:
            return p_model  # fallback: retorna el modelo si algo falla
        return tuple(v / total for v in blended)  # type: ignore[return-value]

    def predict_both(
        self,
        name_a: str,
        name_b: str,
        ppg_a: float = 1.5,
        ppg_b: float = 1.5,
        stage: str = "GROUP_STAGE",
        venue: str | None = None,
        affinity_a: float = 50.0,
        affinity_b: float = 50.0,
        friendly_share_a: float = 0.0,
        friendly_share_b: float = 0.0,
    ) -> dict:
        """Return base and crowd-adjusted probabilities together."""
        p_base = self.predict(name_a, name_b, ppg_a, ppg_b, stage, apply_crowd=False,
                              affinity_a=affinity_a, affinity_b=affinity_b,
                              friendly_share_a=friendly_share_a,
                              friendly_share_b=friendly_share_b)
        p_crowd = self.predict(name_a, name_b, ppg_a, ppg_b, stage, apply_crowd=True,
                               venue=venue, affinity_a=affinity_a, affinity_b=affinity_b,
                               friendly_share_a=friendly_share_a,
                               friendly_share_b=friendly_share_b)
        impact = p_crowd[0] - p_base[0]
        if abs(impact) < 0.001:
            impact_str = "Sin ventaja de localía"
        else:
            beneficiary = name_a if impact > 0 else name_b
            impact_str = f"{'+' if impact > 0 else ''}{impact * 100:.1f}% para {beneficiary}"
        return {
            "base": {"aWin": round(p_base[0], 4), "draw": round(p_base[1], 4), "bWin": round(p_base[2], 4)},
            "withCrowd": {"aWin": round(p_crowd[0], 4), "draw": round(p_crowd[1], 4), "bWin": round(p_crowd[2], 4)},
            "crowdImpact": impact_str,
        }


# Module-level singleton — import and use directly
predictor = MatchPredictor()
