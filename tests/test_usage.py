"""Tests for the usage module."""

import json
from unittest.mock import patch, MagicMock

from claude_switcher.usage import _extract_token, format_usage, fetch_usage_for_account


class TestExtractToken:
    def test_extracts_oauth_token(self):
        creds = json.dumps({"claudeAiOauth": {"accessToken": "tok_123"}})
        assert _extract_token(creds) == "tok_123"

    def test_returns_none_for_missing_oauth(self):
        creds = json.dumps({"other": "data"})
        assert _extract_token(creds) is None

    def test_returns_none_for_invalid_json(self):
        assert _extract_token("not json") is None


class TestFormatUsage:
    def test_formats_both_periods(self):
        usage = {
            "five_hour": {"utilization": 42.7, "resets_at": "2026-03-19T12:00:00Z"},
            "seven_day": {"utilization": 18.3, "resets_at": "2026-03-25T00:00:00Z"},
        }
        assert format_usage(usage) == "5h: 43% | 7j: 18%"

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
