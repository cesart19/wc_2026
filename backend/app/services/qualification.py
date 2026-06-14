"""Cross-group third-place qualification model (FIFA WC 2026, Annex C).

The 8 best third-placed teams across the 12 groups advance to the Round of
32. Whether a given third-place finish qualifies depends on the OTHER 11
groups' thirds, so it cannot be decided group-locally -- which is why the
stakes engine needs this module to reason about *advancement* (top-2 OR
best-third) instead of only direct top-2 qualification.

The group stage is Monte-Carlo'd once and the per-group third-place line of
each simulated world is cached. ``ThirdPlaceCutoff`` then answers, for any
candidate third with stats (points, GD, GF): in what fraction of worlds would
it rank among the 8 best thirds? Comparison is lexicographic on (points, GD,
GF) -- the same ordering the production simulator uses
(``forecasting._simulate_once``); FIFA's later tiebreakers (head-to-head,
fair play, drawing of lots) are out of scope here, as elsewhere in the model.

Pure: it takes already-parsed group state and reuses the production goal
sampler, so it runs offline (no live fetch), mirroring ``stakes``.
"""

import random

from app.services.forecasting import _sim_group
from app.services.venues import get_venue

# Of the 12 third-placed teams, the best 8 advance (Annex C).
THIRDS_ADVANCING = 8

# A third-placed team's final standing line, ordered as the rankers compare:
# (points, goal difference, goals for).
ThirdStats = tuple[int, int, int]


def _third_of_group(grp: dict) -> ThirdStats | None:
    """Simulate one group's remaining matches and return its third's line.

    Args:
        grp: A group (the ``forecasting._build_groups`` shape): ``teams`` carry
            ``id``/``name``/``pts``/``gd``/``gf``/``ppg`` and ``remaining`` is
            a list of ``(home_id, away_id)`` tuples.

    Returns:
        ``(points, gd, gf)`` of the third-placed team, or ``None`` if the
        group has fewer than three teams.
    """
    name_of = {t['id']: t['name'] for t in grp['teams']}
    ppg_of = {t['id']: t['ppg'] for t in grp['teams']}
    table = {t['id']: [t['pts'], t['gd'], t['gf']] for t in grp['teams']}
    for id_a, id_b in grp['remaining']:
        if id_a not in table or id_b not in table:
            continue
        na, nb = name_of[id_a], name_of[id_b]
        # res = (pts_a, gd_a, gf_a, pts_b, gd_b, gf_b)
        res = _sim_group(
            na, nb, ppg_of[id_a], ppg_of[id_b], venue=get_venue(na, nb)
        )
        for tid, off in ((id_a, 0), (id_b, 3)):
            table[tid][0] += res[off]
            table[tid][1] += res[off + 1]
            table[tid][2] += res[off + 2]
    ranked = sorted(table, key=table.__getitem__, reverse=True)
    if len(ranked) < 3:
        return None
    line = table[ranked[2]]
    return (line[0], line[1], line[2])


def _simulate_group_thirds(groups: list[dict]) -> dict[str, ThirdStats]:
    """Sample one world: the third-place line of every ranked group.

    Returns:
        ``{group_letter: (points, gd, gf)}`` for every group with a third.
    """
    thirds: dict[str, ThirdStats] = {}
    for grp in groups:
        line = _third_of_group(grp)
        if line is not None:
            thirds[grp['name']] = line
    return thirds


class ThirdPlaceCutoff:
    """Empirical distribution of the best-thirds qualification line.

    Holds one ``{group_letter: (pts, gd, gf)}`` mapping per simulated world.
    Query deterministically with :meth:`advance_prob`, or draw a single world
    with :meth:`advances_sample` for nesting inside another Monte-Carlo loop.
    """

    def __init__(self, samples: list[dict[str, ThirdStats]]) -> None:
        self._samples = samples

    def __len__(self) -> int:
        return len(self._samples)

    @staticmethod
    def _in_top8(cand: ThirdStats, others: list[ThirdStats]) -> bool:
        """True if ``cand`` ranks among the 8 best of itself + ``others``.

        Ties favour the candidate: an equal third (``o == cand``) is not
        counted as strictly better, matching "would it be drawn in".
        """
        better = sum(1 for o in others if o > cand)
        return better < THIRDS_ADVANCING

    def advance_prob(
        self, stats: ThirdStats, exclude_group: str | None = None
    ) -> float:
        """Fraction of worlds where this third ranks among the best 8.

        Args:
            stats: Candidate third-placed team's final ``(pts, gd, gf)``.
            exclude_group: The candidate's own group letter, dropped from each
                world so it competes against the other 11 thirds only.
        """
        if not self._samples:
            return 0.0
        hits = 0
        for world in self._samples:
            others = [v for g, v in world.items() if g != exclude_group]
            if self._in_top8(stats, others):
                hits += 1
        return hits / len(self._samples)

    def advances_sample(
        self,
        stats: ThirdStats,
        exclude_group: str | None,
        rng: random.Random | None = None,
    ) -> bool:
        """Qualify check against a single randomly drawn world.

        Cheaper than :meth:`advance_prob` for nesting inside a Monte-Carlo:
        one draw per call is unbiased across many calls. Uses the module's
        global RNG unless an explicit ``rng`` is supplied.
        """
        if not self._samples:
            return False
        chooser = rng or random
        world = chooser.choice(self._samples)
        others = [v for g, v in world.items() if g != exclude_group]
        return self._in_top8(stats, others)


def build_cutoff(groups: list[dict], n_sims: int = 2000) -> ThirdPlaceCutoff:
    """Monte-Carlo the group stage to sample the best-thirds line.

    Args:
        groups: All groups (the ``forecasting._build_groups`` shape). Pass the
            full set of 12 for an accurate cutoff; the focal group is dropped
            per-query via ``exclude_group``.
        n_sims: Number of full group-stage simulations to sample.

    Returns:
        A :class:`ThirdPlaceCutoff` over ``n_sims`` sampled worlds.
    """
    samples = [_simulate_group_thirds(groups) for _ in range(n_sims)]
    return ThirdPlaceCutoff(samples)
