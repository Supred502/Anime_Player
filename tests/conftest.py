import pytest

from animeplayer.anilist import client as client_module
from animeplayer.anilist.client import AniListClient


@pytest.fixture(autouse=True)
def _isolate_anilist_shared_state():
    """The AniList client keeps two pieces of process-wide state -- a response
    cache and a rate limiter -- both shared by every instance on purpose,
    because AniList counts one budget per user across the app's authenticated
    and anonymous clients alike.

    Both have to be reset between tests. The cache, because a test that mocks
    a response otherwise poisons the next test asking the same query (this is
    exactly how four watch-order tests started answering with each other's
    chains). The limiter, because a suite makes far more requests a minute
    than a person does, and it would otherwise start really sleeping partway
    through the file -- the run simply hangs.
    """
    AniListClient.clear_cache()
    client_module._limiter._times.clear()
    client_module._limiter._blocked_until = 0.0
    yield
    AniListClient.clear_cache()
