"""V0.1.2：出站模型前脱敏。"""

from __future__ import annotations

from app.services.redaction import REDACTED, redact_text, redact_value


def test_redacts_common_secret_fields_recursively():
    payload = {
        "base_url": "http://example:8080",
        "password": "p@ss",
        "nested": {"api_key": "abc", "max_tokens": 1024},
        "headers": [{"Authorization": "Bearer abcdefghijkl"}],
    }

    result = redact_value(payload)

    assert result["password"] == REDACTED
    assert result["nested"]["api_key"] == REDACTED
    assert result["nested"]["max_tokens"] == 1024
    assert result["headers"][0]["Authorization"] == REDACTED


def test_redacts_urls_bearer_jwt_and_prefixed_keys():
    text = (
        "url http://alice:secret@example:8080 "
        "Authorization: Bearer abcdefghijklmnop "
        "token=plain-token "
        "jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature123 "
        "key sk-abcdefghijklmnop"
    )

    result = redact_text(text)

    assert "alice:secret" not in result
    assert "abcdefghijklmnop" not in result
    assert "plain-token" not in result
    assert "eyJhbGci" not in result
    assert "sk-abcdefghijklmnop" not in result
    assert "example:8080" in result
