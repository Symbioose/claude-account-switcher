"""Tests for config-file safety and CLI discovery."""

import os
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_switcher import cli_paths
from claude_switcher.config import (
    AccountInfo,
    add_account,
    load_accounts,
)
from claude_switcher.fsutil import atomic_write_text


class TestAtomicWrite:
    def test_replaces_content_with_requested_mode(self, tmp_path):
        path = tmp_path / "f.json"
        path.write_text("old")
        os.chmod(path, 0o644)

        atomic_write_text(path, "new", mode=0o600)

        assert path.read_text() == "new"
        assert (path.stat().st_mode & 0o777) == 0o600
        assert [p.name for p in tmp_path.iterdir()] == ["f.json"]

    def test_creates_new_file(self, tmp_path):
        path = tmp_path / "f.json"
        atomic_write_text(path, "x", mode=0o600)
        assert path.read_text() == "x"
        assert (path.stat().st_mode & 0o777) == 0o600

    def test_follows_symlink(self, tmp_path):
        target = tmp_path / "real.json"
        target.write_text("old")
        link = tmp_path / "link.json"
        link.symlink_to(target)

        atomic_write_text(link, "new", mode=0o600)

        assert link.is_symlink()
        assert target.read_text() == "new"

    @pytest.mark.parametrize("failing", ["tempfile.mkstemp", "os.fsync", "os.replace"])
    def test_any_failure_falls_back_to_plain_write(self, tmp_path, failing):
        path = tmp_path / "f.json"
        path.write_text("old")
        with patch(f"claude_switcher.fsutil.{failing}", side_effect=OSError("boom")):
            atomic_write_text(path, "new", mode=0o600)
        assert path.read_text() == "new"
        assert (path.stat().st_mode & 0o777) == 0o600
        assert [p.name for p in tmp_path.iterdir()] == ["f.json"]


class TestConfigSafety:
    def test_saves_leave_no_temp_files(self, tmp_path):
        path = tmp_path / "accounts.json"
        for email in ("a@x.com", "b@x.com", "c@x.com"):
            add_account(AccountInfo(email, "max", "", False, email), path)
        assert [p.name for p in tmp_path.iterdir()] == ["accounts.json"]
        assert [a.email for a in load_accounts(path)] == ["a@x.com", "b@x.com", "c@x.com"]

    def test_invalid_config_is_backed_up_before_overwrite(self, tmp_path):
        path = tmp_path / "accounts.json"
        path.write_text('{"accounts": [{"email": "a@x.com"')

        add_account(AccountInfo("d@x.com", "pro", "", True, "d"), path)

        backup = tmp_path / "accounts.json.corrupt"
        assert backup.read_text() == '{"accounts": [{"email": "a@x.com"'
        assert (backup.stat().st_mode & 0o777) == 0o600

    def test_existing_backup_is_not_replaced(self, tmp_path):
        path = tmp_path / "accounts.json"
        backup = tmp_path / "accounts.json.corrupt"
        backup.write_text("first")
        path.write_text("{broken")

        assert load_accounts(path) == []
        assert backup.read_text() == "first"

    def test_backup_failure_does_not_break_reads(self, tmp_path):
        path = tmp_path / "accounts.json"
        path.write_text("{broken")
        with patch("claude_switcher.config.shutil.copy2", side_effect=OSError("denied")):
            assert load_accounts(path) == []
        backup = tmp_path / "accounts.json.corrupt"
        real_exists = Path.exists

        def exists(self):
            if self == backup:
                raise PermissionError("denied")
            return real_exists(self)

        with patch.object(Path, "exists", exists):
            assert load_accounts(path) == []

    def test_concurrent_adds_lose_no_account(self, tmp_path):
        path = tmp_path / "accounts.json"
        emails = [f"user{i}@x.com" for i in range(40)]

        def add(email):
            add_account(AccountInfo(email, "pro", "", False, email), path)

        threads = [threading.Thread(target=add, args=(e,)) for e in emails]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sorted(a.email for a in load_accounts(path)) == sorted(emails)


class TestCliPaths:
    def _only_under(self, root):
        real_is_file = Path.is_file

        def is_file(self):
            return str(self).startswith(str(root)) and real_is_file(self)

        return patch.object(cli_paths.Path, "is_file", is_file)

    def test_historical_dirs_are_checked_before_new_ones(self, tmp_path):
        local_bin = tmp_path / ".local" / "bin"
        nvm_bin = tmp_path / ".nvm" / "versions" / "node" / "v22.0.0" / "bin"
        for directory in (local_bin, nvm_bin):
            directory.mkdir(parents=True)
            (directory / "claude").write_text("")
        with patch.object(cli_paths.Path, "home", return_value=tmp_path), self._only_under(tmp_path):
            assert cli_paths.find_cli("claude") == str(local_bin / "claude")

    def test_finds_cli_in_newest_nvm_version(self, tmp_path):
        for version in ("v18.2.0", "v22.11.0", "v9.0.0"):
            bin_dir = tmp_path / ".nvm" / "versions" / "node" / version / "bin"
            bin_dir.mkdir(parents=True)
            (bin_dir / "claude").write_text("")
        with patch.object(cli_paths.Path, "home", return_value=tmp_path), self._only_under(tmp_path):
            found = cli_paths.find_cli("claude")
        assert found == str(tmp_path / ".nvm" / "versions" / "node" / "v22.11.0" / "bin" / "claude")

    def test_returns_none_when_missing(self, tmp_path):
        with patch.object(cli_paths.Path, "home", return_value=tmp_path), self._only_under(tmp_path):
            assert cli_paths.find_cli("claude") is None

    def test_cli_env_appends_missing_binary_dir(self):
        with patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}):
            env = cli_paths.cli_env("/opt/node/bin/claude")
        assert env["PATH"] == "/usr/bin:/bin:/opt/node/bin"

    def test_cli_env_inherits_when_dir_already_on_path(self):
        with patch.dict(os.environ, {"PATH": "/usr/local/bin:/usr/bin"}):
            assert cli_paths.cli_env("/usr/local/bin/claude") is None

    def test_cli_env_inherits_for_bare_name(self):
        with patch.dict(os.environ, {"PATH": "/usr/bin"}):
            assert cli_paths.cli_env("claude") is None

    def test_cli_env_inherits_without_path(self):
        env_without_path = {k: v for k, v in os.environ.items() if k != "PATH"}
        with patch.dict(os.environ, env_without_path, clear=True):
            assert cli_paths.cli_env("/opt/node/bin/claude") is None
