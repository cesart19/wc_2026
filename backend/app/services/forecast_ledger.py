"""
Forecast ledger — registro persistente de pronósticos pre-partido y
evaluación de calibración contra resultados reales.

Cada llamada a /forecast/match (o prematch.py) registra un snapshot por
capa: ``model`` / ``market`` / ``blended`` y, opcionalmente, ``maturity``
(prior experto de madurez underdog-vs-potencia). La evaluación usa el
ÚLTIMO snapshot tomado ANTES del kickoff de cada partido terminado. Con
104 partidos esto convierte el ajuste del modelo en una decisión basada
en evidencia y no en anécdotas.

Métricas por capa (todas multicategoría sobre {homeWin, draw, awayWin},
con ``o`` el one-hot del resultado):

- **Brier** ``sum((p_i - o_i)^2)`` — rango [0, 2]; menor es mejor.
- **Log-loss** ``-log(p_resultado)`` — castiga el exceso de confianza.
- **RPS** (Ranked Probability Score) — respeta el orden ordinal
  home > draw > away: falla "cerca" (predecir empate cuando gana el local)
  puntúa mejor que fallar "lejos" (predecir que gana el visitante). Es el
  scoring rule estándar para fútbol.

Además del puntaje absoluto, ``evaluate`` reporta:

- **baselines** climatología (tasa base observada) y uniforme.
- **skill** de cada capa vs climatología y vs mercado (``1 - score/ref``;
  >0 = mejor que la referencia). El skill vs mercado se computa pareado,
  solo sobre los partidos donde AMBas capas tienen pronóstico.
- **strata** calibración por bucket de probabilidad del favorito — el
  bucket clearFavorite/heavyFavorite responde "¿el favorito gana tan
  seguido como predice el modelo?", el caso underdog-vs-potencia.
- **calibration** diagrama de confiabilidad (predicho vs observado) por
  decil de probabilidad, por capa.
"""

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

LEDGER_PATH = Path(__file__).parent / 'forecast_ledger.json'

# Capas puntuables. ``calibrated`` (favorite-shrink sobre el blended) y
# ``maturity`` (prior experto) solo aparecen en los snapshots que las traen;
# los partidos sin una capa simplemente no contribuyen a su resumen.
_LAYERS = ('model', 'market', 'blended', 'calibrated', 'maturity')

# Capas de pronóstico (excluye ``market``, que es la referencia externa).
_FORECAST_LAYERS = ('model', 'blended', 'calibrated', 'maturity')

_METRICS = ('brier', 'logLoss', 'rps')

# Probabilidad mínima para el log-loss (evita log(0) en empates de KO).
_EPS = 1e-12

# Cortes de probabilidad de victoria del favorito para estratificar la
# calibración. El bucket clearFavorite/heavyFavorite es el que responde
# "¿el favorito gana tan seguido como predice el modelo?" — el caso
# underdog-vs-potencia.
_FAVORITE_STRATA = (
    ('tossUp', 0.0, 0.45),
    ('lean', 0.45, 0.55),
    ('clearFavorite', 0.55, 0.70),
    ('heavyFavorite', 0.70, 1.01),
)

# Capa que define el favorito y su probabilidad en la estratificación: la
# recalibrada (producción) primero, con fallback a blended y luego al modelo
# puro. Así la reliability mide la capa que de hecho se publica.
_STRATA_LAYER_ORDER = ('calibrated', 'blended', 'model')

# Número de deciles del diagrama de confiabilidad.
_RELIABILITY_BINS = 10


def _load() -> dict:
    """Carga el ledger desde disco; ``{}`` si no existe o es ilegible."""
    if LEDGER_PATH.exists():
        try:
            return json.loads(LEDGER_PATH.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError) as err:
            log.warning('Ledger ilegible (%s) — se reinicia', err)
    return {}


def _save(ledger: dict) -> None:
    """Persiste el ledger en disco con indentación legible."""
    LEDGER_PATH.write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2), encoding='utf-8'
    )


def _key(home: str, away: str) -> str:
    """Clave canónica de un partido en el ledger."""
    return f'{home}|{away}'


def record_snapshot(
    home: str,
    away: str,
    stage: str,
    venue: str | None,
    probs: dict[str, dict[str, float] | None],
    extras: dict | None = None,
    recorded_at: datetime | None = None,
) -> None:
    """Registra un snapshot de pronóstico para un partido.

    Args:
        home: Selección local.
        away: Selección visitante.
        stage: Etapa del torneo (GROUP_STAGE, LAST_32, ...).
        venue: Sede resuelta, si se conoce.
        probs: Probabilidades por capa. Claves esperadas: ``model``,
            ``market``, ``blended`` y opcionalmente ``maturity``; cada
            valor es un dict con homeWin / draw / awayWin (draw puede ser
            None en eliminación directa) o None si la capa no aplica.
        extras: Datos adicionales a persistir (p.ej. afinidades, tier de
            madurez).
        recorded_at: Marca de tiempo del snapshot. Por defecto el instante
            actual; se pasa explícito solo para backfill histórico, donde
            debe ser anterior al kickoff para que evaluate() lo considere.
    """
    ledger = _load()
    entry = ledger.setdefault(
        _key(home, away),
        {'home': home, 'away': away, 'stage': stage, 'snapshots': []},
    )
    entry['venue'] = venue
    entry['snapshots'].append(
        {
            'recordedAtUtc': (
                recorded_at or datetime.now(timezone.utc)
            ).isoformat(timespec='seconds'),
            'probs': probs,
            'extras': extras or {},
        }
    )
    _save(ledger)
    log.info('Ledger: snapshot registrado para %s vs %s', home, away)


# ───────────────────────────── Scoring rules ───────────────────────────────


def _outcome_onehot(score_home: int, score_away: int) -> tuple[int, int, int]:
    """One-hot (homeWin, draw, awayWin) del marcador final."""
    if score_home > score_away:
        return 1, 0, 0
    if score_home == score_away:
        return 0, 1, 0
    return 0, 0, 1


def _vec(probs: dict[str, float]) -> tuple[float, float, float]:
    """(homeWin, draw, awayWin) con None → 0.0."""
    return (
        probs.get('homeWin') or 0.0,
        probs.get('draw') or 0.0,
        probs.get('awayWin') or 0.0,
    )


def _brier(
    vec: tuple[float, float, float], onehot: tuple[int, int, int]
) -> float:
    """Brier multicategoría: suma de cuadrados de residuos."""
    return sum((p - o) ** 2 for p, o in zip(vec, onehot))


def _log_loss(
    vec: tuple[float, float, float], onehot: tuple[int, int, int]
) -> float:
    """Log-loss = -log(p) de la categoría realizada (clip en _EPS)."""
    idx = onehot.index(1)
    p = min(1.0, max(_EPS, vec[idx]))
    return -math.log(p)


def _rps(
    vec: tuple[float, float, float], onehot: tuple[int, int, int]
) -> float:
    """Ranked Probability Score sobre el orden ordinal home>draw>away."""
    cum_pred = 0.0
    cum_obs = 0.0
    total = 0.0
    for k in range(len(vec) - 1):
        cum_pred += vec[k]
        cum_obs += onehot[k]
        total += (cum_pred - cum_obs) ** 2
    return total / (len(vec) - 1)


def _score(
    vec: tuple[float, float, float], onehot: tuple[int, int, int]
) -> dict[str, float]:
    """Las tres reglas de puntaje para un pronóstico vs su resultado."""
    return {
        'brier': _brier(vec, onehot),
        'logLoss': _log_loss(vec, onehot),
        'rps': _rps(vec, onehot),
    }


# ──────────────────────── Selección de snapshot / favorito ─────────────────


def _prematch_snapshot(entry: dict, kickoff_utc: str) -> dict | None:
    """Último snapshot registrado antes del kickoff (los demás se ignoran)."""
    valid = [
        s
        for s in entry.get('snapshots', [])
        if s['recordedAtUtc'] < kickoff_utc
    ]
    return valid[-1] if valid else None


def _favorite_view(
    probs: dict[str, float],
) -> tuple[float, bool] | None:
    """(prob de victoria del favorito, favorito_es_local) o None.

    El favorito es el lado con mayor probabilidad de ganar. Devuelve None
    si la capa no trae señal de victoria (ambas en 0).
    """
    home, _, away = _vec(probs)
    if home == 0.0 and away == 0.0:
        return None
    fav_is_home = home >= away
    return (home if fav_is_home else away), fav_is_home


def _stratum(p_fav: float) -> str:
    """Bucket de _FAVORITE_STRATA al que cae la prob del favorito."""
    for name, low, high in _FAVORITE_STRATA:
        if low <= p_fav < high:
            return name
    return _FAVORITE_STRATA[-1][0]


def _strata_view(snap: dict, onehot: tuple[int, int, int]) -> dict | None:
    """Bucket + resultado (fav/draw/dog) del partido para la estratificación."""
    probs = None
    for layer in _STRATA_LAYER_ORDER:
        if snap['probs'].get(layer):
            probs = snap['probs'][layer]
            break
    if not probs:
        return None
    view = _favorite_view(probs)
    if view is None:
        return None
    p_fav, fav_is_home = view
    if onehot[1] == 1:
        result = 'draw'
    else:
        fav_won = (onehot[0] == 1) == fav_is_home
        result = 'fav' if fav_won else 'dog'
    return {'stratum': _stratum(p_fav), 'pFav': p_fav, 'result': result}


def _layer_scores(
    snap: dict, onehot: tuple[int, int, int]
) -> tuple[dict, dict, dict]:
    """Puntajes por capa de un snapshot.

    Returns:
        ``(layer_probs, scores, detail)`` donde ``detail`` está indexado
        por métrica → capa (None si la capa no está en el snapshot).
    """
    layer_probs: dict[str, dict] = {}
    scores: dict[str, dict[str, float]] = {}
    detail: dict[str, dict[str, float | None]] = {
        metric: {} for metric in _METRICS
    }
    for layer in _LAYERS:
        probs = snap['probs'].get(layer)
        if probs:
            sc = _score(_vec(probs), onehot)
            layer_probs[layer] = probs
            scores[layer] = sc
            for metric in _METRICS:
                detail[metric][layer] = round(sc[metric], 4)
        else:
            for metric in _METRICS:
                detail[metric][layer] = None
    return layer_probs, scores, detail


def _match_record(entry: dict, match: dict) -> tuple[dict, dict] | None:
    """Fila de detalle + registro interno de un partido evaluable.

    Returns:
        ``(detail_row, record)`` o None si el partido no tiene snapshot
        pre-kickoff o marcador final.
    """
    snap = _prematch_snapshot(entry, match.get('utcDate', ''))
    if snap is None:
        return None
    score = match.get('score', {})
    sh, sa = score.get('home'), score.get('away')
    if sh is None or sa is None:
        return None

    onehot = _outcome_onehot(sh, sa)
    layer_probs, scores, detail = _layer_scores(snap, onehot)
    row = {
        'match': f"{entry['home']} {sh}-{sa} {entry['away']}",
        'utcDate': match.get('utcDate'),
        'recordedAtUtc': snap['recordedAtUtc'],
        'brier': detail['brier'],
        'logLoss': detail['logLoss'],
        'rps': detail['rps'],
    }
    record = {
        'onehot': onehot,
        'layerProbs': layer_probs,
        'scores': scores,
        'strata': _strata_view(snap, onehot),
    }
    return row, record


# ─────────────────────────── Agregación / resúmenes ────────────────────────


def _attach_baseline_scores(
    records: list[dict],
) -> tuple[float, float, float] | None:
    """Añade puntajes de climatología y uniforme a cada registro.

    Returns:
        El vector de climatología (tasa base observada de H/D/A) o None si
        no hay partidos.
    """
    if not records:
        return None
    n = len(records)
    clim = tuple(sum(r['onehot'][i] for r in records) / n for i in range(3))
    uniform = (1 / 3, 1 / 3, 1 / 3)
    for rec in records:
        rec['scores']['climatology'] = _score(clim, rec['onehot'])
        rec['scores']['uniform'] = _score(uniform, rec['onehot'])
    return clim


def _summarize(records: list[dict], key: str) -> dict:
    """Promedio de cada métrica para una capa/baseline sobre sus partidos."""
    rows = [r['scores'][key] for r in records if key in r['scores']]
    if not rows:
        return {
            'matches': 0,
            'meanBrier': None,
            'meanLogLoss': None,
            'meanRps': None,
        }
    n = len(rows)
    return {
        'matches': n,
        'meanBrier': round(sum(x['brier'] for x in rows) / n, 4),
        'meanLogLoss': round(sum(x['logLoss'] for x in rows) / n, 4),
        'meanRps': round(sum(x['rps'] for x in rows) / n, 4),
    }


def _baseline_summary(
    records: list[dict], clim: tuple[float, float, float] | None
) -> dict:
    """Resumen de los baselines, con las probabilidades que usan."""
    if not records or clim is None:
        return {'climatology': None, 'uniform': None}
    third = round(1 / 3, 4)
    return {
        'climatology': {
            'probs': {
                'homeWin': round(clim[0], 4),
                'draw': round(clim[1], 4),
                'awayWin': round(clim[2], 4),
            },
            **_summarize(records, 'climatology'),
        },
        'uniform': {
            'probs': {'homeWin': third, 'draw': third, 'awayWin': third},
            **_summarize(records, 'uniform'),
        },
    }


def _skill(
    records: list[dict], layer: str, ref: str, metric: str
) -> float | None:
    """Skill ``1 - mean(layer)/mean(ref)`` pareado sobre partidos comunes."""
    pairs = [
        (r['scores'][layer][metric], r['scores'][ref][metric])
        for r in records
        if layer in r['scores'] and ref in r['scores']
    ]
    if not pairs:
        return None
    mean_layer = sum(a for a, _ in pairs) / len(pairs)
    mean_ref = sum(b for _, b in pairs) / len(pairs)
    if mean_ref == 0:
        return None
    return round(1 - mean_layer / mean_ref, 4)


def _has_layer(records: list[dict], key: str) -> bool:
    """True si alguna capa/baseline ``key`` aparece en los registros."""
    return any(key in r['scores'] for r in records)


def _skill_block(records: list[dict]) -> dict:
    """Skill de cada capa vs climatología y vs mercado, por métrica."""
    present = [layer for layer in _LAYERS if _has_layer(records, layer)]
    vs_clim = {
        layer: {
            metric: _skill(records, layer, 'climatology', metric)
            for metric in _METRICS
        }
        for layer in present
    }
    vs_market = {
        layer: {
            metric: _skill(records, layer, 'market', metric)
            for metric in _METRICS
        }
        for layer in _FORECAST_LAYERS
        if layer in present
    }
    return {
        'note': '1 - score/referencia; >0 = mejor que la referencia',
        'vsClimatology': vs_clim,
        'vsMarket': vs_market,
    }


def _strata_summary(records: list[dict]) -> dict:
    """Calibración por bucket de probabilidad del favorito."""
    acc = {
        name: {
            'matches': 0,
            'sumPredFavWin': 0.0,
            'favWon': 0,
            'draws': 0,
            'dogWon': 0,
        }
        for name, _, _ in _FAVORITE_STRATA
    }
    tally = {'fav': 'favWon', 'draw': 'draws', 'dog': 'dogWon'}
    for rec in records:
        view = rec['strata']
        if view is None:
            continue
        bucket = acc[view['stratum']]
        bucket['matches'] += 1
        bucket['sumPredFavWin'] += view['pFav']
        bucket[tally[view['result']]] += 1

    out = {}
    for name, bucket in acc.items():
        n = bucket['matches']
        if n == 0:
            continue
        out[name] = {
            'matches': n,
            'meanPredictedFavWin': round(bucket['sumPredFavWin'] / n, 4),
            'obsFavWinRate': round(bucket['favWon'] / n, 4),
            'obsDrawRate': round(bucket['draws'] / n, 4),
            'obsUnderdogWinRate': round(bucket['dogWon'] / n, 4),
        }
    return out


def _reliability(records: list[dict], layer: str) -> list[dict]:
    """Diagrama de confiabilidad (predicho vs observado) por decil."""
    bins = [[0, 0.0, 0.0] for _ in range(_RELIABILITY_BINS)]
    for rec in records:
        probs = rec['layerProbs'].get(layer)
        if not probs:
            continue
        for p, o in zip(_vec(probs), rec['onehot']):
            idx = min(_RELIABILITY_BINS - 1, int(p * _RELIABILITY_BINS))
            bins[idx][0] += 1
            bins[idx][1] += p
            bins[idx][2] += o

    out = []
    for i, (count, sum_pred, sum_obs) in enumerate(bins):
        if count == 0:
            continue
        low = i / _RELIABILITY_BINS
        high = (i + 1) / _RELIABILITY_BINS
        out.append(
            {
                'bin': f'{low:.1f}-{high:.1f}',
                'count': count,
                'meanPredicted': round(sum_pred / count, 4),
                'observedFreq': round(sum_obs / count, 4),
            }
        )
    return out


def _collect(
    ledger: dict, fixtures: list[dict]
) -> tuple[list[dict], list[dict]]:
    """Filas de detalle + registros de los partidos terminados evaluables."""
    detail: list[dict] = []
    records: list[dict] = []
    for match in fixtures:
        if match.get('status') != 'FINISHED':
            continue
        home = (match.get('homeTeam') or {}).get('name', '')
        away = (match.get('awayTeam') or {}).get('name', '')
        entry = ledger.get(_key(home, away))
        if not entry:
            continue
        built = _match_record(entry, match)
        if built is None:
            continue
        row, record = built
        detail.append(row)
        records.append(record)
    return detail, records


def evaluate(fixtures: list[dict]) -> dict:
    """Evalúa el ledger contra los partidos terminados.

    Args:
        fixtures: Lista de partidos en el formato del endpoint /fixtures
            (homeTeam.name, awayTeam.name, utcDate, status, score).

    Returns:
        Dict con: ``matches`` (detalle por partido, Brier/log-loss/RPS por
        capa), ``summary`` (medias por capa), ``baselines`` (climatología y
        uniforme), ``skill`` (vs climatología y vs mercado), ``strata``
        (calibración por bucket de favorito) y ``calibration`` (diagrama de
        confiabilidad por capa).
    """
    detail, records = _collect(_load(), fixtures)
    clim = _attach_baseline_scores(records)
    return {
        'matches': detail,
        'summary': {layer: _summarize(records, layer) for layer in _LAYERS},
        'baselines': _baseline_summary(records, clim),
        'skill': _skill_block(records),
        'strata': _strata_summary(records),
        'calibration': {
            layer: _reliability(records, layer) for layer in _LAYERS
        },
    }
