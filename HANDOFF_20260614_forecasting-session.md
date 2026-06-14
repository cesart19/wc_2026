# 🤝 Handoff — Sesión forecasting WC2026 (2026-06-14)

> Continuidad para retomar sin re-derivar contexto. **Supersede a**
> `HANDOFF_20260613_advancement-aware-stakes.md` (lo engloba y actualiza).

- **Date / session:** 2026-06-14
- **Author:** César Torres
- **Repo / branch:** wc_2026 · `feat/forecasting-backend` (TODO sin commit)

## Objetivo
Dos hilos esta sesión: (a) **productizar stakes "advancement-aware"** (top-2 o
mejor-tercero) — entregado y testeado; (b) **explorar mejorar el modelo de gol**
para capturar lo que no ve (compacidad/transiciones/estado-de-juego) —
**RECHAZADO** vía design-loop. Más fixes operativos (alineaciones, normalización
turca) durante Australia-Türkiye.

## Estado actual
**HECHO y verde:**
- **Stakes advancement-aware (Fases 1-3):** `qualification.py` (cutoff
  cross-group de terceros) + `compute_group_stakes` extendido (`pAdvance`,
  `swingAdvance`, `pAdvanceIfDraw`, `advanceLabel`) + `coast_for_match` con
  split supervivencia/sembrado (`_coast_value`) + endpoint `GET /forecast/stakes`
  + flag `prematch.py --stakes`. **30 tests verdes**, pylint **10/10**
  (qualification.py + stakes.py), black 79. **Damp APAGADO**
  (`_STAKES_COAST_DAMP=0.0`) — sin cambios en vivo.
- **Fix 'ı' turca** en `prematch_analysis.py` (`_toks`/`_norm`) + test
  (`tests/test_prematch_normalize.py`). Resolvió Yılmaz→Galatasaray por nombre.
- **Snapshots confirmed-XI** de Australia-Türkiye en el ledger
  (`method=prematch_confirmed_xi_v2`); el partido terminó **Australia 2-0**
  (modelo 33.8% a Aus le ganó al mercado 17.8% en Brier).

**HECHO y CERRADO (rechazado):**
- Exploración del **modelo de gol**: 4 diseños, **los 4 bloqueados por Goldfish**
  → **RECHAZADO** (`ADR-MODEL-001`). 3 design-docs + ADR escritos.

**SIN HACER / pendiente:**
- **Ningún commit.** Todo en working tree de `feat/forecasting-backend`.
- Backtest del damp de coasting + subir `_STAKES_COAST_DAMP` → solo viable en
  jornada 3 (~24-26 jun).

## Decisiones tomadas (y por qué)
- **Damp de coasting OFF hasta backtest** — la señal solo aparece en jornada 3
  / eliminatorias; con ~7 partidos no se puede validar.
- **Invariante de no-bucle:** el damp se aplica solo a nivel de ruta
  (post-predict); la sim de stakes llama a `predict` SIN damp. No moverlo dentro
  de `predict`/`_sim_group`.
- **`build_group_state` pliega resultados jugados** (a diferencia del fallback
  de forecasting que pone la tabla en cero) → stakes reflejan la tabla viva.
- **Familia "mejorar modelo de gol" RECHAZADA** (4/4 Goldfish bloqueantes;
  ver `ADR-MODEL-001`): predict+mercado **ya calibra** (el mercado gana; el
  modelo le ganó en Australia), y el **cuello de botella real es DATOS**
  (tiempos de gol/xG, no free tier), no el método. **No** re-intentar
  reparametrizaciones estáticas del modelo de gol.
- **Nota de calibración (empates jornada 1):** 2 fueron ruido fortuito
  (penal/autogol: Canada, Qatar) y 1 fue coasting (Brasil) → **no bajar el peso
  del blend** con esa muestra (sería sobreajustar a ruido). Registrada en
  memoria `advancement-aware-stakes`.

## Próximos pasos (en orden)
1. **Decidir el commit** de todo lo pendiente (feature de stakes + fix turco +
   tests + 3 docs + ADR). **OJO:** `forecast_ledger.json` también cambió
   (snapshots de prematch de hoy) — decidir si entra. Actualizar/retirar los
   handoffs viejos del commit según convenga.
2. **Backtest del damp + subir `_STAKES_COAST_DAMP`** — solo en jornada 3
   (~24-26 jun); **cachear el cutoff** antes de prender (hoy se reconstruye por
   llamada). Tunear `_SEEDING_RETENTION` (0.5 es conjetura).
3. **Operación prematch/ledger:** re-correr `prematch.py` de cada partido cerca
   del kickoff (los snapshots de jornada 2/3 ya registrados son tempranos).
4. **Modelo de gol:** NO retomar salvo (a) conseguir datos de tiempos de gol/xG,
   o (b) priorizar el "modelo en vivo" standalone — ver `ADR-MODEL-001` §Follow-up.

## Archivos tocados / relevantes
**Código modificado:**
- `backend/app/services/stakes.py` — núcleo del feature (extensión
  compute_group_stakes, `_advance_label`, `_coast_value`, coast_for_match,
  `build_group_state`, `_remaining_dicts`, `match_stakes`,
  `group_stakes_report`; constantes `_SEEDING_RETENTION`, `_CUTOFF_SIMS`).
- `backend/app/routes/forecast.py` — endpoint `GET /forecast/stakes`.
- `backend/app/services/prematch_analysis.py` — `run_prematch(with_stakes=…)` +
  **fix 'ı' turca** en `_toks`/`_norm`.
- `backend/prematch.py` — flag `--stakes` + render.
- `backend/app/services/forecast_ledger.json` — **datos** (snapshots confirmed-XI
  + Grupo D), no código.

**Código nuevo:**
- `backend/app/services/qualification.py` — modelo cross-group de terceros.
- `backend/tests/` — `test_qualification.py`, `test_stakes_advance.py`,
  `test_coast.py`, `test_stakes_report.py`, `test_prematch_normalize.py` (30).
- `backend/conftest.py`, `backend/requirements-dev.txt` (pytest/black/pylint).

**Docs / decisiones:**
- `DESIGN_20260614_attack-defense-split.md` (SUPERADO; Goldfish #1-#2).
- `DESIGN_20260614_score-first-goal-model.md` (BLOQUEADO; Goldfish #3).
- `DESIGN_20260614_game-state-timestepped.md` (RECHAZADO; Goldfish #4).
- `ADR-MODEL-001-goal-model-improvement-rejected.md` (status Rejected).

## Riesgos / dudas abiertas
- **Todo sin commit**; `forecast_ledger.json` es dato (decidir alcance del commit).
- Damp de coasting **sin validar** (J3); `_SEEDING_RETENTION=0.5` es conjetura.
- `/forecast/stakes` es **pesado** (reconstruye el cutoff por llamada) → cachear
  antes de uso intensivo.
- pylint de `prematch_analysis.py` ~9.2 (pre-existente, no es código nuevo); el
  R0801 (duplicado de `record_snapshot` entre forecast.py y prematch_analysis.py)
  es pre-existente.
- "Aidan O'Neill" sigue sin casar por nombre (variante a/e); en producción lo
  resuelve `apif_id`, así que es inocuo.

## Cómo verificar
```bash
cd "backend"
source venv/bin/activate
pip install -r requirements-dev.txt

python -m pytest tests/ -q                  # → 30 passed
pylint app/services/qualification.py app/services/stakes.py --disable=import-error  # → 10.00/10
black --line-length 79 --skip-string-normalization --check \
      app/services/qualification.py app/services/stakes.py app/services/prematch_analysis.py tests/

# Damp sigue apagado:
python -c "from app.services.match_predictor import _STAKES_COAST_DAMP as d; print('damp', d)"  # → 0.0

# Demo del feature (sin efectos secundarios):
python -c "
import asyncio, random; from dotenv import load_dotenv; load_dotenv('.env')
from app.services.football_api import get_matches
from app.services.stakes import group_stakes_report
random.seed(3)
r = group_stakes_report(asyncio.run(get_matches()), group='D', n_sims=6000, cutoff_sims=1200)
[print(t['name'], t['pAdvance'], t['pTop2']) for t in r['groups']['D']['teams']]
"
```
