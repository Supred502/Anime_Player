"""GraphQL client for AniList (https://graphql.anilist.co).

Login uses AniList's "Auth Pin" implicit-grant variant: the user authorizes in
their browser and AniList shows them the access token to copy into the app,
rather than this app running a local HTTP server to catch a redirect. That's
AniList's own documented recommendation for apps without a redirect server --
see https://docs.anilist.co/guide/auth/ ("Auth Pin"). To use it, the user's
AniList API client (created at anilist.co/settings/developer) must have its
Redirect URL set to exactly https://anilist.co/api/v2/oauth/pin.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

API_URL = "https://graphql.anilist.co"
AUTHORIZE_URL_TEMPLATE = "https://anilist.co/api/v2/oauth/authorize?client_id={client_id}&response_type=token"

_VIEWER_QUERY = """
query {
  Viewer { id name }
}
"""

_MEDIA_LIST_COLLECTION_QUERY = """
query ($userId: Int!) {
  MediaListCollection(userId: $userId, type: ANIME) {
    lists {
      entries {
        status
        progress
        score
        media {
          id
          title { romaji english }
          synonyms
          coverImage { large }
          genres
          popularity
        }
      }
    }
  }
}
"""

_MEDIA_FIELDS = """
    id
    idMal
    title { romaji english }
    synonyms
    coverImage { large }
    bannerImage
    averageScore
    popularity
    genres
    format
    episodes
    description(asHtml: false)
"""

_MEDIA_SEARCH_QUERY = f"""
query ($search: String) {{
  Page(perPage: 5) {{
    media(search: $search, type: ANIME) {{
      {_MEDIA_FIELDS}
    }}
  }}
}}
"""

_MEDIA_BY_ID_QUERY = f"""
query ($id: Int!) {{
  Media(id: $id) {{
    {_MEDIA_FIELDS}
  }}
}}
"""

# genre_in/tag_in are AniList's own catalog filters -- this is the whole reason
# genre/tag search goes through AniList rather than the streaming source: the
# catalog and genre taxonomy are both far smaller (confirmed live: ~20-30
# results for a single source-side genre filter vs AniList's hundreds).
# pageInfo.hasNextPage lets the UI offer "Load more" instead of silently
# capping results at one page of 50.
#
# format_in/format_not_in are built dynamically (see _build_filter_search_query
# below) rather than always-present optional variables like genres/tags are --
# confirmed live against the real API that AniList's server 500s whenever a
# $formats/$notFormats variable of type [MediaFormat] is present in the query
# at all and passed null, even though the exact same null-when-unused pattern
# works fine for the [String]-typed genre/tag variables. Passing [] instead of
# null avoids the 500 but silently matches zero results instead of "no
# filter" -- the argument has to be left out of the query text entirely.
def _build_filter_search_query(has_formats: bool, has_not_formats: bool) -> str:
    format_vars = []
    format_args = []
    if has_formats:
        format_vars.append("$formats: [MediaFormat]")
        format_args.append("format_in: $formats")
    if has_not_formats:
        format_vars.append("$notFormats: [MediaFormat]")
        format_args.append("format_not_in: $notFormats")
    extra_vars = ("\n  " + ", ".join(format_vars) + ",") if format_vars else ""
    extra_args = (" " + ", ".join(format_args) + ",") if format_args else ""
    return f"""
query (
  $search: String, $genres: [String], $notGenres: [String], $tags: [String], $notTags: [String],{extra_vars}
  $page: Int
) {{
  Page(perPage: 50, page: $page) {{
    pageInfo {{ hasNextPage }}
    media(
      search: $search, genre_in: $genres, genre_not_in: $notGenres,
      tag_in: $tags, tag_not_in: $notTags,{extra_args}
      type: ANIME, sort: POPULARITY_DESC
    ) {{
      {_MEDIA_FIELDS}
    }}
  }}
}}
"""

_GENRE_COLLECTION_QUERY = """
query {
  GenreCollection
}
"""

_TAG_COLLECTION_QUERY = """
query {
  MediaTagCollection {
    name
    isAdult
  }
}
"""

# The two "what should I watch next" signals, fetched together because they
# come from the same media objects and a second round trip per batch would
# double the cost for nothing:
#
#   * SEQUEL relations -- "you finished season 1, season 2 exists". Precise,
#     but only ever suggests more of what's already been watched.
#   * recommendations -- AniList's community "if you liked this, try that",
#     ordered by how many people agreed. This is what makes the feature
#     suggest something genuinely new.
#
# The caller cross-references both against the user's full list locally to
# drop anything already added in any status.
_RECOMMENDATION_SOURCES_QUERY = f"""
query ($ids: [Int]) {{
  Page(perPage: 50) {{
    media(id_in: $ids, type: ANIME) {{
      id
      title {{ romaji english }}
      relations {{
        edges {{
          relationType
          node {{
            {_MEDIA_FIELDS}
          }}
        }}
      }}
      recommendations(perPage: 8, sort: RATING_DESC) {{
        nodes {{
          rating
          mediaRecommendation {{
            {_MEDIA_FIELDS}
          }}
        }}
      }}
    }}
  }}
}}
"""

# A page of the catalog by popularity, used to pick something at random. Only
# ids/titles are needed to choose, but the full fields come back so the chosen
# one needs no follow-up request.
_POPULAR_PAGE_QUERY = f"""
query ($page: Int, $formats: [MediaFormat]) {{
  Page(perPage: 50, page: $page) {{
    pageInfo {{ lastPage }}
    media(type: ANIME, format_in: $formats, sort: POPULARITY_DESC, isAdult: false) {{
      {_MEDIA_FIELDS}
    }}
  }}
}}
"""

_SAVE_MEDIA_LIST_ENTRY_MUTATION = """
mutation ($mediaId: Int, $status: MediaListStatus, $progress: Int) {
  SaveMediaListEntry(mediaId: $mediaId, status: $status, progress: $progress) {
    id
  }
}
"""


class AniListError(Exception):
    """A GraphQL request succeeded at the HTTP level but returned errors."""


@dataclass(frozen=True, slots=True)
class Viewer:
    id: int
    name: str


@dataclass(frozen=True, slots=True)
class ListEntry:
    media_id: int
    status: str  # CURRENT, PLANNING, COMPLETED, DROPPED, PAUSED, REPEATING
    progress: int
    score: float
    title: str  # primary display title (english, falling back to romaji)
    cover_url: str | None
    titles: tuple[str, ...]  # romaji, english, synonyms -- used for title matching
    genres: tuple[str, ...]
    popularity: int


@dataclass(frozen=True, slots=True)
class MediaSummary:
    id: int
    id_mal: int | None  # MyAnimeList id -- used for the Jikan filler-episode fallback
    title: str  # primary display title (english, falling back to romaji)
    titles: tuple[str, ...]  # romaji, english, synonyms -- used for title matching
    cover_url: str | None
    # Wide key art, for the detail page's header. Often null -- AniList only
    # has one for the better-known entries, so anything using it needs a
    # fallback to the cover.
    banner_url: str | None
    average_score: int | None  # 0-100, AniList's own scale
    popularity: int
    genres: tuple[str, ...]
    format: str | None  # e.g. "TV", "MOVIE", "OVA"
    episodes: int | None
    description: str | None  # plain-ish text; still needs HTML tags stripped for display


def build_authorize_url(client_id: str) -> str:
    return AUTHORIZE_URL_TEMPLATE.format(client_id=client_id)


def _titles_of(media: dict) -> tuple[str, ...]:
    title = media.get("title", {})
    candidates = [title.get("romaji"), title.get("english"), *media.get("synonyms", [])]
    return tuple(t for t in candidates if t)


def _primary_title(media: dict) -> str:
    title = media.get("title", {})
    return title.get("english") or title.get("romaji") or "Unknown"


def _media_summary_of(media: dict) -> MediaSummary:
    return MediaSummary(
        id=media["id"],
        id_mal=media.get("idMal"),
        title=_primary_title(media),
        titles=_titles_of(media),
        cover_url=(media.get("coverImage") or {}).get("large"),
        banner_url=media.get("bannerImage"),
        average_score=media.get("averageScore"),
        popularity=media.get("popularity") or 0,
        genres=tuple(media.get("genres") or []),
        format=media.get("format"),
        episodes=media.get("episodes"),
        description=media.get("description"),
    )


class AniListClient:
    def __init__(self, client: httpx.Client, token: str | None = None) -> None:
        """token is only required for viewer-specific calls (get_viewer,
        get_list_collection, save_progress). Search/genre/tag queries are
        public AniList data and work fine without one -- callers who aren't
        logged in still get genre/tag search."""
        self._token = token
        self._client = client

    def _request(self, query: str, variables: dict | None = None) -> dict:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        resp = self._client.post(API_URL, json={"query": query, "variables": variables or {}}, headers=headers)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("errors"):
            messages = "; ".join(e.get("message", "unknown error") for e in payload["errors"])
            raise AniListError(messages)
        return payload["data"]

    def get_viewer(self) -> Viewer:
        data = self._request(_VIEWER_QUERY)
        viewer = data["Viewer"]
        return Viewer(id=viewer["id"], name=viewer["name"])

    def get_list_collection(self, user_id: int) -> list[ListEntry]:
        data = self._request(_MEDIA_LIST_COLLECTION_QUERY, {"userId": user_id})
        entries: list[ListEntry] = []
        for lst in data["MediaListCollection"]["lists"]:
            for entry in lst["entries"]:
                media = entry["media"]
                entries.append(
                    ListEntry(
                        media_id=media["id"],
                        status=entry["status"],
                        progress=entry["progress"],
                        score=entry["score"],
                        title=_primary_title(media),
                        cover_url=(media.get("coverImage") or {}).get("large"),
                        titles=_titles_of(media),
                        genres=tuple(media.get("genres") or []),
                        popularity=media.get("popularity") or 0,
                    )
                )
        return entries

    def search_media(self, query: str) -> list[MediaSummary]:
        data = self._request(_MEDIA_SEARCH_QUERY, {"search": query})
        return [_media_summary_of(m) for m in data["Page"]["media"]]

    def get_media_by_id(self, media_id: int) -> MediaSummary:
        data = self._request(_MEDIA_BY_ID_QUERY, {"id": media_id})
        return _media_summary_of(data["Media"])

    def get_genre_collection(self) -> list[str]:
        data = self._request(_GENRE_COLLECTION_QUERY)
        return list(data["GenreCollection"])

    def get_tag_collection(self) -> list[str]:
        data = self._request(_TAG_COLLECTION_QUERY)
        return [t["name"] for t in data["MediaTagCollection"] if not t.get("isAdult")]

    def search_by_filters(
        self,
        search: str,
        genres: list[str],
        tags: list[str],
        *,
        exclude_genres: list[str] | None = None,
        exclude_tags: list[str] | None = None,
        formats: list[str] | None = None,
        exclude_formats: list[str] | None = None,
        page: int = 1,
    ) -> tuple[list[MediaSummary], bool]:
        """Browses AniList's own catalog by genre/tag/format (optionally
        combined with a title search too), sorted by popularity. This is what
        genre/tag filtering in the app's search uses instead of the source --
        the source's catalog and genre list are both far smaller. Returns
        (results, has_next_page) -- results used to be silently capped at one
        page of 50 with no way to see more. formats/exclude_formats use
        AniList's own MediaFormat enum values: TV, TV_SHORT, MOVIE, SPECIAL,
        OVA, ONA, MUSIC."""
        variables = {
            "search": search or None,
            "genres": genres or None,
            "notGenres": exclude_genres or None,
            "tags": tags or None,
            "notTags": exclude_tags or None,
            "page": page,
        }
        # See _build_filter_search_query's docstring comment: formats/
        # notFormats must be left out of the query (and variables) entirely
        # when unset, not passed as null, or AniList's server 500s.
        if formats:
            variables["formats"] = formats
        if exclude_formats:
            variables["notFormats"] = exclude_formats
        query = _build_filter_search_query(bool(formats), bool(exclude_formats))
        data = self._request(query, variables)
        page_data = data["Page"]
        results = [_media_summary_of(m) for m in page_data["media"]]
        has_next = bool((page_data.get("pageInfo") or {}).get("hasNextPage"))
        return results, has_next

    def get_recommendation_sources(
        self, media_ids: list[int]
    ) -> list[tuple[str, MediaSummary, str, int]]:
        """For each given anime, what to watch after it.

        Returns (kind, suggestion, because_of_title, weight) rows, where kind
        is "sequel" or "similar". AniList pages this 50 ids at a time, so a
        longer list is fetched in batches -- the caller decides how many of the
        user's shows are worth spending requests on.
        """
        rows: list[tuple[str, MediaSummary, str, int]] = []
        for start in range(0, len(media_ids), 50):
            data = self._request(
                _RECOMMENDATION_SOURCES_QUERY, {"ids": media_ids[start : start + 50]}
            )
            for media in data["Page"]["media"]:
                because = _primary_title(media)
                for edge in (media.get("relations") or {}).get("edges", []):
                    if edge.get("relationType") == "SEQUEL":
                        rows.append(("sequel", _media_summary_of(edge["node"]), because, 0))
                for node in (media.get("recommendations") or {}).get("nodes", []):
                    suggestion = node.get("mediaRecommendation")
                    if suggestion:
                        rows.append(
                            ("similar", _media_summary_of(suggestion), because, node.get("rating") or 0)
                        )
        return rows

    def get_popular_page(self, page: int, formats: list[str]) -> tuple[list[MediaSummary], int]:
        """One page of the catalog by popularity, plus how many pages there
        are. Used to pick a random anime from a pool worth picking from --
        uniformly random across all of AniList is almost always an obscure
        short nobody asked for."""
        data = self._request(_POPULAR_PAGE_QUERY, {"page": page, "formats": formats})
        page_data = data["Page"]
        last_page = (page_data.get("pageInfo") or {}).get("lastPage") or page
        return [_media_summary_of(m) for m in page_data["media"]], last_page

    def get_media_extras(self, media_id: int) -> "MediaExtras":
        """Everything the detail page shows beside the episode list: related
        entries, what the community recommends next, and reviews."""
        media = self._request(_MEDIA_EXTRAS_QUERY, {"id": media_id})["Media"]

        relations = []
        for edge in (media.get("relations") or {}).get("edges", []):
            node = edge.get("node") or {}
            if not node.get("id"):
                continue
            relations.append(
                Relation(
                    relation_type=edge.get("relationType") or "",
                    media=_media_summary_of(node),
                    year=(node.get("startDate") or {}).get("year"),
                    status=node.get("status"),
                )
            )

        recommendations = [
            _media_summary_of(node["mediaRecommendation"])
            for node in (media.get("recommendations") or {}).get("nodes", [])
            if node.get("mediaRecommendation")
        ]

        reviews = [
            Review(
                id=node["id"],
                summary=(node.get("summary") or "").strip(),
                score=node.get("score"),
                rating=node.get("rating") or 0,
                rating_amount=node.get("ratingAmount") or 0,
                user=((node.get("user") or {}).get("name")) or "Anonymous",
            )
            for node in (media.get("reviews") or {}).get("nodes", [])
            if (node.get("summary") or "").strip()
        ]

        return MediaExtras(
            relations=tuple(relations),
            recommendations=tuple(recommendations),
            reviews=tuple(reviews),
        )

    # Six rounds is plenty: each one steps one sequel/prequel further from
    # where we started, and the longest real chains (Monogatari, JoJo) are
    # well inside eight entries either side. A bound matters because this
    # walks a graph the server describes one node at a time.
    _CHAIN_ROUNDS = 6

    def get_watch_order(self, media_id: int) -> list["ChainEntry"]:
        """The franchise's entries in story order, starting from any one of
        them.

        Built by walking only PREQUEL/SEQUEL edges outwards until the chain
        closes, then following it from the end that has no prequel. Side
        stories, spin-offs and recaps are deliberately not in here -- they are
        related viewing, not a watch order, and including them is how an OVA
        ends up announced as "season 2".
        """
        nodes: dict[int, dict] = {}
        # id -> the id that comes after it. Recorded from both directions,
        # since a pair is described from each side and either may be the one
        # we happen to fetch.
        next_of: dict[int, int] = {}
        frontier = {media_id}

        for _round in range(self._CHAIN_ROUNDS):
            pending = [i for i in frontier if i not in nodes]
            if not pending:
                break
            frontier = set()
            for start in range(0, len(pending), 50):
                data = self._request(_CHAIN_QUERY, {"ids": pending[start : start + 50]})
                for media in data["Page"]["media"]:
                    nodes[media["id"]] = media
                    for edge in (media.get("relations") or {}).get("edges", []):
                        neighbour = (edge.get("node") or {}).get("id")
                        kind = edge.get("relationType")
                        if not neighbour or kind not in _STORY_RELATIONS:
                            continue
                        frontier.add(neighbour)
                        if kind == "SEQUEL":
                            next_of[media["id"]] = neighbour
                        else:
                            next_of[neighbour] = media["id"]

        if media_id not in nodes:
            return []

        # Only entries actually reachable along the chain: a batch fetch also
        # brings back neighbours-of-neighbours that were never linked in.
        has_previous = set(next_of.values())
        start_id = media_id
        seen: set[int] = set()
        while start_id in has_previous and start_id not in seen:
            seen.add(start_id)
            start_id = next(prev for prev, nxt in next_of.items() if nxt == start_id)

        order: list[ChainEntry] = []
        current: int | None = start_id
        visited: set[int] = set()
        while current is not None and current not in visited:
            visited.add(current)
            media = nodes.get(current)
            if media is not None:
                order.append(
                    ChainEntry(
                        id=media["id"],
                        title=_primary_title(media),
                        format=media.get("format"),
                        episodes=media.get("episodes"),
                        year=(media.get("startDate") or {}).get("year"),
                        status=media.get("status"),
                        cover_url=(media.get("coverImage") or {}).get("large"),
                    )
                )
            current = next_of.get(current)
        return order

    def save_progress(self, media_id: int, status: str, progress: int) -> None:
        self._request(
            _SAVE_MEDIA_LIST_ENTRY_MUTATION,
            {"mediaId": media_id, "status": status, "progress": progress},
        )


# -- Detail-page extras ----------------------------------------------------
#
# Relations, community recommendations and reviews, for the "what else is
# there" half of the detail page. One query rather than three: they are all
# fields of the same Media, and AniList rate-limits by request.

_RELATION_FIELDS = """
      id
      idMal
      title { romaji english }
      synonyms
      coverImage { large }
      bannerImage
      averageScore
      popularity
      genres
      format
      episodes
      description(asHtml: false)
      startDate { year }
      status
"""

_MEDIA_EXTRAS_QUERY = """
query ($id: Int!) {
  Media(id: $id, type: ANIME) {
    relations {
      edges {
        relationType(version: 2)
        node { %s }
      }
    }
    recommendations(perPage: 12, sort: RATING_DESC) {
      nodes {
        rating
        mediaRecommendation { %s }
      }
    }
    reviews(perPage: 6, sort: RATING_DESC) {
      nodes {
        id
        summary
        score
        rating
        ratingAmount
        user { name }
      }
    }
  }
}
""" % (_RELATION_FIELDS, _RELATION_FIELDS)

# Only the edges that mean "more of this story". SIDE_STORY, SPIN_OFF and the
# rest are related viewing, not the same watch order, and putting them in the
# chain is how a recap or an OVA ends up presented as "season 2".
_STORY_RELATIONS = ("PREQUEL", "SEQUEL")

_CHAIN_QUERY = """
query ($ids: [Int]) {
  Page(perPage: 50) {
    media(id_in: $ids, type: ANIME) {
      id
      title { romaji english }
      format
      episodes
      startDate { year }
      status
      coverImage { large }
      relations {
        edges {
          relationType(version: 2)
          node { id }
        }
      }
    }
  }
}
"""


@dataclass(frozen=True, slots=True)
class Relation:
    relation_type: str  # "SEQUEL", "PREQUEL", "SIDE_STORY", "SPIN_OFF", ...
    media: MediaSummary
    year: int | None
    status: str | None  # "FINISHED", "RELEASING", "NOT_YET_RELEASED", ...


@dataclass(frozen=True, slots=True)
class Review:
    id: int
    summary: str  # the author's own one-line, spoiler-free teaser
    score: int | None  # the reviewer's score out of 100
    rating: int  # how many readers found it helpful
    rating_amount: int
    user: str


@dataclass(frozen=True, slots=True)
class MediaExtras:
    relations: tuple[Relation, ...]
    recommendations: tuple[MediaSummary, ...]
    reviews: tuple[Review, ...]


@dataclass(frozen=True, slots=True)
class ChainEntry:
    """One entry in a franchise's watch order."""

    id: int
    title: str
    format: str | None
    episodes: int | None
    year: int | None
    status: str | None
    cover_url: str | None
