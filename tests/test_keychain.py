import json
import subprocess
from unittest.mock import patch, MagicMock

from claude_switcher.keychain import read_credentials, write_credentials, delete_credentials

FAKE_CREDS = json.dumps({"accessToken": "sk-ant-oat01-xxx", "refreshToken": "sk-ant-ort01-xxx"})


class TestReadCredentials:
    @patch("claude_switcher.keychain.subprocess.run")
    def test_read_existing_entry(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout=FAKE_CREDS)
        result = read_credentials("claude-switcher:emile@gmail.com")
        assert result == FAKE_CREDS
        mock_run.assert_called_once_with(
            ["security", "find-generic-password", "-s", "claude-switcher:emile@gmail.com", "-w"],
            capture_output=True,
            text=True,
        )

    @patch("claude_switcher.keychain.subprocess.run")
    def test_read_missing_entry_returns_none(self, mock_run):
        mock_run.return_value = MagicMock(returncode=44, stdout="", stderr="not found")
        result = read_credentials("claude-switcher:missing@test.com")
        assert result is None


class TestWriteCredentials:
    @patch("claude_switcher.keychain.subprocess.run")
    def test_write_credentials_deletes_then_adds(self, mock_run):
        # First call: delete returns 0 (entry found), second delete: returncode!=0 (no more),
        # third call: add-generic-password returns 0
        mock_run.side_effect = [
            MagicMock(returncode=0),   # delete succeeds (one existing entry)
            MagicMock(returncode=44),  # delete fails (no more entries)
            MagicMock(returncode=0),   # add succeeds
        ]
        write_credentials("claude-switcher:emile@gmail.com", "emilejouannet", FAKE_CREDS)
        assert mock_run.call_count == 3
        # Verify delete calls
        mock_run.assert_any_call(
            ["security", "delete-generic-password", "-s", "claude-switcher:emile@gmail.com"],
            capture_output=True, text=True,
        )
        # Verify add call (password passed via stdin, not as argument)
        mock_run.assert_any_call(
            [
                "security", "add-generic-password",
                "-s", "claude-switcher:emile@gmail.com",
                "-a", "emilejouannet",
                "-w",
            ],
            input=FAKE_CREDS,
            capture_output=True,
            text=True,
        )

    @patch("claude_switcher.keychain.subprocess.run")
    def test_write_no_existing_entry(self, mock_run):
        # No existing entry to delete, then add succeeds
        mock_run.side_effect = [
            MagicMock(returncode=44),  # delete fails immediately (no entry)
            MagicMock(returncode=0),   # add succeeds
        ]
        write_credentials("claude-switcher:new@test.com", "newuser", FAKE_CREDS)
        assert mock_run.call_count == 2

    @patch("claude_switcher.keychain.subprocess.run")
    def test_write_failure_raises(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=44),  # delete fails (no entry)
            MagicMock(returncode=1, stderr="permission denied"),  # add fails
        ]
        try:
            write_credentials("claude-switcher:test@test.com", "testuser", FAKE_CREDS)
            assert False, "Should have raised"
        except RuntimeError as e:
            assert "Keychain write failed" in str(e)


class TestDeleteCredentials:
    @patch("claude_switcher.keychain.subprocess.run")
    def test_delete_existing(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        result = delete_credentials("claude-switcher:emile@gmail.com")
        assert result is True

    @patch("claude_switcher.keychain.subprocess.run")
    def test_delete_missing_returns_false(self, mock_run):
        mock_run.return_value = MagicMock(returncode=44)
        result = delete_credentials("claude-switcher:missing@test.com")
        assert result is False


class TestReadAccountAttribute:
    @patch("claude_switcher.keychain.subprocess.run")
    def test_read_account_attribute(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='    "acct"<blob>="emilejouannet"\n',
            stderr='',
        )
        from claude_switcher.keychain import read_account_attribute
        result = read_account_attribute("Claude Code-credentials")
        assert result == "emilejouannet"
