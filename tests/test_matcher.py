from pathlib import Path
from unittest.mock import MagicMock

from animeplayer.anilist import matcher
from animeplayer.anilist.client import MediaSummary
from animeplayer.sources.hianime import SearchResult
from animeplayer.storage.db import Database


def _summary(media_id: int, title: str, **overrides) -> MediaSummary:
    defaults = dict(
        id=media_id, id_mal=None, title=title, titles=(title,), cover_url=None, banner_url=None, average_score=None,
        popularity=0, genres=(), format="TV", episodes=None, description=None,
    )
    defaults.update(overrides)
    return MediaSummary(**defaults)


def test_resolve_media_id_picks_best_match(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    client = MagicMock()
    client.search_media.return_value = [
        _summary(2293, "Hunter x Hunter"),
        _summary(2294, "Hunter x Hunter (2011)"),
    ]

    media_id = matcher.resolve_media_id("Hunter x Hunter", client, db)

    assert media_id == 2293
    db.close()


def test_resolve_media_id_caches_result(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    client = MagicMock()
    client.search_media.return_value = [_summary(2293, "Hunter x Hunter")]

    first = matcher.resolve_media_id("Hunter x Hunter", client, db)
    second = matcher.resolve_media_id("Hunter x Hunter", client, db)

    assert first == second == 2293
    client.search_media.assert_called_once()
    db.close()


def test_resolve_media_id_returns_none_when_no_good_match(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    client = MagicMock()
    client.search_media.return_value = [_summary(999, "Completely Unrelated Show")]

    media_id = matcher.resolve_media_id("Hunter x Hunter", client, db)

    assert media_id is None
    assert db.has_title_mapping("Hunter x Hunter")
    db.close()


def test_resolve_media_id_no_candidates(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    client = MagicMock()
    client.search_media.return_value = []

    media_id = matcher.resolve_media_id("Some Obscure Anime", client, db)

    assert media_id is None
    client.search_media.assert_called_once()
    db.close()


def test_resolve_media_summary_picks_best_match(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    client = MagicMock()
    client.search_media.return_value = [
        _summary(2293, "Hunter x Hunter", average_score=90),
        _summary(2294, "Hunter x Hunter (2011)", average_score=85),
    ]

    summary = matcher.resolve_media_summary("Hunter x Hunter", client, db)

    assert summary.id == 2293
    assert summary.average_score == 90
    db.close()


def test_resolve_media_summary_uses_cached_id(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    client = MagicMock()
    client.search_media.return_value = [_summary(2293, "Hunter x Hunter")]
    client.get_media_by_id.return_value = _summary(2293, "Hunter x Hunter", average_score=90)

    matcher.resolve_media_summary("Hunter x Hunter", client, db)  # populates the cache
    summary = matcher.resolve_media_summary("Hunter x Hunter", client, db)  # cache hit

    client.search_media.assert_called_once()
    client.get_media_by_id.assert_called_once_with(2293)
    assert summary.average_score == 90
    db.close()


def test_resolve_media_summary_returns_none_when_no_good_match(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    client = MagicMock()
    client.search_media.return_value = [_summary(999, "Completely Unrelated Show")]

    summary = matcher.resolve_media_summary("Hunter x Hunter", client, db)

    assert summary is None
    db.close()


def _result(slug_id: str, title: str) -> SearchResult:
    return SearchResult(
        slug_id=slug_id, numeric_id=slug_id.rsplit("-", 1)[-1], title=title,
        poster_url="", kind="TV", rating="", duration="24m", sub_count=148, dub_count=148,
    )


def test_best_source_result_picks_closest_title() -> None:
    results = [
        _result("hunter-x-hunter-2293", "Hunter x Hunter"),
        _result("hunter-x-hunter-2011-2294", "Hunter x Hunter (2011)"),
    ]

    best = matcher.best_source_result("Hunter x Hunter", results)

    assert best.slug_id == "hunter-x-hunter-2293"


def test_best_source_result_returns_none_when_no_good_match() -> None:
    results = [_result("something-else-1", "Completely Unrelated Show")]

    best = matcher.best_source_result("Hunter x Hunter", results)

    assert best is None


# -- Season/part/side-story awareness --------------------------------------
# Each of these is a wrong match that was observed live against the real
# catalogs before the scoring below existed.


def test_season_one_does_not_match_a_later_season() -> None:
    # "Sousou no Frieren" vs "Sousou no Frieren 3rd Season" scores 0.77 on
    # plain string similarity, so clicking season 1 opened season 3.
    results = [
        _result("sousou-no-frieren-3rd-7220", "Sousou no Frieren 3rd Season"),
        _result("frieren-beyond-journeys-end-481", "Frieren: Beyond Journey's End"),
    ]

    best = matcher.best_source_result(
        ("Sousou no Frieren", "Frieren: Beyond Journey's End"), results
    )

    assert best.slug_id == "frieren-beyond-journeys-end-481"


def test_later_season_does_not_fall_back_to_season_one() -> None:
    results = [_result("rezero-1387", "Re:ZERO -Starting Life in Another World-")]

    best = matcher.best_source_result(
        ("Re:Zero kara Hajimeru Isekai Seikatsu 3rd Season",), results
    )

    assert best is None


def test_season_number_is_read_however_it_is_written() -> None:
    # The two catalogs disagree on spelling in every one of these ways.
    assert matcher._season_of("Show Season 2") == 2
    assert matcher._season_of("GRANBLUE FANTASY The Animation Season2") == 2
    assert matcher._season_of("Show 2nd Season") == 2
    assert matcher._season_of("Show Season II") == 2
    assert matcher._season_of("Overlord II") == 2
    assert matcher._season_of("Psycho-Pass 3") == 3


def test_a_number_that_is_part_of_the_name_is_not_a_season() -> None:
    assert matcher._season_of("Steins;Gate 0") is None
    assert matcher._season_of("Mob Psycho 100") is None
    assert matcher._season_of("86 EIGHTY-SIX") is None
    assert matcher._season_of("Sousou no Frieren") is None


def test_a_recap_does_not_win_over_the_show_it_recaps() -> None:
    results = [
        _result("bakemonogatari-recap-1", "Bakemonogatari Recap"),
        _result("bakemonogatari-2", "Bakemonogatari (The Monogatari Series)"),
    ]

    best = matcher.best_source_result(("Bakemonogatari",), results)

    assert best.slug_id == "bakemonogatari-2"


def test_a_show_that_really_is_a_special_still_matches_one() -> None:
    # The penalty is for a mismatch, not for the word: an entry that is itself
    # a set of specials has to still be findable.
    results = [_result("high-school-dxd-specials-1", "High School DxD Specials")]

    best = matcher.best_source_result(("High School DxD Specials",), results)

    assert best.slug_id == "high-school-dxd-specials-1"


def test_an_appended_qualifier_still_matches() -> None:
    results = [_result("dorohedoro-2691", "Dorohedoro (The Complete Series)")]

    best = matcher.best_source_result(("Dorohedoro",), results)

    assert best.slug_id == "dorohedoro-2691"


def test_a_short_shared_prefix_gets_no_bonus() -> None:
    # "Monster" is a prefix of "Monster Eater" by coincidence, not because
    # they are the same show, so it must score as plain similarity rather than
    # being lifted to the prefix score the way a long title is.
    coincidence = matcher.title_score(("Monster",), ("Monster Eater",))
    real = matcher.title_score(("Bakemonogatari",), ("Bakemonogatari Series",))

    assert coincidence < matcher._PREFIX_SCORE <= real


# -- Searching under every name AniList knows -------------------------------


def test_find_source_result_searches_each_title_variant() -> None:
    # The source indexes the licensed English title and finds nothing for the
    # romaji one, which is why a single query can't be fixed by better scoring.
    catalog = {
        "demon slayer kimetsu no yaiba swordsmith village arc": [
            _result("demon-slayer-swordsmith-233", "Demon Slayer: Kimetsu no Yaiba Swordsmith Village Arc")
        ],
    }
    queried: list[str] = []

    def search(query: str) -> list[SearchResult]:
        queried.append(query)
        return catalog.get(query, [])

    best = matcher.find_source_result(
        (
            "Kimetsu no Yaiba: Katanakaji no Sato-hen",
            "Demon Slayer: Kimetsu no Yaiba Swordsmith Village Arc",
        ),
        search,
    )

    assert best.slug_id == "demon-slayer-swordsmith-233"
    assert len(queried) == 2


def test_find_source_result_stops_at_an_exact_match() -> None:
    queried: list[str] = []

    def search(query: str) -> list[SearchResult]:
        queried.append(query)
        return [_result("dorohedoro-2691", "Dorohedoro")]

    best = matcher.find_source_result(("Dorohedoro", "ドロヘドロ", "Dorohedoro TV"), search)

    assert best.slug_id == "dorohedoro-2691"
    assert queried == ["dorohedoro"]  # no reason to try the rest


def test_search_queries_drop_punctuation_and_native_script() -> None:
    # The source's search does not tokenise punctuation -- searching its own
    # title for Re:Zero season 3 verbatim returns nothing -- and its index is
    # romaji/English, so a Japanese synonym is a wasted request.
    queries = matcher.search_queries(
        ("Re:ZERO -Starting Life in Another World- Season 3", "リゼロ", "Re:Zero Season 3")
    )

    assert queries == ["re zero starting life in another world season 3", "re zero season 3"]


def test_a_single_title_string_is_not_iterated_into_characters() -> None:
    # A str is a Sequence[str], so this mistake is silent without the guard.
    assert matcher.title_score("Dorohedoro", "Dorohedoro") == 1.0
