"""Declarative HTTP tools: user-defined APIs the chat engine may call.

The registry is a YAML file. Each entry describes one HTTP request the model may
issue. The rules exist to keep a user-supplied file from turning into an
arbitrary-code or credential leak:

- v1 is HTTP-only. Arbitrary Python handlers are deliberately not supported:
  they would run with the app's own privileges and could not be validated.
- Plain ``http://`` is refused unless that tool opts in with
  ``allow_http: true``.
- A header that carries credentials must reference the keyring as
  ``secret:<key_name>``; a literal credential in a sensitive header is a load
  error, so no key ever lands in the registry file.
- Every ``{placeholder}`` in the url, query, body, or headers must be declared in
  the tool's ``parameters`` schema.

Calls are audited by :class:`~ccfa_core.tools_bridge.ToolBridge`, the only
intended caller; the registry itself writes nothing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, NamedTuple

import httpx
import yaml

SCHEMA_VERSION = 1
MAX_TIMEOUT_S = 120.0
MAX_RESPONSE_CHARS = 20_000

_NAME = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
_METHODS = ("GET", "POST")
_RISKS = ("read", "write")
_FIELDS = frozenset(
    {
        "name",
        "description",
        "method",
        "url",
        "risk",
        "timeout_s",
        "headers",
        "parameters",
        "query",
        "json",
        "allow_http",
    }
)
_SENSITIVE_HEADERS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "api-key",
        "x-auth-token",
    }
)
_SECRET_PREFIX = "secret:"


class RegistryIssue(NamedTuple):
    code: str
    path: str
    message: str


class HttpToolError(RuntimeError):
    """Raised by a registry call; ``code`` is surfaced by the tool bridge."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class HttpToolSpec:
    name: str
    description: str
    risk: str
    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    parameters: dict = field(default_factory=dict)
    timeout_s: float = 30.0
    query: dict[str, str] = field(default_factory=dict)
    body: dict[str, str] = field(default_factory=dict)


def _issue(code: str, path: Path, message: str) -> RegistryIssue:
    return RegistryIssue(code, str(path), message)


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_map(
    value: Any,
    path: Path,
    label: str,
    issues: list[RegistryIssue],
) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        issues.append(_issue("registry-invalid-field", path, f"{label} 必须是映射"))
        return {}
    result: dict[str, str] = {}
    for key, item in value.items():
        if not _is_text(key) or not isinstance(item, str):
            issues.append(
                _issue(
                    "registry-invalid-field",
                    path,
                    f"{label} 的键与值都必须是非空字符串",
                )
            )
            continue
        result[str(key)] = item
    return result


def _placeholders(text: str) -> set[str]:
    return {match.group(1).strip() for match in _PLACEHOLDER.finditer(text)}


def _validate_parameters(
    value: Any,
    path: Path,
    issues: list[RegistryIssue],
) -> tuple[dict, set[str]]:
    if not isinstance(value, dict):
        issues.append(
            _issue("registry-invalid-schema", path, "parameters 必须是对象")
        )
        return {}, set()
    if value.get("type") != "object":
        properties = value.get("properties")
        issues.append(
            _issue(
                "registry-invalid-schema",
                path,
                "parameters.type 必须是 object",
            )
        )
        # Keep the declared names so a broken schema does not also cascade a
        # spurious unknown-placeholder error for every template.
        return value, set(properties) if isinstance(properties, dict) else set()
    properties = value.get("properties")
    if not isinstance(properties, dict) or not properties:
        issues.append(
            _issue(
                "registry-invalid-schema",
                path,
                "parameters.properties 必须是非空映射",
            )
        )
        return value, set()
    required = value.get("required")
    if required is None:
        required = []
    if not isinstance(required, list) or not all(
        isinstance(item, str) for item in required
    ):
        issues.append(
            _issue(
                "registry-invalid-schema",
                path,
                "parameters.required 必须是字符串数组",
            )
        )
        return value, set(properties)
    unknown = sorted(set(required) - set(properties))
    if unknown:
        issues.append(
            _issue(
                "registry-invalid-schema",
                path,
                f"parameters.required 含未声明属性: {', '.join(unknown)}",
            )
        )
    if value.get("additionalProperties") is not False:
        issues.append(
            _issue(
                "registry-invalid-schema",
                path,
                "parameters.additionalProperties 必须是 false",
            )
        )
    return value, set(properties)


def _parse_tool(
    item: Any,
    index: int,
    path: Path,
    reserved_names: set[str],
) -> tuple[HttpToolSpec | None, list[RegistryIssue]]:
    issues: list[RegistryIssue] = []
    if not isinstance(item, dict):
        return None, [_issue("registry-invalid", path, f"tools[{index}] 必须是映射")]
    unknown = sorted(set(item) - _FIELDS)
    if unknown:
        issues.append(
            _issue(
                "registry-unknown-field",
                path,
                f"tools[{index}] 含未知字段: {', '.join(unknown)}",
            )
        )
    name = item.get("name")
    if not _is_text(name) or _NAME.match(name) is None:
        issues.append(
            _issue(
                "registry-invalid-name",
                path,
                f"tools[{index}].name 必须匹配 [a-z][a-z0-9_]{{1,63}}: {name!r}",
            )
        )
        name = None
    elif name in reserved_names:
        issues.append(
            _issue(
                "registry-name-conflict",
                path,
                f"工具名 {name!r} 与内置工具冲突",
            )
        )
        name = None

    description = item.get("description")
    if not _is_text(description):
        issues.append(
            _issue(
                "registry-invalid-field",
                path,
                f"tools[{index}].description 必须是非空字符串",
            )
        )

    method = item.get("method")
    if not isinstance(method, str) or method.upper() not in _METHODS:
        issues.append(
            _issue(
                "registry-invalid-method",
                path,
                f"tools[{index}].method 必须是 {' / '.join(_METHODS)}",
            )
        )
        method = None
    else:
        method = method.upper()

    risk = item.get("risk")
    if risk not in _RISKS:
        issues.append(
            _issue(
                "registry-invalid-risk",
                path,
                f"tools[{index}].risk 必须是 {' / '.join(_RISKS)}",
            )
        )
        risk = None

    timeout = item.get("timeout_s", 30.0)
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or timeout <= 0
        or timeout > MAX_TIMEOUT_S
    ):
        issues.append(
            _issue(
                "registry-invalid-timeout",
                path,
                f"tools[{index}].timeout_s 必须是 0 到 {MAX_TIMEOUT_S:g} 之间的数",
            )
        )
        timeout = 30.0

    allow_http = item.get("allow_http", False)
    if not isinstance(allow_http, bool):
        issues.append(
            _issue(
                "registry-invalid-field",
                path,
                f"tools[{index}].allow_http 必须是布尔值",
            )
        )
        allow_http = False
    url = item.get("url")
    if not _is_text(url) or not url.startswith(("https://", "http://")):
        issues.append(
            _issue(
                "registry-invalid-url",
                path,
                f"tools[{index}].url 必须是 http(s) URL",
            )
        )
        url = ""
    elif url.startswith("http://") and not allow_http:
        issues.append(
            _issue(
                "registry-insecure-url",
                path,
                f"工具 {name or index} 使用明文 http://；"
                "如确要如此，请显式写 allow_http: true",
            )
        )

    headers = _string_map(item.get("headers"), path, f"tools[{index}].headers", issues)
    for header, value in headers.items():
        if header.casefold() in _SENSITIVE_HEADERS:
            if not value.startswith(_SECRET_PREFIX) or not value[
                len(_SECRET_PREFIX) :
            ].strip():
                issues.append(
                    _issue(
                        "registry-literal-secret",
                        path,
                        f"工具 {name or index} 的敏感头 {header} 必须写成 "
                        '"secret:<key_name>"，不能写明文凭据',
                    )
                )
        if _SECRET_PREFIX in value and not value.startswith(_SECRET_PREFIX):
            issues.append(
                _issue(
                    "registry-literal-secret",
                    path,
                    f"工具 {name or index} 的 {header} 只能在值开头引用 secret:",
                )
            )

    query = _string_map(item.get("query"), path, f"tools[{index}].query", issues)
    body = _string_map(item.get("json"), path, f"tools[{index}].json", issues)
    if method == "GET" and body:
        issues.append(
            _issue(
                "registry-invalid-field",
                path,
                f"工具 {name or index} 是 GET，不能带 json body",
            )
        )

    parameters, declared = _validate_parameters(
        item.get("parameters"), path, issues
    )
    used: set[str] = _placeholders(url)
    for mapping in (query, body, headers):
        for value in mapping.values():
            if value.startswith(_SECRET_PREFIX):
                continue
            used |= _placeholders(value)
    for placeholder in sorted(used - declared):
        issues.append(
            _issue(
                "registry-unknown-placeholder",
                path,
                f"工具 {name or index} 使用了未声明的占位符 {{{placeholder}}}",
            )
        )

    if issues or name is None or method is None or risk is None or not url:
        return None, issues
    return (
        HttpToolSpec(
            name=name,
            description=description,
            risk=risk,
            method=method,
            url=url,
            headers=headers,
            parameters=parameters,
            timeout_s=float(timeout),
            query=query,
            body=body,
        ),
        issues,
    )


def load_registry(
    path: Path,
    *,
    reserved_names: tuple[str, ...] = (),
) -> tuple[list[HttpToolSpec], list[RegistryIssue]]:
    """Load and validate a registry; returns (specs, issues)."""
    path = Path(path)
    if not path.is_file():
        return [], [
            _issue(
                "registry-missing",
                path,
                f"找不到 HTTP 工具注册表 {path}",
            )
        ]
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        return [], [_issue("registry-invalid", path, f"无法读取注册表: {exc}")]
    if payload is None:
        return [], []
    if not isinstance(payload, dict):
        return [], [_issue("registry-invalid", path, "注册表顶层必须是映射")]
    version = payload.get("version")
    if type(version) is not int or version != SCHEMA_VERSION:
        return [], [
            _issue(
                "registry-invalid",
                path,
                f"注册表 version 必须是整数 {SCHEMA_VERSION}",
            )
        ]
    tools = payload.get("tools")
    if not isinstance(tools, list):
        return [], [_issue("registry-invalid", path, "tools 必须是数组")]

    specs: list[HttpToolSpec] = []
    issues: list[RegistryIssue] = []
    seen: set[str] = set()
    for index, item in enumerate(tools):
        spec, tool_issues = _parse_tool(
            item,
            index,
            path,
            set(reserved_names),
        )
        issues.extend(tool_issues)
        if spec is None:
            continue
        if spec.name in seen:
            issues.append(
                _issue(
                    "registry-duplicate-name",
                    path,
                    f"工具名重复: {spec.name}",
                )
            )
            continue
        seen.add(spec.name)
        specs.append(spec)
    if issues:
        # Fail closed: a registry with any invalid entry is not loaded at all,
        # so a half-broken file can never leave some tools silently active.
        return [], issues
    return specs, issues


class HttpToolRegistry:
    """Validated HTTP tools, ready to expose through the tool bridge."""

    def __init__(
        self,
        specs: list[HttpToolSpec],
        *,
        resolve_secret: Callable[[str], str | None] | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self._specs = {spec.name: spec for spec in specs}
        self._resolve_secret = resolve_secret
        self._transport = transport

    def specs(self) -> list[HttpToolSpec]:
        return list(self._specs.values())

    def risk(self, name: str) -> str:
        return self._specs[name].risk

    def openai_tools(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": json.loads(json.dumps(spec.parameters)),
                },
            }
            for spec in self._specs.values()
        ]

    def call(self, name: str, arguments: dict) -> Any:
        """Run one tool and return its result, raising ``HttpToolError``."""
        spec = self._specs.get(name)
        if spec is None:
            raise HttpToolError("unknown-tool", f"未知 HTTP 工具: {name!r}")
        request = self._build_request(spec, arguments or {})
        try:
            with httpx.Client(
                transport=self._transport,
                timeout=spec.timeout_s,
            ) as client:
                response = client.request(**request)
        except httpx.HTTPError as exc:
            raise HttpToolError(
                "http-error",
                f"请求失败: {type(exc).__name__}",
            ) from None
        if response.status_code >= 400:
            raise HttpToolError(
                "http-status",
                f"HTTP {response.status_code}",
            )
        return _read_response(response)

    def execute(self, name: str, arguments: dict | None = None) -> dict:
        """Convenience wrapper returning the bridge's result envelope."""
        arguments = arguments or {}
        try:
            value = self.call(name, arguments)
        except HttpToolError as exc:
            return {
                "ok": False,
                "tool": name,
                "error": {"code": exc.code, "message": str(exc)},
            }
        return {
            "ok": True,
            "tool": name,
            "risk": self.risk(name),
            "result": value,
        }

    def _build_request(self, spec: HttpToolSpec, arguments: dict) -> dict:
        url = _render(spec.url, arguments, required=True)
        params = _render_map(spec.query, arguments)
        body = _render_map(spec.body, arguments)
        headers = _render_headers(spec.headers, arguments, self._resolve_secret)
        request: dict[str, Any] = {
            "method": spec.method,
            "url": url,
            "headers": headers,
        }
        if params:
            request["params"] = params
        if body:
            request["json"] = body
        return request


def _render(template: str, arguments: dict, *, required: bool) -> str:
    def replace(match: re.Match) -> str:
        key = match.group(1).strip()
        value = arguments.get(key)
        if value is None:
            if required:
                raise HttpToolError(
                    "missing-argument",
                    f"缺少 URL 占位符参数: {key}",
                )
            return ""
        return str(value)

    return _PLACEHOLDER.sub(replace, template)


def _render_map(mapping: dict[str, str], arguments: dict) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, template in mapping.items():
        names = _placeholders(template)
        if any(arguments.get(name) is None for name in names):
            continue
        result[key] = _render(template, arguments, required=False)
    return result


def _render_headers(
    mapping: dict[str, str],
    arguments: dict,
    resolve_secret: Callable[[str], str | None] | None,
) -> dict[str, str]:
    headers: dict[str, str] = {}
    for key, template in mapping.items():
        if template.startswith(_SECRET_PREFIX):
            key_name = template[len(_SECRET_PREFIX) :].strip()
            value = resolve_secret(key_name) if resolve_secret else None
            if not value:
                raise HttpToolError(
                    "missing-secret",
                    f"缺少凭据 {key_name}：请在设置里配置该 key",
                )
            headers[key] = value
            continue
        names = _placeholders(template)
        if any(arguments.get(name) is None for name in names):
            continue
        headers[key] = _render(template, arguments, required=False)
    return headers


def _read_response(response: httpx.Response) -> dict:
    try:
        return {"status": response.status_code, "json": response.json()}
    except ValueError:
        text = response.text
        if len(text) > MAX_RESPONSE_CHARS:
            text = text[:MAX_RESPONSE_CHARS] + "...(truncated)"
        return {"status": response.status_code, "text": text}
