"""
Forecast ledger — registro persistente de pronósticos pre-partido y
evaluación de calibración contra resultados reales.

Cada llamada a /forecast/match registra un snapshot (modelo, mercado,
blended). La evaluación usa el ÚLTIMO snapshot tomado ANTES del kickoff
de cada partido terminado y calcula el Brier score multicategoría por
capa, acumulado sobre el torneo. Con 104 partidos esto convierte el
ajuste del modelo en una decisión basada en evidencia y no en anécdotas.

Brier multicategoría: sum((p_i - o_i)^2) sobre {homeWin, draw, awayWin},
donde o es el one-hot del resultado. Rango [0, 2]; menor es mejor.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

LEDGER_PATH = Path(__file__).parent / "forecast_ledger.json"

_LAYERS = ("model", "market", "blended")


def _load() -> dict:
    if LEDGER_PATH.exists():
        try:
            return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as err:
            log.warning("Ledger ilegible (%s) — se reinicia", err)
    return {}


def _save(ledger: dict) -> None:
    LEDGER_PATH.write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _key(home: str, away: str) -> str:
    return f"{home}|{away}"


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
        probs: Probabilidades por capa. Claves esperadas: "model",
            "market", "blended"; cada valor es un dict con homeWin /
            draw / awayWin (draw puede ser None en eliminación directa)
            o None si la capa no está disponible.
        extras: Datos adicionales a persistir (p.ej. afinidades usadas).
        recorded_at: Marca de tiempo del snapshot. Por defecto el instante
            actual; se pasa explícito solo para backfill histórico, donde
            debe ser anterior al kickoff para que evaluate() lo considere.
    """
    ledger = _load()
    entry = ledger.setdefault(
        _key(home, away),
        {"home": home, "away": away, "stage": stage, "snapshots": []},
    )
    entry["venue"] = venue
    entry["snapshots"].append(
        {
            "recordedAtUtc": (
                recorded_at or datetime.now(timezone.utc)
            ).isoformat(timespec="seconds"),
            "probs": probs,
            "extras": extras or {},
        }
    )
    _save(ledger)
    log.info("Ledger: snapshot registrado para %s vs %s", home, away)


def _outcome_onehot(score_home: int, score_away: int) -> tuple[int, int, int]:
    if score_home > score_away:
        return 1, 0, 0
    if score_home == score_away:
        return 0, 1, 0
    return 0, 0, 1


def _brier(probs: dict[str, float], onehot: tuple[int, int, int]) -> float:
    vec = (
        probs.get("homeWin") or 0.0,
        probs.get("draw") or 0.0,
        probs.get("awayWin") or 0.0,
    )
    return sum((p - o) ** 2 for p, o in zip(vec, onehot))


def _prematch_snapshot(entry: dict, kickoff_utc: str) -> dict | None:
    """Último snapshot registrado antes del kickoff (los demás se ignoran)."""
    valid = [
        s
        for s in entry.get("snapshots", [])
        if s["recordedAtUtc"] < kickoff_utc
    ]
    return valid[-1] if valid else None


def evaluate(fixtures: list[dict]) -> dict:
    """Evalúa el ledger contra los partidos terminados.

    Args:
        fixtures: Lista de partidos en el formato del endpoint /fixtures
            (homeTeam.name, awayTeam.name, utcDate, status, score).

    Returns:
        Dict con detalle por partido y resumen Brier acumulado por capa.
    """
    ledger = _load()
    detail: list[dict] = []
    totals: dict[str, list[float]] = {layer: [] for layer in _LAYERS}

    for m in fixtures:
        if m.get("status") != "FINISHED":
            continue
        home = (m.get("homeTeam") or {}).get("name", "")
        away = (m.get("awayTeam") or {}).get("name", "")
        entry = ledger.get(_key(home, away))
        if not entry:
            continue
        snap = _prematch_snapshot(entry, m.get("utcDate", ""))
        if snap is None:
            continue
        score = m.get("score", {})
        sh, sa = score.get("home"), score.get("away")
        if sh is None or sa is None:
            continue
        onehot = _outcome_onehot(sh, sa)
        row = {
            "match": f"{home} {sh}-{sa} {away}",
            "utcDate": m.get("utcDate"),
            "recordedAtUtc": snap["recordedAtUtc"],
            "brier": {},
        }
        for layer in _LAYERS:
            probs = snap["probs"].get(layer)
            if probs:
                b = round(_brier(probs, onehot), 4)
                row["brier"][layer] = b
                totals[layer].append(b)
            else:
                row["brier"][layer] = None
        detail.append(row)

    summary = {
        layer: {
            "matches": len(vals),
            "meanBrier": round(sum(vals) / len(vals), 4) if vals else None,
        }
        for layer, vals in totals.items()
    }
    return {"matches": detail, "summary": summary}
