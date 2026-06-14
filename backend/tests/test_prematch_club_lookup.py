"""Tests for club resolution in prematch_analysis.

Locks three fixes found while reviewing the Ivory Coast vs Ecuador report
(jornada 1), where several starters resolved to the wrong club:

  1. Single-letter candidate tokens (the 'a' in 'Wong-a-Soij') turned that
     map entry into a false-positive sink: 'Willian Pacho' and
     'C. Inao Oulai' both wrongly mapped to FC Volendam.
  2. Middle-name abbreviations ('E.' = Elye in 'Sepe Elye Wahi') were
     dropped because the initial was only compared against the first token.
  3. Three WC-2026 starters were absent from the map and now resolve via the
     stable API-Football id bridge (immune to romanisation/abbreviation).
"""

import json

from app.services.prematch_analysis import (
    _MAP_PATH,
    lookup_club,
    same_player,
)

_PCM = json.loads(_MAP_PATH.read_text(encoding="utf-8"))


def _apif_index() -> dict[int, dict]:
    """Rebuild the id bridge exactly as ``probable_xi`` does."""
    return {
        int(info["apif_id"]): info
        for info in _PCM.values()
        if info.get("apif_id")
    }


# ── Fix 1: single-letter token must not create a false positive ────────────


def test_short_candidate_token_is_not_a_match_sink() -> None:
    """A 1-letter candidate token must not match arbitrary target tokens.

    'Wong-a-Soij' (FC Volendam) used to absorb unrelated names through its
    'a' token. These names share no real token with it, so the result must
    not be that club.
    """
    for name in ("Willian Pacho", "C. Inao Oulai"):
        assert lookup_club(name, _PCM).get("club") != "FC Volendam"


# ── Fix 2: middle-name abbreviation resolves to the right club ─────────────


def test_middle_name_initial_matches() -> None:
    """'E. Wahi' matches 'Sepe Elye Wahi' (initial taken from a middle name)."""
    assert same_player("E. Wahi", "Sepe Elye Wahi") is True
    assert lookup_club("E. Wahi", _PCM).get("club") == "OGC Nice"


def test_abbreviation_still_requires_matching_surname() -> None:
    """The broadened initial rule must not match across different surnames."""
    assert same_player("E. Wahi", "Sepe Elye Konan") is False
    assert same_player("A. Smith", "Bob Jones") is False


# ── Fix 3: the id bridge resolves players name-matching cannot ─────────────


def test_apif_id_bridge_resolves_problem_players() -> None:
    """Lineup ids map to the correct club regardless of name format."""
    idx = _apif_index()
    expected = {
        16367: ("William Pacho", "Paris Saint-Germain FC"),
        1807: ("Evan Ndicka", "AS Roma"),
        135068: ("Emmanuel Agbadou", "Beşiktaş"),
        25414: ("John Yeboah", "Venezia FC"),
        474591: ("Christ Inao Oulaï", "Trabzonspor"),
        64190: ("Yahia Fofana", "Rizespor"),
        63964: ("Félix Torres", "SC Internacional"),
    }
    for apif_id, (name, club) in expected.items():
        info = idx.get(apif_id)
        assert info is not None, f"apif_id {apif_id} missing from bridge"
        assert info["name"] == name
        assert info["club"] == club


def test_id_bridge_beats_surname_initial_collision() -> None:
    """Surname+initial name matching collides with more famous namesakes.

    'Y. Fofana' (Yahia, the Ivorian GK) name-matches Youssouf Fofana (Milan)
    and 'F. Torres' (Félix, Ecuador) matches Ferran Torres (Barcelona). The
    id bridge must override these, which is exactly why these entries carry
    an explicit apif_id.
    """
    idx = _apif_index()
    assert idx[64190]["club"] != "AC Milan"
    assert idx[63964]["club"] != "FC Barcelona"
