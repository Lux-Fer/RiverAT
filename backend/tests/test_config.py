"""生产配置守卫。"""

from __future__ import annotations

import pytest

from app.core.config import Settings, validate_production_settings


def test_production_rejects_default_secret():
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        validate_production_settings(
            Settings(
                app_env="prod",
                debug=False,
                secret_key="change-me-in-production",
            )
        )


def test_production_rejects_short_secret():
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        validate_production_settings(
            Settings(app_env="prod", debug=False, secret_key="short")
        )


def test_production_rejects_debug():
    with pytest.raises(RuntimeError, match="DEBUG"):
        validate_production_settings(
            Settings(app_env="prod", debug=True, secret_key="a" * 64)
        )


def test_development_allows_local_defaults():
    validate_production_settings(
        Settings(app_env="dev", debug=True, secret_key="luxfer")
    )
