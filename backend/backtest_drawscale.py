"""Backtest the draw-mass calibration over jornada 1 + 2 (6 matches).

Sweeps ``_DRAW_SCALE`` (the parity-scaling constant in
``match_predictor.predict``) to test whether giving the model more draw
mass improves calibration now that the sample contains three draws, not
the lone draw of jornada 1. Reports multiclass log-loss and Brier for the
pure model layer (6 matches) and the market-blended layer (4 matches with
live odds), broken down by outcome class so the favourite-win vs draw
trade-off is explicit.

Affinity is held neutral (50/50): its effect on the win probability is
secondary by design (``_AFFINITY_K=0.12`` → <=~1% shift) and irrelevant to
the parity mapping under test, so neutralising it isolates the variable and
removes the APIF-cache dependency. Run from backend/ with the venv active.
"""

import math
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / '.env')

from app.services import match_predictor as mp  # noqa: E402

# (home, away, venue, market|None, actual: 0=home 1=draw 2=away, label)
MATCHES: list[tuple] = [
    (
        'Mexico', 'South Africa',
        'Estadio Azteca · Ciudad de México', None, 0, 'fav-win',
    ),
    (
        'South Korea', 'Czechia',
        'Estadio Akron · Guadalajara', None, 0, 'fav-win',
    ),
    (
        'United States', 'Paraguay',
        'SoFi Stadium · Los Angeles',
        (0.4596, 0.2983, 0.2421), 0, 'fav-win',
    ),
    (
        'Canada', 'Bosnia-Herzegovina',
        'BMO Field · Toronto',
        (0.5238, 0.2737, 0.2025), 1, 'draw',
    ),
    (
        'Qatar', 'Switzerland',
        "Levi's Stadium · San Francisco",
        (0.0666, 0.1453, 0.7881), 1, 'draw',
    ),
    (
        'Brazil', 'Morocco',
        'MetLife Stadium · New York/New Jersey',
        (0.5756, 0.2504, 0.1740), 1, 'draw',
    ),
]

# _DRAW_SCALE sweep: 2.0 is the current production value. Lower → more draw
# mass in imbalanced matches (the draw prob decays slower away from parity).
SCALES: tuple[float, ...] = (2.0, 1.6, 1.4, 1.2, 1.0, 0.8, 0.6)

# Production blend constants (match_predictor defaults).
ALPHA = 0.6
DRAW_BOOST = 0.2


def model_probs(
    home: str, away: str, venue: str, draw_scale: float
) -> tuple[float, float, float]:
    """Pure-model probabilities with the given draw scale, neutral affinity."""
    mp._DRAW_SCALE = draw_scale
    return mp.predictor.predict(
        home, away, stage='GROUP_STAGE', venue=venue,
        affinity_a=50.0, affinity_b=50.0,
        friendly_share_a=0.0, friendly_share_b=0.0,
    )


def log_loss(p: tuple[float, float, float], actual: int) -> float:
    """Multiclass log-loss for a single observation."""
    return -math.log(max(1e-12, p[actual]))


def brier(p: tuple[float, float, float], actual: int) -> float:
    """Multiclass Brier score for a single observation."""
    return sum((p[i] - (1.0 if i == actual else 0.0)) ** 2 for i in range(3))


def _mean(vals: list[float]) -> float | None:
    return sum(vals) / len(vals) if vals else None


def main() -> None:
    """Sweep the draw scale and print the calibration scoreboard."""
    mp._DRAW_MARKET_BOOST = DRAW_BOOST

    # Reference: baseline draw prob per match so the effect is visible.
    print('Draw probability per match by _DRAW_SCALE (model layer)')
    print(f"  {'match':<26}" + ''.join(f's={s:<5}' for s in SCALES))
    for home, away, venue, _market, _actual, label in MATCHES:
        cells = ''.join(
            f'{model_probs(home, away, venue, s)[1] * 100:4.1f} '
            for s in SCALES
        )
        print(f'  {home[:12]}-{away[:11]:<13} {cells}  [{label}]')

    print('\n' + '=' * 70)
    print('Aggregate scores by _DRAW_SCALE  (lower = better)')
    print(
        f"  {'scale':<6}"
        f"{'model_LL':>10}{'model_Br':>10}"
        f"{'blend_LL':>10}{'blend_Br':>10}"
        f"{'draw_Br':>10}{'favwin_Br':>11}"
    )

    for scale in SCALES:
        m_ll, m_br, b_ll, b_br = [], [], [], []
        draw_br, fav_br = [], []
        for home, away, venue, market, actual, label in MATCHES:
            pm = model_probs(home, away, venue, scale)
            m_ll.append(log_loss(pm, actual))
            mb = brier(pm, actual)
            m_br.append(mb)
            (draw_br if label == 'draw' else fav_br).append(mb)
            if market:
                pb = mp.predictor.blend_with_market(pm, market, alpha=ALPHA)
                b_ll.append(log_loss(pb, actual))
                b_br.append(brier(pb, actual))
        tag = '  *' if scale == 2.0 else ''
        print(
            f'  {scale:<6.1f}'
            f'{_mean(m_ll):>10.4f}{_mean(m_br):>10.4f}'
            f'{_mean(b_ll):>10.4f}{_mean(b_br):>10.4f}'
            f'{_mean(draw_br):>10.4f}{_mean(fav_br):>11.4f}{tag}'
        )

    print('\n  * = current production value (_DRAW_SCALE=2.0)')
    print('  model_* over 6 matches | blend_* over the 4 with live market')
    print('  draw_Br/favwin_Br = model Brier split by outcome class (3 + 3)')


if __name__ == '__main__':
    main()
