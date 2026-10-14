from pathlib import Path
from unittest.mock import patch

from claude_switcher import desktop


class TestProfileDir:
    def test_profile_dir_uses_email(self):
        assert desktop.profile_dir("a@b.com").name == "a_b.com"

    def test_profile_dir_sanitizes_path_separators(self):
        assert "/" not in desktop.profile_dir("../../evil@b.com").name


class TestIsRunning:
    @patch("claude_switcher.desktop.subprocess.run")
    def test_running_when_pgrep_succeeds(self, mock_run):
        mock_run.return_value.returncode = 0
        assert desktop.is_running() is True

    @patch("claude_switcher.desktop.subprocess.run")
    def test_not_running_when_pgrep_fails(self, mock_run):
        mock_run.return_value.returncode = 1
        assert desktop.is_running() is False


class TestSwitchDesktopProfile:
    @patch("claude_switcher.desktop.is_installed", return_value=False)
    def test_noop_when_not_installed(self, _installed):
        assert desktop.switch_desktop_profile("a@b.com") is False

    @patch("claude_switcher.desktop.is_running", return_value=False)
    @patch("claude_switcher.desktop.is_installed", return_value=True)
    def test_noop_when_not_running(self, _installed, _running):
        assert desktop.switch_desktop_profile("a@b.com") is False

    @patch("claude_switcher.desktop._launch")
    @patch("claude_switcher.desktop._quit_and_wait", return_value=True)
    @patch("claude_switcher.desktop.is_running", return_value=True)
    @patch("claude_switcher.desktop.is_installed", return_value=True)
    def test_relaunches_with_profile(self, _installed, _running, _quit, mock_launch, tmp_path):
        with patch.object(desktop, "PROFILES_ROOT", tmp_path):
            assert desktop.switch_desktop_profile("a@b.com") is True
        mock_launch.assert_called_once_with(tmp_path / "a_b.com")

    @patch("claude_switcher.desktop._launch")
    @patch("claude_switcher.desktop._quit_and_wait", return_value=True)
    @patch("claude_switcher.desktop.is_running", return_value=True)
    @patch("claude_switcher.desktop.is_installed", return_value=True)
    def test_creates_profile_dir(self, _installed, _running, _quit, _launch, tmp_path):
        with patch.object(desktop, "PROFILES_ROOT", tmp_path):
            desktop.switch_desktop_profile("a@b.com")
        assert (tmp_path / "a_b.com").is_dir()

    @patch("claude_switcher.desktop._launch")
    @patch("claude_switcher.desktop._quit_and_wait", return_value=False)
    @patch("claude_switcher.desktop.is_running", return_value=True)
    @patch("claude_switcher.desktop.is_installed", return_value=True)
    def test_does_not_launch_if_quit_times_out(self, _installed, _running, _quit, mock_launch):
        assert desktop.switch_desktop_profile("a@b.com") is False
        mock_launch.assert_not_called()


class TestQuitAndWait:
    @patch("claude_switcher.desktop.time.sleep")
    @patch("claude_switcher.desktop.is_running", side_effect=[True, True, False])
    @patch("claude_switcher.desktop.subprocess.run")
    def test_waits_for_exit(self, _run, _running, _sleep):
        assert desktop._quit_and_wait() is True

    @patch("claude_switcher.desktop.time.sleep")
    @patch("claude_switcher.desktop.is_running", return_value=True)
    @patch("claude_switcher.desktop.subprocess.run")
    def test_times_out_when_process_survives(self, _run, _running, _sleep):
        assert desktop._quit_and_wait(timeout=0.5) is False
