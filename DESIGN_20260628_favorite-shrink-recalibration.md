# 📐 Design Doc — Re-calibración del favorite-shrink (post n=62)

> Escrito antes de codear (document-first). Surge del análisis de resultados
> con la fase de grupos completa. Capa de calibración W/D/L (sidestep ADR-001:
> no es feature de gol). **Estado: PROPUESTA — ejecución diferida (ver §7).**

- **Author:** César Torres · **Date:** 2026-06-28
- **Status:** PROPOSED. Implementación P1 (knockout no-op + forma) ya en
  `feat/forecasting-backend` (commit a0037c1); esto cubre lo que queda (P2-C).
- **Reviewers:** \<tech lead\>

## 1. Problem

La capa `calibrated` (`match_predictor.apply_favorite_shrink`) encoge la masa
de victoria del favorito hacia empate+underdog. Sus parámetros
(`lam=0.5, cap=0.12, anchor=0.55, split_draw=0.7`) se fijaron desde priors con
**n=8** (jornada 1), cuando los favoritos amplios tropezaban.

Con la **fase de grupos completa (n=62 puntuados)** la premisa se **invierte**
para los buckets medios (estratificación de `evaluate()`):

| Bucket (P fav) | n | P(fav) predicha | fav gana (obs) |
|---|---|---|---|
| tossUp (<0.45) | 8 | 0.41 | 0.25 (empate 0.625) |
| lean (0.45–0.55) | 12 | 0.50 | 0.42 |
| clearFavorite (0.55–0.70) | 38 | 0.62 | **0.71** |
| heavyFavorite (≥0.70) | 4 | 0.74 | **1.00** |

Los favoritos por encima del ancla (0.55) **sobre-rinden**, no tropiezan. El
shrink los penaliza: mejoró 11 partidos y **empeoró 27** (las peores misfires
son goleadas de favorito: BEL 5-1, POR 5-0, ESP 4-0, FRA 3-0). Gana en Brier
agregado (0.510 vs blended 0.529) **solo** porque los aciertos en toss-ups
(donde los empates se concentran, 62.5%) son grandes. Es un instrumento romo:
**subsidia empates de partidos cerrados gravando aciertos de favorito claro.**

Curva de confiabilidad de `calibrated`: sub-predice sistemáticamente en
0.5–0.8 (bin 0.7–0.8: predicho 0.74 / observado 1.00). El shrink empuja hacia
abajo justo donde debería empujar hacia arriba.

## 2. Goals / non-goals

**Goals**
- Reemplazar la heurística shrink por una **recalibración guiada por la curva
  de confiabilidad** del ledger (predicho → observado), no por una premisa fija.
- Mantenerla **falsable y A/B-able** en el ledger (como hoy: capa puntuable,
  función pura del blended).
- **Reduce a identidad** con datos insuficientes (degradar sin daño).

**Non-goals**
- No toca la capa de gol/marcador (ADR-MODEL-001 sigue vigente).
- No re-escribe ratings estáticos (`team_data.py`) — eso es hindsight; ver §6.
- No cambia el comportamiento de knockout: ya es no-op (P1-B), correcto.

## 3. Evidence base

`evaluate()` sobre 62 partidos puntuados (60 grupos + ledger). Mercado sigue
mejor (Brier 0.490 / RPS 0.146); `calibrated` mejor capa propia (0.510 / 0.157);
ninguna capa propia gana al mercado todavía. El detalle por bucket y la
reliability están en §1. Reproducible: `evaluate(fixtures)` en
`forecast_ledger.py` (no requiere re-correr modelos — los snapshots están).

## 4. Proposed approach (alternativas)

**A. Recalibración isotónica / Platt por capa (recomendada cuando haya datos).**
Ajustar un mapeo monótono `p_fav → p_fav_calibrado` sobre la tabla de
confiabilidad. Captura tanto la sub-predicción de favoritos claros como la
sobre-predicción de toss-ups, sin imponer dirección. Una sola capa nueva
`recalibrated` en `_LAYERS`, A/B contra `calibrated`/`blended`/`market`.

**B. Re-anclar el shrink existente (parche mínimo).** Subir `anchor` (~0.70) y
bajar `cap`, de modo que solo toque al `heavyFavorite` y deje `clearFavorite`
intacto. Barato, pero sigue siendo unidireccional (solo encoge) y no corrige
la sobre-predicción de toss-ups.

**C. Mover masa de empate por bucket (no por favorito).** El hallazgo real es
que los empates se concentran en toss-ups. Modelar el empate como función del
bucket de paridad en vez de encoger al favorito. Más fiel al dato, más cambio.

## 5. Recommendation

**A** como destino, **gateada por tamaño de muestra**. A n=62 la superficie
sigue siendo chica y la fase de grupos ya terminó (los toss-ups/empates no se
re-juegan este torneo), así que ajustar ahora es **alto riesgo de overfit y
cero impacto en lo que resta**. Implementar A como capa `recalibrated`
falsable, **entrenada offline y validada vía A/B en el ledger**, antes del
próximo torneo o cuando se acumulen ≥2 fases de grupos.

## 6. Ratings (nota, no acción)

n=62 marca dos desajustes de prior, **a revisar en el refresh post-torneo, NO
a editar mid-torneo** (hindsight): Uruguay sobrevalorado (elo 1900, 0.67 ppg,
eliminado último) y Noruega infravalorada (1700, 2.0 ppg, avanzó con Haaland).
Las élites rindieron a su rating → reescribir elos a mano sería overfitting.

## 7. Why deferred (honest)

- **Impacto en el torneo actual: nulo.** Solo quedan knockouts, donde el shrink
  ya es no-op (P1-B). La recalibración aplica a fase de grupos.
- **Riesgo de overfit a n=62** — el mismo patrón que quemó el grid a n=8.
- Por tanto: este doc **captura el hallazgo y el plan**; la ejecución espera
  datos. Disparador: próxima fase de grupos, o acumular más partidos.

## 8. Validation plan

1. Añadir capa `recalibrated` (función pura del blended), backfill sobre los
   snapshots existentes.
2. A/B en `evaluate()`: Brier/logLoss/RPS + skill vs mercado pareado + strata.
3. Criterio de promoción: mejora la RPS vs `calibrated` **y** no degrada
   ningún bucket de favorito. Si no, se descarta y se documenta (como aquí).

## 9. Links

- Capa actual y su historia: memoria `calibrated-favorite-shrink`.
- ADR vigente sobre la capa de gol: `ADR-MODEL-001-...md`.
- Implementación P1 relacionada: commit a0037c1.
