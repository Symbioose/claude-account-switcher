"""Tests for the usage module."""

import json
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

from claude_switcher.usage import _extract_token, _format_reset_delta, format_usage, fetch_usage_for_account


class TestExtractToken:
    def test_extracts_oauth_token(self):
        creds = json.dumps({"claudeAiOauth": {"accessToken": "tok_123"}})
        assert _extract_token(creds) == "tok_123"

    def test_returns_none_for_missing_oauth(self):
        creds = json.dumps({"other": "data"})
        assert _extract_token(creds) is None

    def test_returns_none_for_invalid_json(self):
        assert _extract_token("not json") is None


class TestFormatResetDelta:
    def test_days_and_hours(self):
        future = datetime.now(timezone.utc) + timedelta(days=5, hours=13)
        result = _format_reset_delta(future.isoformat())
        assert result.startswith("5d 1")  # 5d 13h or 5d 12h depending on timing

    def test_hours_and_minutes(self):
        future = datetime.now(timezone.utc) + timedelta(hours=2, minutes=30)
        result = _format_reset_delta(future.isoformat())
        assert result.startswith("2h ")

    def test_minutes_only(self):
        future = datetime.now(timezone.utc) + timedelta(minutes=45)
        result = _format_reset_delta(future.isoformat())
        assert result.endswith("m")
        assert "h" not in result

    def test_past_returns_now(self):
        past = datetime.now(timezone.utc) - timedelta(minutes=5)
        assert _format_reset_delta(past.isoformat()) == "now"

    def test_z_suffix(self):
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        ts = future.strftime("%Y-%m-%dT%H:%M:%SZ")
        result = _format_reset_delta(ts)
        assert "h" in result or "m" in result


class TestFormatUsage:
    @patch("claude_switcher.usage.datetime")
    def test_formats_both_periods(self, mock_dt):
        now = datetime(2026, 3, 19, 10, 0, 0, tzinfo=timezone.utc)
        mock_dt.now.return_value = now
        mock_dt.fromisoformat = datetime.fromisoformat
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        usage = {
            "five_hour": {"utilization": 42.7, "resets_at": "2026-03-19T12:00:00+00:00"},
            "seven_day": {"utilization": 18.3, "resets_at": "2026-03-25T00:00:00+00:00"},
        }
        result = format_usage(usage)
        assert "5h 43% (2h 0m)" in result
        assert "7j 18% (5d 14h)" in result

    def test_returns_unavailable_for_none(self):
        assert format_usage(None) == "Usage indisponible"

    def test_returns_unavailable_for_empty(self):
        assert format_usage({}) == "Usage indisponible"


class TestFetchUsageForAccount:
    @patch("claude_switcher.usage.urllib.request.urlopen")
    @patch("claude_switcher.usage.keychain.read_credentials")
    def test_fetches_and_parses(self, mock_read, mock_urlopen):
        mock_read.return_value = json.dumps({"claudeAiOauth": {"accessToken": "tok"}})
        response_data = json.dumps({
            "five_hour": {"utilization": 50.0, "resets_at": "2026-03-19T12:00:00Z"},
            "seven_day": {"utilization": 20.0, "resets_at": "2026-03-25T00:00:00Z"},
        }).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = response_data
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = fetch_usage_for_account("test@test.com")
        assert result["five_hour"]["utilization"] == 50.0

    @patch("claude_switcher.usage.keychain.read_credentials")
    def test_returns_none_when_no_creds(self, mock_read):
        mock_read.return_value = None
        assert fetch_usage_for_account("test@test.com") is None
