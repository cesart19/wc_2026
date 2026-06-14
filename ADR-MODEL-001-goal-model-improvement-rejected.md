# ADR-MODEL-001 — Rechazo de la familia "mejorar el modelo de gol"

> Architecture Decision Record. Registra una decisión de diseño que vale la
> pena recordar — incluido un **rechazo**. Si algún día se revierte, se crea un
> ADR nuevo que supersede a este (no se edita).

- **Status:** Rejected
- **Date:** 2026-06-14
- **Deciders:** César Torres + validación design-loop (4 rondas Goldfish, sesiones frescas)
- **Project / repo:** wc_2026 · `feat/forecasting-backend`

## Context

Tras el upset **Australia 2-0 Türkiye** (2026-06-14) — donde el **modelo (33.8%
a Australia) le ganó al mercado (17.8%)** en Brier — se exploró mejorar el
modelo de pronóstico para capturar variables que hoy no ve: **compacidad
defensiva, transiciones/contragolpe, eficacia de finalización y estado-de-juego**.

Se aplicó el loop Elephants & Goldfish (document-first + validación con sesión
fresca). Se diseñaron y validaron **cuatro** enfoques; los tres design-docs
registran el detalle:
- `DESIGN_20260614_attack-defense-split.md` (§9/§10: Goldfish #1 y #2)
- `DESIGN_20260614_score-first-goal-model.md` (§10: Goldfish #3)
- `DESIGN_20260614_game-state-timestepped.md` (§10: Goldfish #4)

Restricción de fondo: el modelo en vivo es **predict() + blend de mercado**,
sobre un sampler **outcome-first** (`forecasting._sim_group` elige W/D/L y luego
condiciona los goles), con datos propios de selección **escasos** (free tier de
football-data: sin tiempos de gol ni xG).

## Options considered

1. **Split ataque/defensa `strength + residuo`.** — Contra: unidades
   incompatibles (sumar goles/partido a una fuerza en [0,1]); no arregla el
   W/D/L que motivó el trabajo.
2. **Atk/def en unidades de gol, sin tocar el W/D/L.** — Contra: el beneficio
   de GD es **arquitectónicamente imposible** — `_sim_group` fija el resultado
   primero, así que λ solo reescala el margen, no la GD ni el W/D/L.
3. **Score-first (supremacía de predict+mercado, total de mercado).** — Contra:
   **sobre-determinado**; descarta el empate **ya calibrado** del mercado
   (regresión), y el mercado de totales **ni siquiera se obtiene** hoy.
4. **Simulación time-stepped con efectos de marcador (estado-de-juego).** —
   Contra: el "fix de ρ" es **infactible** (Holgate solo admite ρ≥0 → no puede
   bajar el empate que `predict` suprime en partidos desbalanceados; además 4
   objetivos sobre 3 parámetros); **costo ~90× el MC** inviable in-request;
   `base/90` no preserva ρ; valor **admitidamente nulo** en el Brier
   pre-partido.

## Decision

**Se RECHAZA la familia de mejoras al modelo de gol.** Cuatro rondas Goldfish,
cuatro fallos bloqueantes: el apalancamiento **no** está ahí. Se conserva el
modelo actual (**predict() + blend de mercado**), que el forecast ledger muestra
**bien calibrado** (el mercado gana, y el modelo incluso le ganó al mercado en
Australia). **El cuello de botella real es de DATOS** (tiempos de gol / xG), no
del método de modelado. El trade-off aceptado: renunciar a representar
compacidad/transiciones/estado-de-juego a cambio de no degradar una calibración
que ya funciona, ni asumir costo/riesgo/complejidad sin retorno.

## Consequences

- **Positive:** El design-loop **evitó 4 implementaciones defectuosas antes de
  codear** — incluida una reescritura del path core de costo ~90× que habría
  **regresado la calibración**. Se preserva un modelo calibrado; el
  razonamiento queda documentado (3 docs + memoria); el proceso Goldfish quedó
  validado como filtro anti-complacencia. El trabajo ya entregado y valioso se
  mantiene intacto: **motor de stakes/advancement (Fases 1-3, en repo, 30 tests
  verdes, pylint 10/10)**.
- **Negative / costs:** El modelo sigue sin representar compacidad,
  transiciones, eficacia ni estado-de-juego; el pronóstico **en vivo** sigue
  siendo manual; el realismo condicional y de cola-GD no mejora. Costo de la
  exploración: ~4 design-docs + 4 validaciones con agente fresco (tiempo/tokens),
  sin código derivado.
- **Follow-up (condición para retomar):** Revisar **solo si** (a) se consiguen
  **mejores datos** (tiempos de gol minuto a minuto / xG — API-Football de pago
  o FBref/Understat); ese es el verdadero desbloqueo, no el método. O (b) el
  **pronóstico en vivo** se vuelve prioridad de producto: el "modelo en vivo"
  aditivo (arrancar la sim desde el marcador/minuto actual) es la única pieza
  data-light genuinamente útil y podría reconsiderarse **standalone**. **No**
  re-intentar las reparametrizaciones estáticas del modelo de gol (opciones 1-4).
