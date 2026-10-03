"""OpenAI-compatible chat-completions engine.

The API key is read from a SecretStore at request time. It is never logged
and never embedded into engine errors; response snippets are redacted before
they reach an exception message.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

import httpx

from .base import (
    ChatMessage,
    EngineError,
    EngineReply,
    is_cancelled,
    validate_timeout,
)

LOGGER = logging.getLogger(__name__)

SNIPPET_LIMIT = 500
REDACTED = "[redacted]"


def _snippet(text: Any, secret: str, limit: int = SNIPPET_LIMIT) -> str:
    redacted = str(text)
    if secret and secret in redacted:
        redacted = redacted.replace(secret, REDACTED)
    if len(redacted) > limit:
        return redacted[:limit] + "...[truncated]"
    return redacted


class OpenAICompatibleEngine:
    """Chat-completions engine for OpenAI-compatible HTTP APIs."""

    name = "openai-compatible"

    def __init__(
        self,
        base_url: str,
        model: str,
        secret_store: Any,
        key_name: str,
        timeout_s: float = 120,
        transport: httpx.BaseTransport | None = None,
        client_factory: Callable[[], Any] | None = None,
    ):
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("base_url 必须是非空字符串")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model 必须是非空字符串")
        if not isinstance(key_name, str) or not key_name.strip():
            raise ValueError("key_name 必须是非空字符串")
        if secret_store is None:
            raise ValueError("secret_store 不能为 None")
        self._base_url = base_url.strip().rstrip("/")
        self._model = model.strip()
        self._secret_store = secret_store
        self._key_name = key_name
        self._timeout_s = validate_timeout(timeout_s, "timeout_s")
        self._transport = transport
        self._client_factory = client_factory

    def send(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[dict] | None = None,
        timeout_s: float | None = None,
        cancel: Any = None,
    ) -> EngineReply:
        if is_cancelled(cancel):
            raise EngineError("请求已取消")
        key = self._api_key()
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
        }
        if tools is not None:
            payload["tools"] = tools
        effective_timeout = (
            self._timeout_s
            if timeout_s is None
            else validate_timeout(timeout_s, "timeout_s")
        )
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        url = f"{self._base_url}/chat/completions"
        LOGGER.debug("POST %s model=%s", url, self._model)
        try:
            with self._make_client() as client:
                response = client.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=effective_timeout,
                )
        except httpx.TimeoutException as exc:
            raise EngineError(
                f"请求超时（{effective_timeout:g}s）: {_snippet(exc, key)}"
            ) from exc
        except httpx.HTTPError as exc:
            raise EngineError(f"请求失败: {_snippet(exc, key)}") from exc
        if is_cancelled(cancel):
            raise EngineError("请求已取消")
        if not 200 <= response.status_code < 300:
            raise EngineError(
                f"HTTP {response.status_code}: "
                f"{_snippet(self._response_text(response), key)}"
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise EngineError(
                "响应不是合法 JSON: "
                f"{_snippet(self._response_text(response), key)}"
            ) from exc
        return self._parse_reply(body)

    def _api_key(self) -> str:
        try:
            value = self._secret_store.get(self._key_name)
        except Exception as exc:  # adapter boundary: surface store failures
            raise EngineError(f"无法读取 API key: {exc}") from exc
        if not isinstance(value, str) or not value.strip():
            raise EngineError(
                "未配置 API key：请先在设置中保存该 provider 的密钥"
            )
        return value.strip()

    def _make_client(self) -> Any:
        if self._client_factory is not None:
            return self._client_factory()
        return httpx.Client(transport=self._transport, timeout=self._timeout_s)

    @staticmethod
    def _response_text(response: Any) -> str:
        try:
            return response.text
        except Exception:
            return ""

    @staticmethod
    def _parse_reply(body: Any) -> EngineReply:
        if not isinstance(body, dict):
            raise EngineError("响应 JSON 顶层必须是对象")
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise EngineError("响应缺少 choices")
        first = choices[0]
        if not isinstance(first, dict):
            raise EngineError("choices[0] 必须是对象")
        message = first.get("message")
        if not isinstance(message, dict):
            raise EngineError("choices[0].message 必须是对象")
        content = message.get("content")
        if content is None:
            text = ""
        elif isinstance(content, str):
            text = content
        else:
            raise EngineError("choices[0].message.content 必须是字符串或 null")
        tool_calls = message.get("tool_calls")
        if tool_calls is None:
            tool_calls = []
        elif not isinstance(tool_calls, list):
            raise EngineError("choices[0].message.tool_calls 必须是列表")
        return EngineReply(text=text, tool_calls=list(tool_calls))
