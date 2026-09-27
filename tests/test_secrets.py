import keyring
import keyring.errors

from animeplayer.storage import secrets


def test_without_a_password_store_logins_go_to_a_private_file(tmp_path, monkeypatch):
    def broken(*_args, **_kwargs):
        raise keyring.errors.NoKeyringError("no backend")
    for name in ("set_password", "get_password", "delete_password"):
        monkeypatch.setattr(keyring, name, broken)
    monkeypatch.setattr(secrets, "_FALLBACK", tmp_path / "logins.json")

    secrets.save_token("abc")
    assert secrets.load_token() == "abc"
    assert (tmp_path / "logins.json").stat().st_mode & 0o777 == 0o600
    secrets.save_jimaku_key("key1")
    secrets.clear_token()
    assert secrets.load_token() is None
    assert secrets.load_jimaku_key() == "key1"


class _Store:
    """A password store; `forgetful` takes logins and doesn't give them back."""
    def __init__(self, forgetful=False):
        self.data, self.forgetful, self.up = {}, forgetful, True
    def set_password(self, service, field, value):
        if not self.up:
            raise keyring.errors.KeyringError("not running")
        if not self.forgetful:
            self.data[(service, field)] = value
    def get_password(self, service, field):
        if not self.up:
            raise keyring.errors.KeyringError("not running")
        return self.data.get((service, field))
    def delete_password(self, service, field):
        self.data.pop((service, field), None)


def _use(monkeypatch, tmp_path, store):
    for name in ("set_password", "get_password", "delete_password"):
        monkeypatch.setattr(keyring, name, getattr(store, name))
    monkeypatch.setattr(secrets, "_FALLBACK", tmp_path / "logins.json")


def test_a_store_that_forgets_does_not_lose_the_login(tmp_path, monkeypatch):
    monkeypatch.delenv("FLATPAK_ID", raising=False)
    _use(monkeypatch, tmp_path, _Store(forgetful=True))
    secrets.save_token("abc")
    assert secrets.load_token() == "abc"


def test_flatpak_login_from_desktop_mode_is_there_in_gaming_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("FLATPAK_ID", "io.github.supred.animeplayer")
    store = _Store()
    _use(monkeypatch, tmp_path, store)
    secrets.save_token("abc")          # Desktop Mode: the store is running
    store.up = False                    # Gaming Mode: it isn't
    assert secrets.load_token() == "abc"
    secrets.clear_token()
    assert secrets.load_token() is None


def test_outside_the_flatpak_a_working_store_keeps_it_out_of_the_file(tmp_path, monkeypatch):
    monkeypatch.delenv("FLATPAK_ID", raising=False)
    _use(monkeypatch, tmp_path, _Store())
    secrets.save_token("abc")
    assert secrets.load_token() == "abc"
    assert not (tmp_path / "logins.json").exists()


def test_flatpak_login_kept_only_in_the_store_is_copied_to_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv("FLATPAK_ID", "io.github.supred.animeplayer")
    store = _Store()
    _use(monkeypatch, tmp_path, store)
    store.data[(secrets._SERVICE_NAME, "access_token")] = "old"   # an earlier version's save
    assert secrets.load_token() == "old"
    store.up = False
    assert secrets.load_token() == "old"


def test_only_anilist_refusing_the_token_counts_as_logged_out():
    from animeplayer.ui.backend import _token_rejected
    assert _token_rejected("Invalid token")
    assert _token_rejected("Unauthorized.")
    assert not _token_rejected("[Errno -3] Temporary failure in name resolution")
    assert not _token_rejected("AniList is rate-limiting us right now -- give it a minute and try again.")
    assert not _token_rejected("Server error '500 Internal Server Error'")
