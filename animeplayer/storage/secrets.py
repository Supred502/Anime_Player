"""Logins the app keeps: the AniList token, the Jimaku API key, and a
friend's AniList token during Watch Together.

In the system's password store (KWallet, GNOME Keyring, Windows Credential
Manager) when there is one. When there isn't -- Steam Deck's Gaming Mode
runs no password store, and neither does a bare window manager -- in a file
only this user can read, beside the app's database. Either way the rest of
the app just calls save/load/clear.

In the Flatpak, always in the file as well. On the Steam Deck the same app
runs in Desktop Mode, which has a password store, and in Gaming Mode, which
doesn't: a login kept only in the store was gone in Gaming Mode, and the
Deck asked for it again on every start. A store can also take a login
without complaint and not give it back, so a save is read back to check.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import keyring
import keyring.errors

from animeplayer.storage.db import DEFAULT_DB_PATH

# Using a distinct keyring entry under ANIMEPLAYER_DB_PATH (dev/test runs only,
# see storage/db.py) means a test run simply finds no saved token -- it can't
# see or touch the user's real AniList login, and so can't push writes to
# their real account either.
_TEST = bool(os.environ.get("ANIMEPLAYER_DB_PATH"))
_SERVICE_NAME = "animeplayer-anilist-test" if _TEST else "animeplayer-anilist"
_JIMAKU_SERVICE = "animeplayer-jimaku-test" if _TEST else "animeplayer-jimaku"
_GUEST_SERVICE = "animeplayer-anilist-guest-test" if _TEST else "animeplayer-anilist-guest"
_TOKEN_KEY = "access_token"

_FALLBACK = DEFAULT_DB_PATH.parent / "logins.json"


def _read_fallback() -> dict[str, str]:
    try:
        return json.loads(_FALLBACK.read_text())
    except (OSError, ValueError):
        return {}


def _write_fallback(data: dict[str, str]) -> None:
    _FALLBACK.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(_FALLBACK, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.chmod(_FALLBACK, 0o600)


# The field each login has always been stored under -- the Jimaku key was
# "api_key" -- so logins saved by earlier versions are still found.
_FIELDS = {_JIMAKU_SERVICE: "api_key"}


def _field(service: str) -> str:
    return _FIELDS.get(service, _TOKEN_KEY)


def _always_file() -> bool:
    return bool(os.environ.get("FLATPAK_ID"))


def _set(service: str, value: str) -> None:
    kept = False
    try:
        keyring.set_password(service, _field(service), value)
        kept = keyring.get_password(service, _field(service)) == value
    except Exception:  # noqa: BLE001 -- no store, a locked one, D-Bus trouble: all mean "use the file"
        pass
    if kept and not _always_file():
        return
    data = _read_fallback()
    data[service] = value
    _write_fallback(data)


def _get(service: str) -> str:
    # The file first in the Flatpak: it's always there, and asking a store
    # that isn't running (Gaming Mode) only costs a D-Bus timeout.
    if _always_file():
        value = _read_fallback().get(service, "")
        if value:
            return value
    try:
        value = keyring.get_password(service, _field(service))
        if value:
            if _always_file():
                # Saved by a version that only used the store: copied, so
                # Gaming Mode finds it from now on.
                data = _read_fallback()
                data[service] = value
                _write_fallback(data)
            return value
    except Exception:  # noqa: BLE001 -- see _set
        pass
    return _read_fallback().get(service, "")


def _delete(service: str) -> None:
    try:
        keyring.delete_password(service, _field(service))
    except Exception:  # noqa: BLE001 -- not there, or no store
        pass
    data = _read_fallback()
    if data.pop(service, None) is not None:
        _write_fallback(data)


def save_token(token: str) -> None:
    _set(_SERVICE_NAME, token)


def load_token() -> str | None:
    return _get(_SERVICE_NAME) or None


def clear_token() -> None:
    _delete(_SERVICE_NAME)


# The Jimaku API key (Japanese subtitles, see learn/jimaku.py).
def save_jimaku_key(key: str) -> None:
    if key.strip():
        _set(_JIMAKU_SERVICE, key.strip())
    else:
        clear_jimaku_key()


def load_jimaku_key() -> str:
    return _get(_JIMAKU_SERVICE)


def clear_jimaku_key() -> None:
    _delete(_JIMAKU_SERVICE)


# A friend's AniList login during Watch Together: held only for one show,
# deleted when it ends.
def save_guest_token(token: str) -> None:
    _set(_GUEST_SERVICE, token)


def load_guest_token() -> str:
    return _get(_GUEST_SERVICE)


def clear_guest_token() -> None:
    _delete(_GUEST_SERVICE)
