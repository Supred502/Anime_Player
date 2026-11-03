"""Trailers: AniList links them on YouTube, and the Deck's Game Mode has no
browser to send anyone to, so they play in the app. yt-dlp finds the stream
addresses; mpv plays them.

YouTube serves only 360p with the sound in the same file. Anything better is
a video stream and an audio stream, which mpv plays together (see
MpvVideoItem.loadUrlWithAudio).
"""

from __future__ import annotations

from typing import Any

# Up to 1080p, H.264 where there is one (decodes in hardware nearly
# everywhere, the Deck included), with AAC sound; else whatever plays.
FORMAT = ("bestvideo[height<=1080][vcodec^=avc1]+bestaudio[ext=m4a]"
          "/bestvideo[height<=1080]+bestaudio/best")


def streams_of(info: dict[str, Any]) -> tuple[str, str]:
    """(video URL, audio URL or "") from what yt-dlp worked out."""
    picked = info.get("requested_formats")
    if picked:
        video = next((f["url"] for f in picked if f.get("vcodec") not in (None, "none")), "")
        audio = next((f["url"] for f in picked if f.get("vcodec") in (None, "none")), "")
        if video:
            return video, audio if audio != video else ""
    return info.get("url") or "", ""


def resolve(youtube_id: str) -> tuple[str, str]:
    """Blocking; a few seconds. Raises if the video can't be had."""
    import yt_dlp  # only when a trailer is asked for: it's a large import

    options = {"quiet": True, "no_warnings": True, "skip_download": True, "format": FORMAT,
               "noplaylist": True}
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={youtube_id}", download=False)
    video, audio = streams_of(info or {})
    if not video:
        raise RuntimeError("no playable stream")
    return video, audio
