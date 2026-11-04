"""v1.1 任务（M3/M4，D95）：对话出草案 → 人确认 → 执行 → 结果。

M3 只生成草案；M4 增加确认、执行与结果聚合。
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChatMessage, Task, TaskStep, Tool, User, WorkProduct
from app.services import llm
from app.services.tools import available_tools

SYSTEM_PROMPT = """你是 RiverAT 的测试任务助手。

你的工作：把用户的测试需求，转换成**工具调用草案**。

规则：
1. 只能调用给出的工具，不要编造工具。
2. **发出 tool_call 只是"提出草案"，平台不会真的执行**，所以要用 tool_calls 表达你想调用的工具与参数，不要只用文字描述。
3. 参数必须符合工具的 JSON Schema。信息足够时必须给出 tool_calls；缺少必要信息时不要猜，在回复里说明缺什么（可以不调用工具）。
4. 不要声称已经执行；你只提出草案，等人确认。
5. 回复用中文，简短说明你打算做什么。
"""


class TaskError(ValueError):
    """无法生成任务草案。"""


def validate_args(schema: dict, args: dict) -> list[str]:
    """最小 JSON Schema 校验：required + 顶层 type，不引入额外依赖。"""

    if not isinstance(args, dict):
        return ["参数必须是对象"]

    problems: list[str] = []
    for key in schema.get("required", []):
        if key not in args:
            problems.append(f"缺少 {key}")

    props = schema.get("properties", {})
    type_map = {
        "string": str,
        "number": (int, float),
        "integer": int,
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    for key, value in args.items():
        prop = props.get(key)
        if not isinstance(prop, dict):
            continue
        expected = prop.get("type")
        python_type = type_map.get(expected)
        if python_type and not isinstance(value, python_type):
            problems.append(f"{key} 应为 {expected}")
    return problems


async def _tool_specs(
    session: AsyncSession,
) -> tuple[list[dict], dict[str, Tool]]:
    """已审核工具 → OpenAI tools 定义；同名工具取最新版本。"""

    by_name: dict[str, Tool] = {}
    for tool in await available_tools(session):
        by_name.setdefault(tool.name, tool)

    specs = [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or tool.name,
                "parameters": (tool.manifest or {}).get(
                    "input_schema", {"type": "object", "properties": {}}
                ),
            },
        }
        for tool in by_name.values()
    ]
    return specs, by_name


async def propose_task(
    session: AsyncSession,
    *,
    text: str,
    product_id: UUID | None = None,
    actor: User | None = None,
) -> Task:
    text = text.strip()
    if not text:
        raise TaskError("请先输入需求")

    specs, by_name = await _tool_specs(session)
    if not specs:
        raise TaskError("还没有审核通过的工具，先去「工具」上传并审核")

    product = await session.get(WorkProduct, product_id) if product_id else None
    if product is None:
        context = "未指定被测产品。"
    else:
        context = (
            f"被测产品：{product.code} · {product.name}"
            f"（地址 {product.base_url or '未填写'}）。"
        )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"{context}\n\n需求：{text}"},
    ]
    answer = await llm.chat(session, messages, tools=specs, max_tokens=1024)

    calls = answer.get("tool_calls") or []
    errors: list[str] = []
    steps: list[TaskStep] = []

    for seq, call in enumerate(calls, start=1):
        function = call.get("function") or {}
        name = function.get("name")
        tool = by_name.get(name or "")
        if tool is None:
            errors.append(f"模型调用了未知工具：{name}")
            continue

        raw_args = function.get("arguments")
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except json.JSONDecodeError:
            args = None
        if not isinstance(args, dict):
            errors.append(f"{name} 的参数不是合法 JSON 对象")
            continue

        problems = validate_args((tool.manifest or {}).get("input_schema", {}), args)
        if problems:
            errors.append(f"{name} 参数不完整：{'；'.join(problems)}")

        steps.append(
            TaskStep(
                seq=seq,
                tool_id=tool.id,
                tool_name=tool.name,
                tool_version=tool.version,
                args=args,
                status="pending",
            )
        )

    reply = (answer.get("content") or "").strip()
    task = Task(
        product_id=product.id if product else None,
        title=text[:60],
        request_text=text,
        status="draft",
        draft={
            "reply": reply,
            "tool_calls": calls,
            "errors": errors,
        },
        created_by=actor.id if actor else None,
    )
    session.add(task)
    await session.flush()

    for step in steps:
        step.task_id = task.id
        session.add(step)

    session.add(ChatMessage(task_id=task.id, role="user", content=text))
    fallback = (
        f"已生成草案，共 {len(steps)} 个工具调用。" if steps else "没有生成工具调用。"
    )
    session.add(
        ChatMessage(
            task_id=task.id,
            role="assistant",
            content=reply or fallback,
        )
    )
    await session.flush()
    return task


async def list_messages(session: AsyncSession, *, limit: int = 30) -> list[ChatMessage]:
    rows = await session.execute(
        select(ChatMessage).order_by(ChatMessage.created_at.desc()).limit(limit)
    )
    return list(reversed(rows.scalars().all()))


async def latest_draft(session: AsyncSession) -> Task | None:
    return await session.scalar(
        select(Task)
        .where(Task.status == "draft")
        .order_by(Task.created_at.desc())
        .limit(1)
    )


async def steps_for(session: AsyncSession, task_id: UUID) -> list[TaskStep]:
    rows = await session.execute(
        select(TaskStep).where(TaskStep.task_id == task_id).order_by(TaskStep.seq)
    )
    return list(rows.scalars().all())


# ---------------------------------------------------------------- M4：确认与执行


def _aggregate(statuses: list[str]) -> str:
    if any(status == "error" for status in statuses):
        return "error"
    if any(status == "failed" for status in statuses):
        return "failed"
    if statuses and all(status == "skipped" for status in statuses):
        return "skipped"
    return "passed"


async def get_task(session: AsyncSession, task_id: UUID) -> Task | None:
    return await session.get(Task, task_id)


async def list_tasks(session: AsyncSession, *, limit: int = 100) -> list[Task]:
    rows = await session.execute(
        select(Task).order_by(Task.created_at.desc()).limit(limit)
    )
    return list(rows.scalars().all())


async def create_manual_task(
    session: AsyncSession,
    *,
    tool_id: UUID,
    args: object,
    product_id: UUID | None = None,
    title: str = "",
    actor: User | None = None,
) -> Task:
    """模型不可用时的降级入口（D97/D108）：人选工具、填参数，生成草案。"""

    from app.models import Tool

    tool = await session.get(Tool, tool_id)
    if tool is None or tool.status != "approved":
        raise TaskError("工具不存在或还没有审核通过")
    if not isinstance(args, dict):
        raise TaskError("参数必须是 JSON 对象")

    problems = validate_args((tool.manifest or {}).get("input_schema", {}), args)
    if problems:
        raise TaskError("；".join(problems))

    task = Task(
        product_id=product_id,
        title=(title.strip() or f"手动：{tool.name}")[:200],
        request_text="手动创建（不经过模型）",
        status="draft",
        draft={
            "reply": f"手动创建：调用 {tool.name}，确认后执行。",
            "tool_calls": [],
            "errors": [],
        },
        created_by=actor.id if actor else None,
    )
    session.add(task)
    await session.flush()
    session.add(
        TaskStep(
            task_id=task.id,
            seq=1,
            tool_id=tool.id,
            tool_name=tool.name,
            tool_version=tool.version,
            args=args,
            status="pending",
        )
    )
    await session.flush()

    from app.services.audit import record

    await record(
        session,
        actor=actor,
        action="task.create",
        target_type="task",
        target_id=str(task.id),
        detail={"title": task.title[:120], "tool": tool.name, "keys": sorted(args)},
    )
    return task


async def approve_task(
    session: AsyncSession, task: Task, *, actor: User | None
) -> Task:
    if task.status != "draft":
        raise TaskError(f"只有草案可以确认，当前状态：{task.status}")
    task.status = "queued"
    task.approved_by = actor.id if actor else None
    task.approved_at = datetime.now(UTC)
    await session.flush()

    from app.services.audit import record

    await record(
        session,
        actor=actor,
        action="task.approve",
        target_type="task",
        target_id=str(task.id),
        detail={
            "title": task.title[:120],
            "steps": len(await steps_for(session, task.id)),
        },
    )
    return task


async def cancel_task(
    session: AsyncSession, task: Task, *, actor: User | None = None
) -> Task:
    if task.status not in ("draft", "queued", "running"):
        raise TaskError(f"只能取消未完成的任务，当前状态：{task.status}")
    previous = task.status
    # 运行中不硬杀进程：标成 cancelling，worker 在步骤之间停下（D107）
    task.status = "cancelling" if previous == "running" else "cancelled"
    if previous != "running":
        task.finished_at = datetime.now(UTC)
    await session.flush()

    from app.services.audit import record

    await record(
        session,
        actor=actor,
        action="task.cancel",
        target_type="task",
        target_id=str(task.id),
        detail={"title": task.title[:120], "from": previous},
    )
    return task


async def rerun_task(
    session: AsyncSession, task: Task, *, actor: User | None = None
) -> Task:
    """复制一个任务的步骤，生成新的草案（D107）：不偷偷重跑，仍要人确认。"""

    steps = await steps_for(session, task.id)
    if not steps:
        raise TaskError("任务没有步骤，无法重跑")

    new_task = Task(
        product_id=task.product_id,
        title=f"{task.title[:180]}（重跑）",
        request_text=task.request_text,
        status="draft",
        draft={
            "reply": f"从任务 {str(task.id)[:8]} 重跑，参数已复制；确认后执行。",
            "tool_calls": [],
            "errors": [],
        },
        created_by=actor.id if actor else None,
    )
    session.add(new_task)
    await session.flush()

    for step in steps:
        session.add(
            TaskStep(
                task_id=new_task.id,
                seq=step.seq,
                tool_id=step.tool_id,
                tool_name=step.tool_name,
                tool_version=step.tool_version,
                args=step.args,
                status="pending",
            )
        )
    await session.flush()

    from app.services.audit import record

    await record(
        session,
        actor=actor,
        action="task.rerun",
        target_type="task",
        target_id=str(new_task.id),
        detail={"from": str(task.id)[:8], "steps": len(steps)},
    )
    return new_task


async def update_step_args(
    session: AsyncSession,
    task: Task,
    step_id: UUID,
    args: object,
    *,
    actor: User | None = None,
) -> TaskStep:
    """草案阶段改某个步骤的参数（D106）；只校验、不执行。"""

    from app.models import Tool

    if task.status != "draft":
        raise TaskError(f"只有草案可以改参数，当前状态：{task.status}")
    if not isinstance(args, dict):
        raise TaskError("参数必须是 JSON 对象")

    step = await session.get(TaskStep, step_id)
    if step is None or step.task_id != task.id:
        raise TaskError("步骤不存在")

    tool = await session.get(Tool, step.tool_id) if step.tool_id else None
    if tool is None:
        raise TaskError("工具不存在或已被删除")

    problems = validate_args((tool.manifest or {}).get("input_schema", {}), args)
    if problems:
        raise TaskError("；".join(problems))

    step.args = args
    await session.flush()

    from app.services.audit import record

    await record(
        session,
        actor=actor,
        action="task.edit",
        target_type="task",
        target_id=str(task.id),
        detail={
            "step": step.seq,
            "tool": step.tool_name,
            "keys": sorted(args),
        },
    )
    return step


STALE_AFTER = timedelta(minutes=10)


def is_stale(task: Task, *, now: datetime | None = None) -> bool:
    """running/cancelling 且心跳过期 = 疑似 worker 已死（D109）。"""

    if task.status not in ("running", "cancelling"):
        return False
    now = now or datetime.now(UTC)
    reference = task.heartbeat_at or task.approved_at or task.created_at
    return reference is not None and reference < now - STALE_AFTER


async def stale_tasks(session: AsyncSession) -> list[Task]:
    rows = await session.execute(
        select(Task)
        .where(Task.status.in_(("running", "cancelling")))
        .order_by(Task.created_at)
    )
    now = datetime.now(UTC)
    return [task for task in rows.scalars().all() if is_stale(task, now=now)]


async def recover_task(
    session: AsyncSession, task: Task, *, actor: User | None = None
) -> Task:
    """把疑似卡死的任务标成 error，保留原因（D109）。"""

    if not is_stale(task):
        raise TaskError(f"任务没有超时，不能回收，当前状态：{task.status}")

    task.status = "error"
    task.finished_at = datetime.now(UTC)
    draft = dict(task.draft or {})
    errors = list(draft.get("errors") or [])
    errors.append("worker 心跳超时，任务已被标记失败（可重跑）")
    draft["errors"] = errors
    task.draft = draft
    await session.flush()

    from app.services.audit import record

    await record(
        session,
        actor=actor,
        action="task.recover",
        target_type="task",
        target_id=str(task.id),
        detail={"title": task.title[:120], "status": "error"},
    )
    return task


async def recover_stale_tasks(session: AsyncSession) -> int:
    """worker 启动时扫一遍，回收上次崩溃留下的僵尸任务。"""

    recovered = 0
    for task in await stale_tasks(session):
        await recover_task(session, task, actor=None)
        recovered += 1
    return recovered


async def _heartbeat_loop(task_id: UUID, stop: asyncio.Event) -> None:
    """独立会话每 30s 刷新一次心跳，避免长步骤被误判为僵尸（D109）。"""

    from sqlalchemy import update

    from app.db.session import get_sessionmaker

    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=30)
            return
        except TimeoutError:
            pass
        try:
            async with get_sessionmaker()() as heartbeat_session:
                await heartbeat_session.execute(
                    update(Task)
                    .where(Task.id == task_id)
                    .values(heartbeat_at=datetime.now(UTC))
                )
                await heartbeat_session.commit()
        except Exception:  # noqa: BLE001 - 心跳失败不影响执行
            return


async def execute_task(session: AsyncSession, task: Task) -> Task:
    """逐步执行任务；每步一个工具调用，失败不中断后续步骤。"""

    from app.models import Tool
    from app.services.tool_exec import run_tool

    steps = await steps_for(session, task.id)
    product = (
        await session.get(WorkProduct, task.product_id) if task.product_id else None
    )

    # 排队期间被取消（D107）：还没开始就不要再跑
    await session.refresh(task)
    if task.status == "cancelling":
        task.status = "cancelled"
        task.finished_at = datetime.now(UTC)
        await session.flush()
        return task

    task.status = "running"
    task.heartbeat_at = datetime.now(UTC)
    await session.flush()

    stop = asyncio.Event()
    heartbeat = asyncio.create_task(_heartbeat_loop(task.id, stop))
    try:
        statuses: list[str] = []
        cancelled = False

        for step in steps:
            # 运行中取消（D107）：步骤之间检查，当前步骤跑完为止
            await session.refresh(task)
            if task.status == "cancelling":
                cancelled = True
                break

            task.heartbeat_at = datetime.now(UTC)
            step.status = "running"
            step.started_at = datetime.now(UTC)
            await session.flush()

            tool = await session.get(Tool, step.tool_id) if step.tool_id else None
            if tool is None:
                result = {
                    "status": "error",
                    "exit_code": None,
                    "output": {},
                    "stderr": "",
                    "error": "工具不存在或已被删除",
                }
            else:
                try:
                    result = await run_tool(
                        tool,
                        args=step.args or {},
                        product=product,
                        task_id=str(task.id),
                    )
                except Exception as exc:  # noqa: BLE001 - 单步异常不能让任务卡死
                    result = {
                        "status": "error",
                        "exit_code": None,
                        "output": {},
                        "stderr": "",
                        "error": f"执行异常：{exc}",
                    }

            step.status = result["status"]
            step.exit_code = result.get("exit_code")
            output = dict(result.get("output") or {})
            if result.get("stderr"):
                output["stderr"] = str(result["stderr"])[:2000]
            step.output = output
            step.error = (result.get("error") or "")[:500] or None
            step.finished_at = datetime.now(UTC)
            statuses.append(step.status)
            await session.flush()

        task.status = "cancelled" if cancelled else _aggregate(statuses)
        task.finished_at = datetime.now(UTC)
        await session.flush()
        return task
    finally:
        stop.set()
        heartbeat.cancel()


async def execute_task_by_id(task_id: UUID) -> None:
    """worker 入口：自己开一个会话，执行完提交。"""

    from app.db.session import get_sessionmaker

    async with get_sessionmaker()() as session:
        task = await get_task(session, task_id)
        if task is None or task.status not in ("queued", "running"):
            return
        await execute_task(session, task)
        await session.commit()
