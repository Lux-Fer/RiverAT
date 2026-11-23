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
    # 看板与发布显示用的本地时区（D81）；默认国内市场
    display_timezone: str = "Asia/Shanghai"
    access_token_expire_minutes: int = 60
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:5173"]
    # 相对路径的插件包从这儿解析（绝对路径原样使用）
    bundle_root: Path = BASE_DIR / "var" / "plugins"
    # v1.1 工具包存放目录（上传的 tar.gz）
    tools_root: Path = BASE_DIR / "var" / "tools"
    # 会话（D43：服务端会话，cookie 只带 token）
    session_ttl_seconds: int = 8 * 3600
    # 首次启动、库里没有用户时，用它建管理员（为空则跳过）
    admin_username: str = "admin"
    admin_password: str = ""
    # v1.1 模型端点（D97）：OpenAI 兼容；DB 里没有配置时的兜底
    riverat_llm_base_url: str = ""
    riverat_llm_model: str = ""
    riverat_llm_api_key: str = ""
    # V0.1.2：任务失败后让模型观察结果并生成“修复草案”（仍需人确认）
    agent_recovery_enabled: bool = True
    agent_recovery_max_steps: int = 3
    agent_replan_limit: int = 2
    # V0.2.1：知识有效期；失败模式比成功方案衰减更快
    knowledge_failure_ttl_days: int = 30
    knowledge_success_ttl_days: int = 90
    # V0.3.0：每步执行后由模型判断继续/停止（不自动执行新工具）
    agent_step_review_enabled: bool = True
    agent_step_review_limit: int = 4
    # V0.3.0：单步失败后提出一个同任务修复，人确认后继续
    agent_step_repair_enabled: bool = True
    agent_step_repair_limit: int = 2
    # V0.3.1：仅全部步骤都是显式 read_only 工具时自动确认
    agent_auto_approve_read_only: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()


INSECURE_SECRET_KEYS = frozenset(
    {"", "change-me", "change-me-in-production", "your-secret-key"}
)


def validate_production_settings(settings: Settings | None = None) -> None:
    """生产启动前拒绝明显不安全的配置，避免默认值直接上线。"""

    current = settings or get_settings()
    if current.app_env != "prod":
        return
    if current.secret_key in INSECURE_SECRET_KEYS or len(current.secret_key) < 16:
        raise RuntimeError(
            "生产环境 SECRET_KEY 不安全：请用 openssl rand -hex 32 生成，"
            "并通过 shell 或项目根目录 .env 注入；不要使用默认值"
        )
    if current.debug:
        raise RuntimeError("生产环境 DEBUG 必须为 false")
