"""V0.1.2：送入模型前的脱敏。

这不是完整的 DLP：只覆盖常见密钥字段、Bearer/Cookie、URL 内嵌密码和常见
供应商 token 前缀。工具输出仍按不可信数据处理，不能因为脱敏就放宽提示。
"""

from __future__ import annotations

import re

REDACTED = "[REDACTED]"

_SENSITIVE_KEYS = {
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "set_cookie",
    "session",
    "session_id",
    "credential",
    "credentials",
    "private_key",
}

_URL_USERINFO = re.compile(
    r"(?P<scheme>https?://)(?P<user>[^/\s:@]+):(?P<password>[^/\s@]+)@",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(?i)\b(bearer\s+)([A-Za-z0-9._~+/=-]{8,})")
_KEY_VALUE = re.compile(
    r"(?i)\b(password|passwd|pwd|token|secret|api[_-]?key|authorization|cookie|session)"
    r"(\s*[=:]\s*)([\"']?)([^\"'\s,;]+)\3"
)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_PREFIXED_KEYS = re.compile(
    r"\b(?:sk|pk|ghp|gho|glpat|xox[baprs])[-_][A-Za-z0-9_-]{8,}\b",
    re.IGNORECASE,
)


def is_sensitive_key(key: object) -> bool:
    normalized = str(key).strip().lower().replace("-", "_")
    if normalized in _SENSITIVE_KEYS:
        return True
    return normalized.endswith(("_token", "_secret", "_password", "_api_key"))


def redact_text(value: object) -> str:
    text = str(value or "")
    if not text:
        return ""
    text = _URL_USERINFO.sub(r"\g<scheme>***:***@", text)
    text = _BEARER.sub(r"\g<1>***", text)
    text = _KEY_VALUE.sub(r"\g<1>\g<2>\g<3>***\g<3>", text)
    text = _JWT.sub(REDACTED, text)
    text = _PREFIXED_KEYS.sub(REDACTED, text)
    return text


def redact_value(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: REDACTED if is_sensitive_key(key) else redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value
