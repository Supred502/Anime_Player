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
