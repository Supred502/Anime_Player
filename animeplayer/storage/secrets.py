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
