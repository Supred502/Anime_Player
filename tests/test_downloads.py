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


def test_skip_times_round_trip_beside_the_file(tmp_path) -> None:
    media = tmp_path / "episode-1-sub.mp4"
    downloads.save_skip_times(media, {"op": {"start": 10.0, "end": 100.0}})
    assert downloads.load_skip_times(media) == {"op": {"start": 10.0, "end": 100.0}}
    # Nothing saved: an empty map, not an exception.
    assert downloads.load_skip_times(tmp_path / "other.mp4") == {}


def test_a_throttled_download_asks_ffmpeg_for_a_read_rate(tmp_path, monkeypatch) -> None:
    seen = {}

    class FakeProcess:
        returncode = 0
        stdout = iter(())
        stderr = None

        def wait(self):
            return 0

    def fake_popen(command, **_kwargs):
        seen["command"] = command
        (tmp_path / "ep.part.mp4").write_bytes(b"x")
        return FakeProcess()

    monkeypatch.setattr(downloads, "ffmpeg_available", lambda: True)
    monkeypatch.setattr(downloads.subprocess, "Popen", fake_popen)
    downloads.Downloader().fetch("http://x/m.m3u8", "", tmp_path / "ep.mp4", 0, lambda *_: None,
                                 readrate=3)
    command = seen["command"]
    # Must come before -i: it's an input option.
    assert command[command.index("-readrate") + 1] == "3"
    assert command.index("-readrate") < command.index("-i")


def test_a_subtitle_is_fetched_with_the_referer(tmp_path) -> None:
    """The host refuses some subtitle files without it."""
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("Referer") != "https://embed.example/":
            return httpx.Response(403)
        return httpx.Response(200, text="WEBVTT")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    saved = downloads.download_subtitle("https://cdn.example/s.vtt", tmp_path / "s.vtt", client,
                                        referer="https://embed.example/")
    assert saved is not None and saved.read_text() == "WEBVTT"


def test_new_downloads_follow_the_chosen_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(downloads, "DOWNLOAD_DIR", downloads.DEFAULT_DOWNLOAD_DIR)
    downloads.set_download_dir(tmp_path / "big-drive")
    assert target_path(_request()).is_relative_to(tmp_path / "big-drive")
    downloads.set_download_dir("")
    assert downloads.DOWNLOAD_DIR == downloads.DEFAULT_DOWNLOAD_DIR


def test_moving_a_saved_episode_takes_its_extras_and_tidies_up(tmp_path):
    old = tmp_path / "old" / "Frieren-frieren-1"
    old.mkdir(parents=True)
    video, subs, skip = old / "episode-1-sub.mp4", old / "episode-1-sub.vtt", old / "episode-1-sub.skip.json"
    for f in (video, subs, skip):
        f.write_text(f.name)
    new_video, new_subs, new_skip = downloads.move_episode([str(video), str(subs), str(skip)], tmp_path / "new")
    assert Path(new_video).read_text() == "episode-1-sub.mp4"
    assert Path(new_subs).parent == tmp_path / "new" / "Frieren-frieren-1"
    assert Path(new_skip).exists()
    assert not old.exists()  # the emptied show folder is gone


def test_disk_usage_counts_listed_files_wherever_they_are(tmp_path):
    a, b = tmp_path / "a.mp4", tmp_path / "x" / "b.mp4"
    b.parent.mkdir()
    a.write_bytes(b"1" * 10)
    b.write_bytes(b"1" * 5)
    assert downloads.disk_usage([str(a), str(b), str(tmp_path / "gone.mp4")]) == 15


def test_download_errors_read_as_plain_words():
    from animeplayer.ui.backend import _plain_download_error
    assert _plain_download_error("[Errno 111] Connection refused").startswith("couldn't reach")
    assert _plain_download_error("The read operation timed out") == "the streaming site took too long to answer"
    assert _plain_download_error("ffmpeg exited with 1") == "ffmpeg exited with 1"
