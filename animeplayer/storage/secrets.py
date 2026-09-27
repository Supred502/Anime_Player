"""Keyring wrapper for the AniList access token (KWallet-backed on KDE)."""

from __future__ import annotations

import os

import keyring
import keyring.errors

# Using a distinct keyring entry under ANIMEPLAYER_DB_PATH (dev/test runs only,
# see storage/db.py) means a test run simply finds no saved token -- it can't
# see or touch the user's real AniList login, and so can't push writes to
# their real account either.
_SERVICE_NAME = "animeplayer-anilist-test" if os.environ.get("ANIMEPLAYER_DB_PATH") else "animeplayer-anilist"
_TOKEN_KEY = "access_token"


def save_token(token: str) -> None:
    keyring.set_password(_SERVICE_NAME, _TOKEN_KEY, token)


def load_token() -> str | None:
    return keyring.get_password(_SERVICE_NAME, _TOKEN_KEY)


def clear_token() -> None:
    try:
        keyring.delete_password(_SERVICE_NAME, _TOKEN_KEY)
    except keyring.errors.PasswordDeleteError:
        pass


# The Jimaku API key (Japanese subtitles, see learn/jimaku.py). A credential,
# so it lives in the keyring beside the AniList token rather than in the
# settings table.
_JIMAKU_SERVICE = "animeplayer-jimaku-test" if os.environ.get("ANIMEPLAYER_DB_PATH") else "animeplayer-jimaku"


def save_jimaku_key(key: str) -> None:
    if key.strip():
        keyring.set_password(_JIMAKU_SERVICE, "api_key", key.strip())
    else:
        clear_jimaku_key()


def load_jimaku_key() -> str:
    try:
        return keyring.get_password(_JIMAKU_SERVICE, "api_key") or ""
    except keyring.errors.KeyringError:
        return ""


def clear_jimaku_key() -> None:
    try:
        keyring.delete_password(_JIMAKU_SERVICE, "api_key")
    except keyring.errors.PasswordDeleteError:
        pass


# A friend's AniList login during Watch Together (see Backend's watch
# together section): held only for one show, deleted when it ends.
_GUEST_SERVICE = "animeplayer-anilist-guest-test" if os.environ.get("ANIMEPLAYER_DB_PATH") else "animeplayer-anilist-guest"


def save_guest_token(token: str) -> None:
    keyring.set_password(_GUEST_SERVICE, _TOKEN_KEY, token)


def load_guest_token() -> str:
    try:
        return keyring.get_password(_GUEST_SERVICE, _TOKEN_KEY) or ""
    except keyring.errors.KeyringError:
        return ""


def clear_guest_token() -> None:
    try:
        keyring.delete_password(_GUEST_SERVICE, _TOKEN_KEY)
    except keyring.errors.PasswordDeleteError:
        pass
