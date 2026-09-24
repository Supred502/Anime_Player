from pathlib import Path

from animeplayer.player import downloads
from animeplayer.player.downloads import DownloadRequest, delete_files, target_path
from animeplayer.storage.db import Database, DownloadEntry


def _request(**overrides) -> DownloadRequest:
    base = dict(
        episode_id=1, dub=False, slug_id="dorohedoro-2691", numeric_id="2691",
        anime_title="Dorohedoro", poster_url="", episode_number=1.0,
    )
    base.update(overrides)
    return DownloadRequest(**base)


def _entry(tmp_path: Path, **overrides) -> DownloadEntry:
    base = dict(
        episode_id=1, dub=False, slug_id="dorohedoro-2691", numeric_id="2691",
        anime_title="Dorohedoro", poster_url=None, episode_number=1.0,
        path=str(tmp_path / "ep1.mp4"), subtitle_path=None, status="ready",
        bytes=100, message="", created_at=1.0,
    )
    base.update(overrides)
    return DownloadEntry(**base)


def test_a_title_with_punctuation_still_makes_a_filename() -> None:
    """Source titles arrive with colons, slashes and full-width punctuation;
    none of it may reach the filesystem."""
    path = target_path(_request(anime_title="Re:ZERO -Starting Life-/ 2nd"))
    assert "/" not in path.parent.name
    assert ":" not in path.parent.name


def test_sub_and_dub_of_one_episode_are_different_files() -> None:
    """They share an episode id on the source, so a naming scheme that ignores
    the audio would have one silently overwrite the other."""
    assert target_path(_request(dub=False)) != target_path(_request(dub=True))


def test_a_fractional_episode_keeps_its_half() -> None:
    assert "episode-1-sub" in target_path(_request(episode_number=1.0)).name
    assert "episode-1.5-sub" in target_path(_request(episode_number=1.5)).name


def test_deleting_the_last_episode_takes_its_folder_with_it(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(downloads, "DOWNLOAD_DIR", tmp_path)
    folder = tmp_path / "Dorohedoro-dorohedoro-2691"
    folder.mkdir()
    first, second = folder / "episode-1-sub.mp4", folder / "episode-2-sub.mp4"
    first.write_bytes(b"x")
    second.write_bytes(b"x")

    delete_files(first)
    # Still one episode left, so the folder stays.
    assert folder.is_dir()

    delete_files(second)
    # Finishing a series shouldn't leave a tree of empty directories behind.
    assert not folder.exists()


def test_the_download_root_itself_is_never_removed(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(downloads, "DOWNLOAD_DIR", tmp_path)
    loose = tmp_path / "stray.mp4"
    loose.write_bytes(b"x")
    delete_files(loose)
    assert tmp_path.is_dir()


def test_a_download_round_trips(tmp_path) -> None:
    db = Database(tmp_path / "t.db")
    media = tmp_path / "ep1.mp4"
    media.write_bytes(b"x")

    db.upsert_download(_entry(tmp_path))
    found = db.get_download(1, dub=False)
    assert found is not None and found.status == "ready"
    # Keyed by audio as well as episode.
    assert db.get_download(1, dub=True) is None


def test_a_ready_row_whose_file_vanished_is_treated_as_gone(tmp_path) -> None:
    """The file can be deleted from underneath us -- by the user, or by a
    cleaned-out home directory. Trusting the row would hand mpv a path to
    nothing, and the episode would fail to start with no explanation."""
    db = Database(tmp_path / "t.db")
    db.upsert_download(_entry(tmp_path))  # the file was never created

    assert db.get_download(1, dub=False) is None
    # ...and the stale row is dropped rather than re-checked forever.
    assert db.all_downloads() == []


def test_a_queued_row_is_not_checked_against_the_disk(tmp_path) -> None:
    """Only 'ready' promises a file. A queued or in-flight download has none
    yet, and must survive being looked at."""
    db = Database(tmp_path / "t.db")
    db.upsert_download(_entry(tmp_path, status="queued"))
    found = db.get_download(1, dub=False)
    assert found is not None and found.status == "queued"


def test_downloaded_anime_groups_by_show_with_a_count(tmp_path) -> None:
    db = Database(tmp_path / "t.db")
    for number in (1, 2):
        media = tmp_path / f"ep{number}.mp4"
        media.write_bytes(b"x")
        db.upsert_download(_entry(tmp_path, episode_id=number, episode_number=float(number),
                                  path=str(media)))
    other = tmp_path / "other.mp4"
    other.write_bytes(b"x")
    db.upsert_download(_entry(tmp_path, episode_id=9, slug_id="frieren-1",
                              anime_title="Frieren", path=str(other)))

    grouped = db.downloaded_anime()
    assert {entry.anime_title: count for entry, count in grouped} == {
        "Dorohedoro": 2, "Frieren": 1
    }


def test_only_ready_episodes_count_as_downloaded(tmp_path) -> None:
    """A show whose only episode is still downloading has nothing to watch
    offline, so it must not appear in the Downloaded listing."""
    db = Database(tmp_path / "t.db")
    db.upsert_download(_entry(tmp_path, status="downloading"))
    assert db.downloaded_anime() == []
