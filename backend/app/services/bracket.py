"""
Bracket oficial FIFA WC 2026.
Portado de frontend/src/js/app.js (KNOCKOUT_BRACKET, líneas 15-54).

Slots de fase de grupos:
  w_X  = ganador del Grupo X
  r_X  = subcampeón del Grupo X
  t_XY… = mejor 3° de los grupos listados (Annex C)

Slots de fase eliminatoria:
  win_NNNNNN  = ganador del partido con ese ID
  lose_NNNNNN = perdedor del partido con ese ID (solo para 3er lugar)
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Cuadro oficial del torneo
# ---------------------------------------------------------------------------

KNOCKOUT_BRACKET: dict[int, dict[str, str]] = {
    # ── LAST_32 (Ronda de 32) ───────────────────────────────────────────
    537417: {"home": "r_A",        "away": "r_B"},
    537423: {"home": "w_C",        "away": "r_F"},
    537415: {"home": "w_E",        "away": "t_ABCDF"},
    537418: {"home": "w_F",        "away": "r_C"},
    537424: {"home": "r_E",        "away": "r_I"},
    537416: {"home": "w_I",        "away": "t_CDFGH"},
    537425: {"home": "w_A",        "away": "t_CEFHI"},
    537426: {"home": "w_L",        "away": "t_EHIJK"},
    537422: {"home": "w_D",        "away": "t_BEFIJ"},
    537421: {"home": "w_G",        "away": "t_AEHIJ"},
    537420: {"home": "r_K",        "away": "r_L"},
    537419: {"home": "w_H",        "away": "r_J"},
    537429: {"home": "w_B",        "away": "t_EFGIJ"},
    537428: {"home": "w_J",        "away": "r_H"},
    537427: {"home": "w_K",        "away": "t_DEIJL"},
    537430: {"home": "r_D",        "away": "r_G"},
    # ── LAST_16 (Ronda de 16) ───────────────────────────────────────────
    537376: {"home": "win_537417", "away": "win_537415"},
    537375: {"home": "win_537416", "away": "win_537424"},
    537377: {"home": "win_537418", "away": "win_537423"},
    537378: {"home": "win_537425", "away": "win_537426"},
    537379: {"home": "win_537422", "away": "win_537421"},
    537380: {"home": "win_537429", "away": "win_537428"},
    537381: {"home": "win_537420", "away": "win_537419"},
    537382: {"home": "win_537427", "away": "win_537430"},
    # ── QUARTER_FINALS ──────────────────────────────────────────────────
    537383: {"home": "win_537376", "away": "win_537375"},
    537384: {"home": "win_537377", "away": "win_537378"},
    537385: {"home": "win_537379", "away": "win_537380"},
    537386: {"home": "win_537381", "away": "win_537382"},
    # ── SEMI_FINALS ─────────────────────────────────────────────────────
    537387: {"home": "win_537383", "away": "win_537384"},
    537388: {"home": "win_537385", "away": "win_537386"},
    # ── FINAL ───────────────────────────────────────────────────────────
    537390: {"home": "win_537387", "away": "win_537388"},
    # ── TERCER LUGAR (no necesario para campeón, incluido por completitud)
    537389: {"home": "lose_537387", "away": "lose_537388"},
}

# Orden de simulación: las dependencias deben resolverse antes de usarse.
# El 3er lugar va al final y se omite en el cálculo del campeón.
BRACKET_ORDER: list[int] = [
    # R32
    537417, 537423, 537415, 537418, 537424, 537416,
    537425, 537426, 537422, 537421, 537420, 537419,
    537429, 537428, 537427, 537430,
    # R16
    537376, 537375, 537377, 537378,
    537379, 537380, 537381, 537382,
    # QF
    537383, 537384, 537385, 537386,
    # SF
    537387, 537388,
    # Final
    537390,
    # 3er lugar (último para no interferir con el campeón)
    537389,
]

# ID del partido final
FINAL_MATCH_ID = 537390


# ---------------------------------------------------------------------------
# Resolución de slots
# ---------------------------------------------------------------------------

def resolve_slot(
    slot: str,
    slots: dict[str, dict],
    match_results: dict[int, dict],
) -> dict | None:
    """
    Resuelve un slot del bracket a un dict de equipo.

    Tipos de slot:
      "w_A"        → ganador del grupo A  (en `slots`)
      "r_B"        → subcampeón grupo B   (en `slots`)
      "t_CDFGH"    → 3° asignado por Annex C (en `slots`)
      "win_537417" → ganador del partido 537417 (en `match_results`)
      "lose_537387"→ perdedor del partido 537387 (en `match_results`)
    """
    if slot.startswith("win_") or slot.startswith("lose_"):
        prefix, mid = slot.split("_", 1)
        match_id = int(mid)
        result = match_results.get(match_id)
        if result is None:
            return None
        return result["winner"] if prefix == "win" else result["loser"]
    return slots.get(slot)
