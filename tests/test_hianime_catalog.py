"""The catalog side of the hianime client: the home page's hero and Trending
row, the ranked catalog pages, and the filter endpoint.

Like test_hianime.py, the markup here is trimmed from real responses rather
than written by hand -- these parsers key off exact class names, attribute
order and where the whitespace falls, so invented markup would pass happily
while the live page failed. The spotlight fixture in particular keeps the
site's own indentation: the sub/dub counts there are followed by a newline
before </div>, and the card-tuned pattern that didn't allow for it read every
hero as sub=0.
"""

import httpx
import pytest
import respx

from animeplayer.sources import hianime as src

SPOTLIGHT_HTML = """
<div class="deslide-wrap"><div id="slider"><div class="swiper-wrapper">
<div class="swiper-slide">
    <div class="deslide-item">
        <div class="deslide-cover">
            <div class="deslide-cover-img">
                <img class="film-poster-img"
                    src="https://hianime.at/storage/media/attack-on-titan-banner.webp"
                    alt="Attack on Titan"
                    decoding="async">
            </div>
        </div>
        <div class="deslide-item-content">
            <div class="desi-sub-text">#1 Spotlight</div>
            <div class="desi-head-title dynamic-name"
                 data-jname="Shingeki no Kyojin">
                Attack on Titan
            </div>
            <div class="sc-detail">
                <div class="scd-item">
                    <i class="fas fa-play-circle mr-1"></i>TV
                </div>
                <div class="scd-item">
                    <i class="fas fa-clock mr-1"></i>24m
                </div>
                <div class="scd-item m-hide">
                    <i class="fas fa-calendar mr-1"></i>Apr 7, 2013
                </div>
                <div class="scd-item mr-1">
                    <span class="quality">HD</span>
                </div>
                <div class="scd-item">
                    <div class="tick">
                        <div class="tick-item tick-sub">
                            <i class="fas fa-closed-captioning mr-1"></i>25
                        </div>
                        <div class="tick-item tick-dub">
                            <i class="fas fa-microphone mr-1"></i>25
                        </div>
                    </div>
                </div>
                <div class="clearfix"></div>
            </div>
            <div class="desi-description">
                Centuries ago, mankind was slaughtered to near extinction by titans.
            </div>
            <div class="desi-buttons">
                <a href="https://hianime.at/watch/attack-on-titan-240"
                   class="btn btn-primary btn-radius mr-2">Watch Now</a>
                <a href="https://hianime.at/attack-on-titan-240"
                   class="btn btn-secondary btn-radius">Detail</a>
            </div>
        </div>
    </div>
</div>
<div class="swiper-slide">
    <div class="deslide-item">
        <div class="deslide-cover"><div class="deslide-cover-img">
            <img class="film-poster-img" src="https://hianime.at/storage/media/dandadan-banner.webp"
                alt="Dandadan" decoding="async">
        </div></div>
        <div class="deslide-item-content">
            <div class="desi-sub-text">#2 Spotlight</div>
            <div class="desi-head-title dynamic-name" data-jname="Dandadan 3rd Season">
                Dandadan 3rd Season
            </div>
            <div class="sc-detail">
                <div class="scd-item">
                    <i class="fas fa-play-circle mr-1"></i>TV (? eps)
                </div>
                <div class="clearfix"></div>
            </div>
            <div class="desi-description">
                Not yet aired.
            </div>
            <div class="desi-buttons">
                <a href="https://hianime.at/watch/dandadan-3rd-7181"
                   class="btn btn-primary btn-radius mr-2">Watch Now</a>
                <a href="https://hianime.at/dandadan-3rd-7181"
                   class="btn btn-secondary btn-radius">Detail</a>
            </div>
        </div>
    </div>
</div>
</div></div></div>
"""

TRENDING_HTML = """
<div class="trending-list" id="trending-home"><div class="swiper-container">
<div class="swiper-wrapper">
    <div class="swiper-slide">
        <div class="item">
    <div class="number">
        <span>01</span>
        <div class="film-title dynamic-name" data-jname="One Piece">One Piece</div>
    </div>
    <a href="https://hianime.at/one-piece-1" class="film-poster" title="One Piece" aria-label="One Piece">
        <img src="https://hianime.at/storage/media/one-piece.webp"
            class="film-poster-img" alt="One Piece"
            loading="lazy" decoding="async">
    </a>
    <div class="clearfix"></div>
</div>
    </div>
    <div class="swiper-slide">
        <div class="item">
    <div class="number">
        <span>02</span>
        <div class="film-title dynamic-name" data-jname="Mushoku Tensei III">Mushoku Tensei Season 3</div>
    </div>
    <a href="https://hianime.at/mushoku-tensei-6" class="film-poster" title="Mushoku Tensei Season 3">
        <img src="https://hianime.at/storage/media/mushoku-tensei.webp"
            class="film-poster-img" alt="Mushoku Tensei Season 3"
            loading="lazy" decoding="async">
    </a>
    <div class="clearfix"></div>
</div>
    </div>
</div></div></div>
"""

CARD_HTML = """
<div class="film_list-wrap">
    <div class="flw-item">
    <div class="film-poster">
        <div class="tick ltr">
            <div class="tick-item tick-sub"><i class="fas fa-closed-captioning mr-1"></i>25</div>
            <div class="tick-item tick-dub"><i class="fas fa-microphone mr-1"></i>25</div>
        </div>
        <img src="https://cdn.example.co/thumbnail/aot.jpg" class="film-poster-img" alt="Attack on Titan">
    </div>
    <div class="film-detail">
        <h3 class="film-name">
            <a href="https://hianime.at/attack-on-titan-240" title="Attack on Titan"
               class="dynamic-name" data-jname="Shingeki no Kyojin">Attack on Titan</a>
        </h3>
        <div class="fd-infor">
            <span class="fdi-item">TV</span>
            <span class="dot"></span>
            <span class="fdi-item fdi-duration">24m</span>
        </div>
    </div>
</div>
</div>
"""

# The paginator only ever renders a window of three page numbers around the
# current one, so "is there a next page" has to come from the Next link.
PAGINATION_WITH_NEXT = """
<div class="pre-pagination mt-5 mb-5"><nav aria-label="Page navigation">
<ul class="pagination pagination-lg justify-content-center">
    <li class="page-item active"><a class="page-link">1</a></li>
    <li class="page-item "><a title="Page 2" class="page-link" href="https://hianime.at/most-popular?page=2">2</a></li>
    <li class="page-item"><a title="Next" class="page-link" href="https://hianime.at/most-popular?page=2">&rsaquo;</a></li>
    <li class="page-item"><a title="Last" class="page-link" href="https://hianime.at/most-popular?page=340">&raquo;</a></li>
</ul></nav></div>
"""

PAGINATION_LAST_PAGE = """
<div class="pre-pagination mt-5 mb-5"><nav aria-label="Page navigation">
<ul class="pagination pagination-lg justify-content-center">
    <li class="page-item"><a title="Previous" class="page-link" href="https://hianime.at/most-popular?page=339">&lsaquo;</a></li>
    <li class="page-item active"><a class="page-link">340</a></li>
</ul></nav></div>
"""

SIDEBAR_HTML = """
<div id="main-sidebar">
    <div class="flw-item">
    <div class="film-detail">
        <h3 class="film-name">
            <a href="https://hianime.at/sidebar-top-10-999" title="Sidebar Top 10 Entry">Sidebar Top 10 Entry</a>
        </h3>
    </div>
</div>
</div>
"""


@pytest.fixture
def client():
    with httpx.Client() as c:
        yield c


@respx.mock
def test_home_highlights_reads_the_hero_and_the_trending_row(client) -> None:
    respx.get("https://hianime.at/home").mock(
        return_value=httpx.Response(200, text=SPOTLIGHT_HTML + TRENDING_HTML)
    )

    spotlight, trending = src.get_home_highlights(client)

    assert [s.title for s in spotlight] == ["Attack on Titan", "Dandadan 3rd Season"]
    hero = spotlight[0]
    assert hero.slug_id == "attack-on-titan-240"
    assert hero.numeric_id == "240"
    assert hero.japanese_title == "Shingeki no Kyojin"
    assert hero.banner_url.endswith("attack-on-titan-banner.webp")
    assert hero.description.startswith("Centuries ago")
    assert (hero.kind, hero.duration, hero.released) == ("TV", "24m", "Apr 7, 2013")
    # The hero's tick markup puts a newline before </div>, unlike a poster
    # card's -- a pattern that doesn't allow for it silently reads 0 here.
    assert (hero.sub_count, hero.dub_count) == (25, 25)
    assert hero.rank == 1

    assert [t.title for t in trending] == ["One Piece", "Mushoku Tensei Season 3"]
    assert trending[0].slug_id == "one-piece-1"
    assert trending[0].poster_url.endswith("one-piece.webp")


@respx.mock
def test_a_spotlight_entry_with_a_short_detail_strip_still_parses(client) -> None:
    """An upcoming show has no runtime and no air date, so its detail strip is
    one item long instead of three. Reading it positionally must not then
    report the format as the runtime."""
    respx.get("https://hianime.at/home").mock(
        return_value=httpx.Response(200, text=SPOTLIGHT_HTML)
    )

    spotlight, _ = src.get_home_highlights(client)

    upcoming = spotlight[1]
    assert upcoming.kind == "TV (? eps)"
    assert upcoming.duration == ""
    assert upcoming.released == ""
    assert (upcoming.sub_count, upcoming.dub_count) == (0, 0)


@respx.mock
def test_browse_reads_a_catalog_page(client) -> None:
    route = respx.get("https://hianime.at/most-popular").mock(
        return_value=httpx.Response(200, text=CARD_HTML + PAGINATION_WITH_NEXT)
    )

    page = src.browse("most-popular", 3, client)

    assert route.calls.last.request.url.params["page"] == "3"
    assert page.page == 3
    assert page.has_more is True
    assert [r.title for r in page.results] == ["Attack on Titan"]
    assert page.results[0].slug_id == "attack-on-titan-240"
    assert page.results[0].kind == "TV"
    assert page.results[0].dub_count == 25


@respx.mock
def test_the_last_catalog_page_reports_no_more(client) -> None:
    respx.get("https://hianime.at/most-popular").mock(
        return_value=httpx.Response(200, text=CARD_HTML + PAGINATION_LAST_PAGE)
    )

    assert src.browse("most-popular", 340, client).has_more is False


@respx.mock
def test_a_catalog_page_ignores_the_sidebars_own_card_grid(client) -> None:
    """Every catalog page repeats a "Top 10" grid in its sidebar, in the same
    card markup -- without splitting it off it lands in the results as ten
    entries that aren't part of the ranking at all."""
    respx.get("https://hianime.at/top-airing").mock(
        return_value=httpx.Response(200, text=CARD_HTML + SIDEBAR_HTML)
    )

    page = src.browse("top-airing", 1, client)

    assert [r.title for r in page.results] == ["Attack on Titan"]


def test_browse_rejects_a_category_that_is_not_a_catalog(client) -> None:
    with pytest.raises(src.SourceError):
        src.browse("../admin", 1, client)


@respx.mock
def test_browse_accepts_a_genre_path(client) -> None:
    route = respx.get("https://hianime.at/genres/isekai").mock(
        return_value=httpx.Response(200, text=CARD_HTML)
    )

    src.browse("genres/isekai", 1, client)

    assert route.called


@respx.mock
def test_filter_browse_sends_one_genre_parameter_per_genre(client) -> None:
    route = respx.get("https://hianime.at/filter").mock(
        return_value=httpx.Response(200, text=CARD_HTML + PAGINATION_WITH_NEXT)
    )

    src.filter_browse(
        client, page=2, type_="tv", status="completed", sort="avg_score",
        genres=("action", "romance"),
    )

    params = route.calls.last.request.url.params
    assert params.get_list("genre[]") == ["action", "romance"]
    assert params["type"] == "tv"
    assert params["status"] == "completed"
    assert params["sort"] == "avg_score"
    assert params["page"] == "2"


@respx.mock
def test_filter_browse_omits_unset_filters(client) -> None:
    """An empty value means "any", and the endpoint is happier with the
    parameter absent than present-and-blank."""
    route = respx.get("https://hianime.at/filter").mock(
        return_value=httpx.Response(200, text=CARD_HTML)
    )

    src.filter_browse(client, page=1)

    params = route.calls.last.request.url.params
    assert set(params.keys()) == {"page"}


@respx.mock
def test_filter_browse_flattens_punctuation_in_the_keyword(client) -> None:
    """Same reason search() does: the site's own indexer doesn't tokenise
    punctuation, so its own titles find nothing (see _search_keyword)."""
    route = respx.get("https://hianime.at/filter").mock(
        return_value=httpx.Response(200, text=CARD_HTML)
    )

    src.filter_browse(client, keyword="Re:ZERO -Starting Life-")

    assert route.calls.last.request.url.params["keyword"] == "Re ZERO Starting Life"


@respx.mock
def test_get_genres_reads_the_filter_forms_own_list(client) -> None:
    respx.get("https://hianime.at/filter").mock(
        return_value=httpx.Response(
            200,
            text="""
            <div class="ni-list">
                <div class="btn btn-sm btn-radius btn-filter-item f-genre-item" data-id="action">Action</div>
                <div class="btn btn-sm btn-radius btn-filter-item f-genre-item" data-id="action-adventure">Action &amp; Adventure</div>
                <div class="btn btn-sm btn-radius btn-filter-item f-genre-item" data-id="action">Action</div>
            </div>
            """,
        )
    )

    genres = src.get_genres(client)

    assert genres == [("action", "Action"), ("action-adventure", "Action & Adventure")]


@pytest.mark.parametrize("category", ["genres/../../etc", "genres/", "genres/Action!"])
def test_browse_rejects_a_malformed_genre_path(client, category: str) -> None:
    """The genre half of a catalog path is the one part not taken from a fixed
    list, and it goes straight into a URL."""
    with pytest.raises(src.SourceError):
        src.browse(category, 1, client)
