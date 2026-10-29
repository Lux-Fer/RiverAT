"""运行配置：从 ``backend/.env`` 读取，代码里只留安全的默认值。

注意 ``.env`` 的路径用绝对路径（相对本文件解析），因为 uvicorn / alembic
的工作目录不一定是 ``backend/``。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]  # backend/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "RiverAT"
    app_env: str = "dev"
    debug: bool = True
    secret_key: str = "change-me"
    database_url: str = "postgresql+asyncpg://riverat:123456@127.0.0.1:5433/riverat"
    redis_url: str = "redis://127.0.0.1:6379/0"
    access_token_expire_minutes: int = 60
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:5173"]
    # 相对路径的插件包从这儿解析（绝对路径原样使用）
    bundle_root: Path = BASE_DIR / "var" / "plugins"


@lru_cache
def get_settings() -> Settings:
    return Settings()
