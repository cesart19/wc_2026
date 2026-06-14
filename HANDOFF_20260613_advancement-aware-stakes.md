# 🤝 Handoff — Stakes advancement-aware (top-2 o mejor-tercero) en WC2026

> Documento de continuidad para retomar el trabajo en otra sesión sin perder
> estado. Capa 4 del framework.

- **Date / session:** 2026-06-13
- **Author:** César Torres
- **Repo / branch:** wc_2026 · `feat/forecasting-backend` (sin commit)

## Objective
Hacer que el motor de stakes razone sobre **avance real** (top-2 OR mejor de
los 8 terceros), no solo clasificación directa top-2. Como 8 de 12 terceros
avanzan, `swingTop2` confunde *supervivencia* con *sembrado*; el objetivo es
medir el avance, usarlo para el coasting, y exponerlo. El damp queda APAGADO
hasta poder backtestearlo.

## Current state
Las 3 fases planeadas están **HECHAS, testeadas y limpias**; nada se quedó a
medias. El damp de coasting sigue **apagado** (`_STAKES_COAST_DAMP=0.0`), así
que no hay cambios en predicciones en vivo.

- **Fase 1 (modelo):** nuevo `qualification.py` (cutoff cross-group de mejores
  terceros) + `compute_group_stakes` extendido con `pAdvance` / `swingAdvance`
  / `pAdvanceIfDraw` / `advanceLabel`. Retrocompatible (sin cutoff → idéntico).
- **Fase 2 (coasting):** `coast_for_match` ahora advancement-aware vía helper
  puro `_coast_value` que separa supervivencia (`swingAdvance`) de sembrado
  (`swingFirst`, con `_SEEDING_RETENTION`).
- **Fase 3 (surfacing):** endpoint `GET /forecast/stakes` + flag
  `prematch.py --stakes`, sobre helpers `build_group_state` / `match_stakes` /
  `group_stakes_report`.
- **Tests:** 27 verdes. **pylint** núcleo (qualification.py + stakes.py)
  **10.00/10**. **black** `--line-length 79` limpio.
- Validado contra datos reales: `match_stakes(Australia, Turkey)` → AUS
  pAdvance 69% / pTop2 42%, TUR 79% / 55% (coincide con el análisis manual de
  la sesión).

## Decisions made (and why)
- **Damp OFF hasta backtest** — la señal de coasting solo aparece en jornada 3
  / eliminatorias; con ~6 partidos jugados no se puede validar todavía.
- **Invariante de no-bucle** — el damp se aplica SOLO a nivel de ruta,
  post-predicción (`match_predictor.apply_coast_damp`); la sim de stakes llama
  a `predict` SIN damp. No mover el damp dentro de `predict`/`_sim_group`.
- **`_SEEDING_RETENTION=0.5`** — perilla conductual (cuánto retiene el
  incentivo de sembrado al coasting), es una conjetura sin validar; tunear en
  el backtest.
- **`build_group_state` pliega resultados jugados** (a diferencia del fallback
  `forecasting._build_groups_from_fixtures`, que pone la tabla en cero) para
  que los stakes reflejen la tabla viva.
- **Cutoff por muestreo** (`advances_sample`, 1 sorteo por sim) por rendimiento
  dentro del Monte-Carlo de stakes.
- **Disables de pylint acotados** en `compute_group_stakes` y `coast_for_match`
  (kernel Monte-Carlo denso; partirlo perjudica claridad/velocidad). El R0801
  pre-existente (duplicación de las llamadas a `record_snapshot` entre
  `forecast.py` y `prematch_analysis.py`) se dejó como está — no lo introdujo
  este trabajo.

## Next steps (in order)
1. **Decidir commit** — todo está sin commitear en `feat/forecasting-backend`.
   OJO: `forecast_ledger.json` también cambió (snapshots de prematch de esta
   sesión, ver abajo) — decidir si entra en el commit.
2. **Backtest del damp vs el ledger** cuando exista data de jornada 3
   (~24-26 jun): medir Brier/log-loss con el damp encendido a distintos
   `_STAKES_COAST_DAMP` y `_SEEDING_RETENTION`, luego prender la bandera.
3. **Cachear el cutoff** antes de prender: hoy `coast_for_match` y
   `/forecast/stakes` reconstruyen el cutoff por llamada (un MC completo del
   grupo, lento). Cachear por estado-de-grupos / por request.
4. (Opcional) Portar `group_stakes_report` al CLI `stakes_report.py` para
   paridad con el endpoint.

## Files touched / relevant
**Nuevos:**
- `backend/app/services/qualification.py` — modelo cross-group de terceros:
  `build_cutoff`, `ThirdPlaceCutoff.advance_prob/advances_sample`.
- `backend/tests/test_qualification.py`, `test_stakes_advance.py`,
  `test_coast.py`, `test_stakes_report.py` — 27 tests.
- `backend/conftest.py` — pone `backend/` en `sys.path` para pytest.
- `backend/requirements-dev.txt` — pytest / black / pylint.

**Modificados (código):**
- `backend/app/services/stakes.py` — núcleo del feature: extensión de
  `compute_group_stakes`, `_advance_label`, `_coast_value`, `coast_for_match`
  recableado, `build_group_state`, `_apply_result`, `_remaining_dicts`,
  `match_stakes`, `group_stakes_report`. Constantes `_SEEDING_RETENTION`,
  `_CUTOFF_SIMS`. (Se quitó un `import random` muerto.)
- `backend/app/routes/forecast.py` — endpoint `GET /forecast/stakes`.
- `backend/app/services/prematch_analysis.py` — `run_prematch(with_stakes=…)`
  añade `report["stakes"]`.
- `backend/prematch.py` — flag `--stakes` + línea de render.

**Modificado (datos, NO código):**
- `backend/app/services/forecast_ledger.json` — snapshots pre-kickoff
  registrados al correr `prematch.py` esta sesión (Australia-Turkey + los 4
  partidos restantes del Grupo D). Son lecturas tempranas (13-jun); conviene
  re-correr cada partido cerca de su kickoff.

## Risks / pending items / open questions
- **`_SEEDING_RETENTION=0.5` sin validar** — afecta el coast cuando se prenda.
- **Endpoint pesado** — `/forecast/stakes` corre MC por grupo + build del
  cutoff; lento para los 12 grupos. Sin caché aún (ver paso 3).
- **Standings de football-data vacíos** — `build_group_state` deriva la tabla
  de los FINISHED (funciona). Pero `forecasting.run_forecast` sigue usando
  `_build_groups_from_fixtures`, que pone resultados en cero — issue
  pre-existente, fuera de alcance de este trabajo.
- **R0801 pre-existente** (duplicate-code de `record_snapshot`) sin resolver.

## How to verify
```bash
cd "backend"
source venv/bin/activate
pip install -r requirements-dev.txt        # pytest/black/pylint en el venv

python -m pytest tests/ -q                 # → 27 passed
pylint app/services/qualification.py app/services/stakes.py --disable=import-error  # → 10.00/10
black --line-length 79 --skip-string-normalization --check \
      app/services/qualification.py app/services/stakes.py tests/

# Verificar que el damp sigue apagado:
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

# Endpoint (con el backend corriendo en :8000):
# curl 'http://localhost:8000/forecast/stakes?group=D&sims=8000'

# prematch con stakes (corre API-Football + registra snapshot):
# python prematch.py "Australia" "Turkey" --date 2026-06-14 --stakes
```
