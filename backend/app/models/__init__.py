"""核心数据模型（D28 的最小可执行子集）。

设计要点：

* **产品树**（D4）：``product.parent_id`` 指向父产品；真正的组合关系落在
  ``version_component`` 上，因为"版本锁死"（D5）是版本级约束。
* **版本锁死**（D5）：一个父版本里，同一个子产品只能出现一次
  （``uq_component_child``），且必须指向一个具体的子版本。
* **计划**（D8/D50）：``plan.definition`` 存声明式 YAML/JSON，平台不解释语义。
* **执行**（D15）：``run_step.status`` 的五个终态由编排层写入，runner 只提供
  passed / failed / skipped / error，blocked 由依赖关系判定。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

RUN_STEP_STATUSES = ("passed", "failed", "skipped", "blocked", "error")
RUN_STATUSES = ("queued", "running", "passed", "failed", "error", "blocked")


def _new_uuid() -> uuid.UUID:
    return uuid.uuid4()


class User(Base):
    """本地账号（D36/D40）。LDAP/SSO 用户 `password_hash` 为空、`auth_source` 不同。"""

    __tablename__ = "user"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200), default="")
    password_hash: Mapped[str | None] = mapped_column(String(255))
    auth_source: Mapped[str] = mapped_column(String(32), default="local")
    external_id: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(32), default="engineer")
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Product(Base):
    """产品树节点。"""

    __tablename__ = "product"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("product.id", ondelete="SET NULL"), index=True
    )
    department: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ProductVersion(Base):
    """可复现的测试对象：产品的一个具体版本。"""

    __tablename__ = "product_version"
    __table_args__ = (
        UniqueConstraint("product_id", "version", name="uq_product_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(32), default="created")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class VersionComponent(Base):
    """版本组成：父版本锁定的一组子版本（D5）。"""

    __tablename__ = "version_component"
    __table_args__ = (
        UniqueConstraint(
            "parent_version_id", "child_product_id", name="uq_component_child"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    parent_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product_version.id", ondelete="CASCADE"), index=True
    )
    child_product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product.id", ondelete="RESTRICT"), index=True
    )
    child_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product_version.id", ondelete="RESTRICT")
    )


class Plan(Base):
    """声明式测试计划；内容不解释，只存原文（D8）。"""

    __tablename__ = "plan"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    product_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product_version.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    definition: Mapped[dict] = mapped_column(JSONB, default=dict)
    # 创建时冻结的展开结果与哈希（D59）：子计划之后怎么改，都不影响这条计划
    snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), default="")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Host(Base):
    """测试机（执行目标）。凭据只存密文（D22）。"""

    __tablename__ = "host"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    hostname: Mapped[str] = mapped_column(String(200))
    port: Mapped[int] = mapped_column(Integer, default=22)
    username: Mapped[str] = mapped_column(String(100))
    auth_type: Mapped[str] = mapped_column(String(32), default="password")
    secret_encrypted: Mapped[str] = mapped_column(String(1000))
    os: Mapped[str] = mapped_column(String(32), default="linux")
    status: Mapped[str] = mapped_column(String(32), default="unknown")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Run(Base):
    """一次执行实例。"""

    __tablename__ = "run"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("plan.id", ondelete="CASCADE"), index=True
    )
    host_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("host.id", ondelete="SET NULL"), index=True
    )
    product_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product_version.id", ondelete="CASCADE"), index=True
    )
    trigger: Mapped[str] = mapped_column(String(32), default="manual")
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=3)
    # 这次执行用的是哪一版计划快照（审计用）
    plan_sha256: Mapped[str | None] = mapped_column(String(64))
    plan_revision: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RunStep(Base):
    """计划节点的执行终态与证据指针（D15/D16）。"""

    __tablename__ = "run_step"
    __table_args__ = (
        UniqueConstraint("run_id", "node_key", "attempt", name="uq_run_step_attempt"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("run.id", ondelete="CASCADE"), index=True
    )
    node_key: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(32))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(String(500))
    # v0 证据：stdout/stderr 尾部（截断）、产物文件名、插件包哈希。
    # 完整证据表（对象存储 + 大文件）留到附件功能一起做。
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeSource(Base):
    """知识来源（D25/D26）：v1 只有执行记录，后续接 Jira/文档。"""

    __tablename__ = "knowledge_source"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    kind: Mapped[str] = mapped_column(String(32), default="run")
    ref_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class KnowledgeDoc(Base):
    __tablename__ = "knowledge_doc"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_source.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunk"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    doc_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_doc.id", ondelete="CASCADE"), index=True
    )
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Release(Base):
    """发布单（D72）：一个待发版本 + 计划发布日期。"""

    __tablename__ = "release"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    product_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product_version.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200), default="")
    target_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(32), default="planned", index=True)
    note: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    """审计日志（D82）：谁在什么时候改了什么。

    ``username`` 冗余保存，用户被删除后历史仍可读；``detail`` 只放差异字段。
    """

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), index=True
    )
    username: Mapped[str] = mapped_column(String(200), default="")
    action: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str] = mapped_column(String(64), default="")
    target_id: Mapped[str | None] = mapped_column(String(200))
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class LlmConfig(Base):
    """v1.1 模型端点（D97）：OpenAI 兼容；只保留一条 is_active。"""

    __tablename__ = "llm_config"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    base_url: Mapped[str] = mapped_column(String(500))
    api_key_enc: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class WorkProduct(Base):
    """v1.1 被测产品（D100）：地址 + CI 配置占位。"""

    __tablename__ = "work_product"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    base_url: Mapped[str] = mapped_column(String(500), default="")
    description: Mapped[str] = mapped_column(String(500), default="")
    # CI 通知在 v1.1 只存配置，不实际收发（D98）
    ci_provider: Mapped[str] = mapped_column(String(64), default="")
    ci_webhook_url: Mapped[str] = mapped_column(String(500), default="")
    ci_secret_enc: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Tool(Base):
    """v1.1 工具（D99）：上传的 tar.gz + tool.json，审核后可用。"""

    __tablename__ = "tool"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_tool_name_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(500), default="")
    manifest: Mapped[dict] = mapped_column(JSONB, default=dict)
    bundle_sha256: Mapped[str] = mapped_column(String(64))
    bundle_path: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Task(Base):
    """v1.1 任务（D95/D100）：对话产生草案，人确认后执行。"""

    __tablename__ = "task"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("work_product.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    request_text: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    draft: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TaskStep(Base):
    """任务中的一次工具调用（D99）。"""

    __tablename__ = "task_step"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("task.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer, default=1)
    tool_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tool.id", ondelete="SET NULL")
    )
    tool_name: Mapped[str] = mapped_column(String(200))
    tool_version: Mapped[str] = mapped_column(String(64), default="")
    args: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    output: Mapped[dict] = mapped_column(JSONB, default=dict)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(String(500))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ChatMessage(Base):
    """助手对话记录（D95）：回看"为什么这么测"。"""

    __tablename__ = "chat_message"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("task.id", ondelete="SET NULL"), index=True
    )
    role: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
