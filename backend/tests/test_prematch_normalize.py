"""Tests for player-name normalisation in prematch_analysis.

Locks the Turkish dotless-ı fix: 'ı' (U+0131) is a base letter that NFD does
not fold to 'i', so it must be transliterated explicitly or Turkish names
never match their ASCII map entries (e.g. 'Yılmaz' vs 'Yilmaz').
"""

from app.services.prematch_analysis import _norm, _toks, same_player


def test_dotless_i_normalises_to_ascii_i() -> None:
    """The Turkish 'ı' folds to 'i' in both normalisers."""
    assert _norm("Yılmaz") == "yilmaz"
    assert _toks("Barış Alper Yılmaz") == ["baris", "alper", "yilmaz"]


def test_same_player_matches_across_dotless_i() -> None:
    """An ASCII map name is a subset-match of the full Turkish name."""
    assert same_player("Barış Alper Yılmaz", "Baris Yilmaz") is True


def test_same_player_still_rejects_unrelated_names() -> None:
    """The fix must not turn into an over-permissive false positive."""
    # Guards the KOR-CZE lesson: scattered token overlap must NOT match.
    assert same_player("Barış Alper Yılmaz", "Key-Shawn Wong-a-Soij") is False
