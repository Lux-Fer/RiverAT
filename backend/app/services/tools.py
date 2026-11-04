"""v1.1 工具（D99）：上传 tar.gz + tool.json，审核后可用。

校验清单（缺一不可）：
* `name` / `version` 非空；
* `entrypoint` 是 {系统: [命令...]}；
* `input_schema` 是 JSON Schema 对象（type = object）。

平台不执行工具代码，只存包与元数据；调用发生在任务执行阶段。
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Tool, User

MAX_BUNDLE_BYTES = 50 * 1024 * 1024


class ToolError(ValueError):
    """工具包不合法。"""


def _read_manifest(data: bytes) -> dict:
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            candidates = [
                member
                for member in tar.getmembers()
                if member.isfile() and member.name.split("/")[-1] == "tool.json"
            ]
            if not candidates:
                raise ToolError("工具包里没有 tool.json")
            member = min(candidates, key=lambda item: item.name.count("/"))
            handle = tar.extractfile(member)
            if handle is None:
                raise ToolError("无法读取 tool.json")
            return json.loads(handle.read().decode("utf-8"))
    except ToolError:
        raise
    except (tarfile.TarError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ToolError(f"工具包解析失败: {exc}") from exc


def _validate(manifest: dict) -> None:
    if not isinstance(manifest, dict):
        raise ToolError("tool.json 必须是对象")
    for field in ("name", "version"):
        if not str(manifest.get(field) or "").strip():
            raise ToolError(f"tool.json 缺少 {field}")
    entrypoint = manifest.get("entrypoint")
    if not isinstance(entrypoint, dict) or not entrypoint:
        raise ToolError("tool.json 的 entrypoint 必须是 {系统: [命令...]}")
    for os_name, argv in entrypoint.items():
        if not isinstance(argv, list) or not argv:
            raise ToolError(f"entrypoint[{os_name}] 必须是非空数组")
    schema = manifest.get("input_schema")
    if not isinstance(schema, dict) or schema.get("type") != "object":
        raise ToolError("input_schema 必须是 type=object 的 JSON Schema")

    runtime = manifest.get("runtime")
    if runtime is not None:
        if not isinstance(runtime, dict):
            raise ToolError("runtime 必须是对象")
        setup = runtime.get("setup")
        if setup is not None:
            if not isinstance(setup, list) or not setup:
                raise ToolError("runtime.setup 必须是非空数组")
            if not all(isinstance(part, str) and part for part in setup):
                raise ToolError("runtime.setup 的每一项都必须是非空字符串")
        timeout = runtime.get("setup_timeout_seconds")
        if timeout is not None and (
            not isinstance(timeout, (int, float)) or timeout <= 0
        ):
            raise ToolError("runtime.setup_timeout_seconds 必须是正数")


async def register_tool(
    session: AsyncSession, *, data: bytes, actor: User | None = None
) -> Tool:
    if not data:
        raise ToolError("上传内容为空")
    if len(data) > MAX_BUNDLE_BYTES:
        raise ToolError("工具包超过 50 MiB")

    manifest = _read_manifest(data)
    _validate(manifest)

    name = str(manifest["name"]).strip()
    version = str(manifest["version"]).strip()

    duplicate = await session.scalar(
        select(Tool).where(Tool.name == name, Tool.version == version)
    )
    if duplicate is not None:
        raise ToolError(f"工具已存在: {name}@{version}")

    sha256 = hashlib.sha256(data).hexdigest()
    tools_root = get_settings().tools_root
    tools_root.mkdir(parents=True, exist_ok=True)
    bundle_path = tools_root / f"{sha256}.tar.gz"
    if not bundle_path.exists():
        bundle_path.write_bytes(data)

    tool = Tool(
        name=name,
        version=version,
        description=str(manifest.get("description") or "")[:500],
        manifest=manifest,
        bundle_sha256=sha256,
        bundle_path=str(bundle_path),
        status="pending",
        uploaded_by=actor.id if actor else None,
    )
    session.add(tool)
    await session.flush()
    return tool


async def list_tools(session: AsyncSession, *, status: str | None = None) -> list[Tool]:
    stmt = select(Tool).order_by(Tool.created_at.desc())
    if status:
        stmt = stmt.where(Tool.status == status)
    rows = await session.execute(stmt)
    return list(rows.scalars().all())


async def get_tool(session: AsyncSession, tool_id: UUID) -> Tool | None:
    return await session.get(Tool, tool_id)


async def approve_tool(
    session: AsyncSession, tool: Tool, *, actor: User | None
) -> Tool:
    from datetime import UTC, datetime

    tool.status = "approved"
    tool.approved_by = actor.id if actor else None
    tool.approved_at = datetime.now(UTC)
    await session.flush()
    return tool


async def reject_tool(
    session: AsyncSession, tool: Tool, *, actor: User | None
) -> Tool:
    tool.status = "rejected"
    tool.approved_by = actor.id if actor else None
    await session.flush()
    return tool


async def available_tools(session: AsyncSession) -> list[Tool]:
    return await list_tools(session, status="approved")
