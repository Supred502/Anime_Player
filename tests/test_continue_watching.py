"""Continue Watching leaves out a show once it's finished.

Deliberately no Backend() here: it opens the real database and login.
"""

from animeplayer.storage.db import AniListStatus
from animeplayer.ui.backend import _finished


def test_finished_show_leaves_continue_watching() -> None:
    assert _finished(AniListStatus(1, "COMPLETED", 12, 8.5, "Hanako-kun 2", None), 12)
    # An earlier episode of a completed show is a rewatch.
    assert not _finished(AniListStatus(2, "COMPLETED", 28, 9, "Frieren", None), 3)
    assert not _finished(AniListStatus(3, "CURRENT", 5, 0, "Still Going", None), 5)
