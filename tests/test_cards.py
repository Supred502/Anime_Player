"""The card dict every grid in the UI is fed.

There is one test worth having here and it is about shape, not content: a QML
ListModel fixes its role set from the first row appended to it, and a later row
missing one of those roles leaves it present but unset -- which QML reads as
`undefined` and renders as that literal word. Search results and AniList
catalog results go into the same model, so the two must describe an anime with
exactly the same keys. They didn't, and every card of every genre search and
every recommendation carried an "undefined" badge.
"""

from animeplayer.anilist.client import MediaSummary
from animeplayer.sources.hianime import SearchResult
from animeplayer.ui.backend import Backend


def _summary(**overrides) -> MediaSummary:
    defaults = dict(
        id=1, id_mal=None, title="Show", titles=("Show",), cover_url=None, banner_url=None,
        average_score=None, popularity=0, genres=(), format="TV", episodes=None,
        description=None,
    )
    defaults.update(overrides)
    return MediaSummary(**defaults)


def _result() -> SearchResult:
    return SearchResult(
        slug_id="show-1", numeric_id="1", title="Show", poster_url="", kind="TV",
        rating="", duration="24m", sub_count=12, dub_count=0,
    )


def test_both_producers_emit_the_same_keys() -> None:
    from_anilist = Backend._media_summary_to_card(_summary())
    from_source = Backend._search_result_to_card(_result())

    assert from_anilist.keys() == from_source.keys()


def test_a_card_never_omits_a_field() -> None:
    assert Backend._media_summary_to_card(_summary()).keys() == Backend._CARD_FIELDS.keys()
    assert Backend._search_result_to_card(_result()).keys() == Backend._CARD_FIELDS.keys()


def test_a_missing_score_is_blank_rather_than_zero() -> None:
    # "0.0" next to a star reads as "rated zero", which is not what an
    # unrated show means.
    assert Backend._media_summary_to_card(_summary(average_score=None))["rating"] == ""
    assert Backend._media_summary_to_card(_summary(average_score=83))["rating"] == "8.3"


def test_a_recommendation_carries_its_reason() -> None:
    card = Backend._media_summary_to_card(_summary(), "Next season of Dorohedoro")

    assert card["reason"] == "Next season of Dorohedoro"
    assert Backend._search_result_to_card(_result())["reason"] == ""
