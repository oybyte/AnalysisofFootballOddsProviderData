from __future__ import annotations

import json
import os
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from odds_journal.llm_provider import (
    PROVIDER_REGISTRY,
    OpenAICompatibleProvider,
    get_provider,
)


class TestOpenAICompatibleProvider:
    def test_requires_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ODDS_JOURNAL_LLM_API_KEY", raising=False)
        with pytest.raises(ValueError, match="缺少 ODDS_JOURNAL_LLM_API_KEY"):
            OpenAICompatibleProvider()

    def test_uses_api_key_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ODDS_JOURNAL_LLM_API_KEY", "test-key-123")
        provider = OpenAICompatibleProvider()
        assert provider._api_key == "test-key-123"

    def test_uses_default_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ODDS_JOURNAL_LLM_API_KEY", "test-key")
        monkeypatch.delenv("ODDS_JOURNAL_LLM_BASE_URL", raising=False)
        provider = OpenAICompatibleProvider()
        assert provider._base_url == "https://api.openai.com/v1"

    def test_uses_custom_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ODDS_JOURNAL_LLM_API_KEY", "test-key")
        monkeypatch.setenv("ODDS_JOURNAL_LLM_BASE_URL", "https://api.deepseek.com/v1")
        provider = OpenAICompatibleProvider()
        assert provider._base_url == "https://api.deepseek.com/v1"

    def test_run_returns_standard_format(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ODDS_JOURNAL_LLM_API_KEY", "test-key")
        provider = OpenAICompatibleProvider()

        mock_response = {
            "choices": [{"message": {"content": '{"key": "value"}'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            "model": "gpt-4o-mini",
        }

        with patch.object(provider, "_call_api", return_value={
            "content": {"key": "value"},
            "input_tokens": 10,
            "output_tokens": 5,
            "model": "gpt-4o-mini",
        }):
            result = provider.run(model_id="gpt-4o-mini", payload={"test": True})

        assert result["model_id"] == "gpt-4o-mini"
        assert "payload_sha256" in result
        assert len(result["payload_sha256"]) == 64
        assert result["response"] == {"key": "value"}
        assert result["input_tokens"] == 10
        assert result["output_tokens"] == 5

    def test_run_handles_non_json_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ODDS_JOURNAL_LLM_API_KEY", "test-key")
        provider = OpenAICompatibleProvider()

        with patch.object(provider, "_call_api", return_value={
            "content": {"raw": "plain text response"},
            "input_tokens": 5,
            "output_tokens": 3,
            "model": "gpt-4o-mini",
        }):
            result = provider.run(model_id="gpt-4o-mini", payload={"test": True})

        assert result["response"] == {"raw": "plain text response"}

    def test_http_error_429_retries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ODDS_JOURNAL_LLM_API_KEY", "test-key")
        provider = OpenAICompatibleProvider()

        call_count = [0]

        def mock_urlopen(req, timeout):
            call_count[0] += 1
            if call_count[0] < 3:
                raise urllib.error.HTTPError(
                    "https://test", 429, "Rate Limited", {}, None  # type: ignore[arg-type]
                )
            import io
            body = json.dumps({
                "choices": [{"message": {"content": '{"ok": true}'}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                "model": "gpt-4o-mini",
            }).encode("utf-8")
            return io.BytesIO(body)

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            result = provider._call_api({"model": "gpt-4o-mini", "messages": []})

        assert call_count[0] == 3
        assert result["content"] == {"ok": True}

    def test_http_error_non_retryable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ODDS_JOURNAL_LLM_API_KEY", "test-key")
        provider = OpenAICompatibleProvider()

        def mock_urlopen(req, timeout):
            raise urllib.error.HTTPError(
                "https://test", 401, "Unauthorized", {}, None  # type: ignore[arg-type]
            )

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            with pytest.raises(ValueError, match="HTTP 401"):
                provider._call_api({"model": "gpt-4o-mini", "messages": []})

    def test_network_error_retries_then_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ODDS_JOURNAL_LLM_API_KEY", "test-key")
        provider = OpenAICompatibleProvider()

        def mock_urlopen(req, timeout):
            raise urllib.error.URLError("connection refused")

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            with pytest.raises(ValueError, match="网络错误"):
                provider._call_api({"model": "gpt-4o-mini", "messages": []})


class TestProviderRegistry:
    def test_fake_offline_in_registry(self) -> None:
        assert "fake-offline" in PROVIDER_REGISTRY

    def test_openai_compatible_in_registry(self) -> None:
        assert "openai-compatible" in PROVIDER_REGISTRY

    def test_unknown_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="未知 AI provider"):
            get_provider("nonexistent-provider")

    def test_get_provider_returns_instance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ODDS_JOURNAL_LLM_API_KEY", "test-key")
        provider = get_provider("openai-compatible")
        assert isinstance(provider, OpenAICompatibleProvider)
        assert provider.provider_id == "openai-compatible"

    def test_get_provider_fake_offline(self) -> None:
        from odds_journal.ai_governance import FakeProvider
        provider = get_provider("fake-offline")
        assert isinstance(provider, FakeProvider)
        assert provider.provider_id == "fake-offline"