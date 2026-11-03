from animeplayer.trailers import streams_of


def test_separate_video_and_audio() -> None:
    info = {"requested_formats": [{"url": "v", "vcodec": "avc1.640028"}, {"url": "a", "vcodec": "none"}]}
    assert streams_of(info) == ("v", "a")


def test_one_file_with_sound() -> None:
    assert streams_of({"url": "both", "vcodec": "avc1"}) == ("both", "")

