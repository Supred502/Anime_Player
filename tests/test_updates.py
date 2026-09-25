import httpx
import pytest
import respx

from animeplayer import updates


def test_versions_compare_numerically():
    assert updates.is_newer("0.10.0", "0.9.9")
    assert updates.is_newer("v1.0", "0.9")
    assert updates.is_newer("1.0.1", "1.0")
    assert not updates.is_newer("1.0", "1.0.0")
    assert not updates.is_newer("0.2.0", "0.2.0")
    assert not updates.is_newer("garbage", "0.1.0")
    assert updates.parse_version("v2.3.4-beta") == (2, 3, 4)


@respx.mock
def test_latest_release_picks_the_installer():
    respx.get(updates.API_URL).mock(return_value=httpx.Response(200, json={
        "tag_name": "v0.3.0",
        "body": "- Faster\n- Better",
        "html_url": "https://github.com/x/y/releases/tag/v0.3.0",
        "assets": [
            {"name": "notes.txt", "browser_download_url": "https://a/notes", "size": 3},
            {"name": "AnimePlayer-0.3.0-Setup.exe", "browser_download_url": "https://a/setup", "size": 1234},
        ],
    }))
    with httpx.Client() as client:
        release = updates.latest_release(client)
    assert release.version == "0.3.0"
    assert release.notes == "- Faster\n- Better"
    assert release.installer_url == "https://a/setup"
    assert release.installer_size == 1234


@respx.mock
def test_no_release_yet():
    respx.get(updates.API_URL).mock(return_value=httpx.Response(404, json={}))
    with httpx.Client() as client:
        assert updates.latest_release(client) is None


@respx.mock
def test_rate_limit_is_a_readable_error():
    respx.get(updates.API_URL).mock(return_value=httpx.Response(403, json={}))
    with httpx.Client() as client, pytest.raises(updates.UpdateError):
        updates.latest_release(client)


@respx.mock
def test_download_checks_the_size(tmp_path):
    release = updates.Release("0.3.0", "", "", "https://a/setup", 10)
    respx.get("https://a/setup").mock(return_value=httpx.Response(200, content=b"x" * 10))
    seen = []
    with httpx.Client() as client:
        path = updates.download_installer(client, release, tmp_path, seen.append)
    assert path.read_bytes() == b"x" * 10
    assert seen[-1] == 1.0

    short = updates.Release("0.3.0", "", "", "https://a/setup", 99)
    with httpx.Client() as client, pytest.raises(updates.UpdateError):
        updates.download_installer(client, short, tmp_path, seen.append)
