from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from .ai_governance import FakeProvider, LLMProvider


class OpenAICompatibleProvider:
    """OpenAI-compatible API provider.

    API key is read from the ODDS_JOURNAL_LLM_API_KEY environment variable.
    Base URL can be overridden via ODDS_JOURNAL_LLM_BASE_URL (defaults to https://api.openai.com/v1).
    """

    provider_id = "openai-compatible"

    def __init__(self) -> None:
        self._api_key = os.environ.get("ODDS_JOURNAL_LLM_API_KEY")
        if not self._api_key:
            raise ValueError("缺少 ODDS_JOURNAL_LLM_API_KEY 环境变量")
        self._base_url = os.environ.get("ODDS_JOURNAL_LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")

    def run(self, *, model_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        payload_sha256 = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        request_body = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": "You are a football odds analyst. Respond only in Chinese. Output only valid JSON defined by the supplied schema. Do not include markdown fences, commentary, or additional text."},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
            ],
            "temperature": 0.0,
        }
        response = self._call_api(request_body)
        return {
            "model_id": model_id,
            "payload_sha256": payload_sha256,
            "response": response.get("content", {}),
            "input_tokens": response.get("input_tokens", 0),
            "output_tokens": response.get("output_tokens", 0),
        }

    def _call_api(self, body: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        max_retries = 2
        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                req = urllib.request.Request(url, data=data, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=120) as resp:
                    raw = json.loads(resp.read().decode("utf-8"))
                choice = raw.get("choices", [{}])[0]
                content_text = choice.get("message", {}).get("content", "{}")
                try:
                    content = json.loads(content_text)
                except json.JSONDecodeError:
                    content = {"raw": content_text}
                return {
                    "content": content,
                    "input_tokens": raw.get("usage", {}).get("prompt_tokens", 0),
                    "output_tokens": raw.get("usage", {}).get("completion_tokens", 0),
                    "model": raw.get("model", ""),
                }
            except urllib.error.HTTPError as exc:
                last_error = exc
                status = exc.code
                if status == 429 and attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                raise ValueError(f"LLM API HTTP {status}：{exc.reason}") from exc
            except urllib.error.URLError as exc:
                last_error = exc
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                raise ValueError(f"LLM API 网络错误：{exc.reason}") from exc
        raise ValueError(f"LLM API 重试耗尽：{last_error}")


PROVIDER_REGISTRY: dict[str, type] = {
    "fake-offline": FakeProvider,
    "openai-compatible": OpenAICompatibleProvider,
}


def get_provider(provider_id: str) -> LLMProvider:
    cls = PROVIDER_REGISTRY.get(provider_id)
    if cls is None:
        raise ValueError(f"未知 AI provider：{provider_id}")
    return cls()