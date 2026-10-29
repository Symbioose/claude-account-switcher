import json
from unittest.mock import patch

import pytest

from claude_switcher import desktop
from claude_switcher.config import AccountInfo


def _account(email, uuid):
    return AccountInfo(email, "pro", "", False, "u", oauth_account={"accountUuid": uuid})


def _desktop_dir(tmp_path, uuid, cookies=b"cookies-a"):
    data_dir = tmp_path / "Claude"
    data_dir.mkdir()
    (data_dir / "Cookies").write_bytes(cookies)
    (data_dir / "config.json").write_text(json.dumps({
        "locale": "fr-FR",
        "oauth:tokenCache": f"tok-{uuid}",
        "oauth:tokenCacheV2": f"tok2-{uuid}",
        "lastKnownAccountUuid": uuid,
    }))
    return data_dir


@pytest.fixture(autouse=True)
def fake_keychain(monkeypatch):
    store = {}
    monkeypatch.setattr(desktop.keychain, "read_credentials", store.get)
    monkeypatch.setattr(desktop.keychain, "write_credentials", lambda s, a, p: store.__setitem__(s, p))
    monkeypatch.setattr(desktop.keychain, "delete_credentials", lambda s: store.pop(s, None) is not None)
    return store


def _config(data_dir):
    return json.loads((data_dir / "config.json").read_text())


@patch("claude_switcher.desktop._app_exists", return_value=True)
@patch("claude_switcher.desktop.launch_app")
@patch("claude_switcher.desktop.quit_app")
@patch("claude_switcher.desktop.is_running", return_value=True)
class TestSwitchDesktop:
    def test_first_switch_saves_current_and_signs_out(self, _running, mock_quit, mock_launch, _app, tmp_path):
        data_dir = _desktop_dir(tmp_path, "uuid-a")
        a, b = _account("a@test.com", "uuid-a"), _account("b@test.com", "uuid-b")

        result = desktop.switch_desktop(b, [a, b], data_dir)

        assert result == "signed_out"
        assert not (data_dir / "Cookies").exists()
        assert "oauth:tokenCache" not in _config(data_dir)
        assert _config(data_dir)["locale"] == "fr-FR"
        assert desktop.has_login("a@test.com")
        mock_quit.assert_called_once()
        mock_launch.assert_called_once()

    def test_switch_back_restores_saved_login(self, _running, _quit, _launch, _app, tmp_path):
        data_dir = _desktop_dir(tmp_path, "uuid-a")
        a, b = _account("a@test.com", "uuid-a"), _account("b@test.com", "uuid-b")
        desktop.switch_desktop(b, [a, b], data_dir)

        # Simulate signing in to b inside Desktop.
        (data_dir / "Cookies").write_bytes(b"cookies-b")
        cfg = _config(data_dir)
        cfg.update({"oauth:tokenCache": "tok-uuid-b", "lastKnownAccountUuid": "uuid-b"})
        (data_dir / "config.json").write_text(json.dumps(cfg))

        assert desktop.switch_desktop(a, [a, b], data_dir) == "switched"
        assert (data_dir / "Cookies").read_bytes() == b"cookies-a"
        assert _config(data_dir)["lastKnownAccountUuid"] == "uuid-a"

        assert desktop.switch_desktop(b, [a, b], data_dir) == "switched"
        assert (data_dir / "Cookies").read_bytes() == b"cookies-b"
        assert _config(data_dir)["oauth:tokenCache"] == "tok-uuid-b"

    def test_already_on_target_does_nothing(self, _running, mock_quit, _launch, _app, tmp_path):
        data_dir = _desktop_dir(tmp_path, "uuid-a")
        a = _account("a@test.com", "uuid-a")

        assert desktop.switch_desktop(a, [a], data_dir) == "skipped"
        mock_quit.assert_not_called()

    def test_unknown_desktop_account_is_left_alone(self, _running, mock_quit, _launch, _app, tmp_path):
        data_dir = _desktop_dir(tmp_path, "uuid-x")
        b = _account("b@test.com", "uuid-b")

        assert desktop.switch_desktop(b, [b], data_dir) == "unknown_account"
        assert (data_dir / "Cookies").read_bytes() == b"cookies-a"
        mock_quit.assert_not_called()

    def test_not_running_is_not_launched(self, mock_running, _quit, mock_launch, _app, tmp_path):
        mock_running.return_value = False
        data_dir = _desktop_dir(tmp_path, "uuid-a")
        a, b = _account("a@test.com", "uuid-a"), _account("b@test.com", "uuid-b")

        desktop.switch_desktop(b, [a, b], data_dir)
        mock_launch.assert_not_called()


def test_not_installed_is_skipped(tmp_path):
    b = _account("b@test.com", "uuid-b")
    assert desktop.switch_desktop(b, [b], tmp_path / "missing") == "skipped"


@patch("claude_switcher.desktop._app_exists", return_value=False)
def test_app_removed_is_skipped(_app, tmp_path):
    data_dir = _desktop_dir(tmp_path, "uuid-a")
    b = _account("b@test.com", "uuid-b")
    assert desktop.switch_desktop(b, [b], data_dir) == "skipped"
    assert (data_dir / "Cookies").exists()


def test_remove_login_deletes_backup(fake_keychain):
    fake_keychain["claude-switcher-desktop:a@test.com"] = "{}"
    desktop.remove_login("a@test.com")
    assert not desktop.has_login("a@test.com")


@patch("claude_switcher.desktop._app_exists", return_value=True)
def test_needs_switch_compares_desktop_account(_app, tmp_path):
    data_dir = _desktop_dir(tmp_path, "uuid-a")
    assert not desktop.needs_switch(_account("a@test.com", "uuid-a"), data_dir)
    assert desktop.needs_switch(_account("b@test.com", "uuid-b"), data_dir)
