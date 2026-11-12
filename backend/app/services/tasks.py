"""v1.1 任务（M3/M4，D95）：对话出草案 → 人确认 → 执行 → 结果。

M3 只生成草案；M4 增加确认、执行与结果聚合。
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import ChatMessage, Task, TaskStep, Tool, User, WorkProduct
from app.services import llm
from app.services.knowledge_base import (
    format_knowledge,
    index_task_outcome,
    record_event,
    record_retrieval,
    search_knowledge,
)
from app.services.redaction import redact_text
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


TITLE_BREAKS = "，,。；;！!？?\n"


def task_title(text: str, limit: int = 60) -> str:
    """取需求的第一句/第一个分句作标题，避免在句子中间硬截断。"""

    cleaned = " ".join(text.split()).strip()
    if not cleaned:
        return "未命名任务"

    cut = len(cleaned)
    for sep in TITLE_BREAKS:
        index = cleaned.find(sep)
        if index != -1:
            cut = min(cut, index)
    head = cleaned[:cut].strip(" ，,。；;！!？?")
    # "你好，帮我..." 这类首分句过短时保留整段，避免标题只剩“你好”
    title = head if len(head) >= 8 else cleaned.strip(" ，,。；;！!？?")
    if len(title) > limit:
        title = title[:limit].rstrip() + "…"
    return title or "未命名任务"


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
    if product is not None and product.status != "active":
        raise TaskError("产品已归档，不能再创建任务")
    if product is None:
        context = "未指定被测产品。"
    else:
        context = (
            f"被测产品：{product.code} · {product.name}"
            f"（地址 {redact_text(product.base_url) or '未填写'}）。"
        )

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    history = await list_messages(
        session, limit=6, actor_id=actor.id if actor else None
    )
    for message in history:
        content = (message.content or "").strip()
        if content:
            messages.append(
                {"role": message.role, "content": redact_text(content)[:1200]}
            )
    messages.append(
        {"role": "user", "content": f"{context}\n\n需求：{text}"}
    )

    knowledge_items = await search_knowledge(
        session,
        f"{context}\n{text}",
        product_id=product_id,
        limit=4,
    )
    knowledge_text = format_knowledge(knowledge_items)
    if knowledge_text:
        messages[-1]["content"] = (
            f"{context}\n\n{knowledge_text}\n\n需求：{text}"
        )

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
        title=task_title(text),
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

    await record_event(
        session,
        event_key=f"task.created:{task.id}",
        kind="task.created",
        product_id=task.product_id,
        task_id=task.id,
        actor_id=task.created_by,
        payload={
            "title": task.title,
            "request": task.request_text[:2000],
            "draft": {
                "reply": reply[:1000],
                "tool_calls": calls[:5],
                "errors": errors,
            },
        },
    )
    await record_retrieval(
        session,
        consumer="plan",
        task_id=task.id,
        product_id=task.product_id,
        items=knowledge_items,
    )

    for step in steps:
        step.task_id = task.id
        session.add(step)

    now = datetime.now(UTC)
    session.add(
        ChatMessage(
            task_id=task.id, role="user", content=text, created_at=now
        )
    )
    fallback = (
        f"已生成草案，共 {len(steps)} 个工具调用。" if steps else "没有生成工具调用。"
    )
    session.add(
        ChatMessage(
            task_id=task.id,
            role="assistant",
            content=reply or fallback,
            created_at=now + timedelta(microseconds=1),
        )
    )
    await session.flush()
    return task


async def list_messages(
    session: AsyncSession, *, limit: int = 30, actor_id: UUID | None = None
) -> list[ChatMessage]:
    stmt = (
        select(ChatMessage)
        .join(Task, ChatMessage.task_id == Task.id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    )
    if actor_id is not None:
        stmt = stmt.where(Task.created_by == actor_id)
    rows = await session.execute(stmt)
    return list(reversed(rows.scalars().all()))


async def latest_draft(
    session: AsyncSession, *, actor_id: UUID | None = None
) -> Task | None:
    stmt = select(Task).where(Task.status == "draft")
    if actor_id is not None:
        stmt = stmt.where(Task.created_by == actor_id)
    return await session.scalar(stmt.order_by(Task.created_at.desc()).limit(1))


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

    product = await session.get(WorkProduct, product_id) if product_id else None
    if product_id and product is None:
        raise TaskError("产品不存在")
    if product is not None and product.status != "active":
        raise TaskError("产品已归档，不能再创建任务")

    task = Task(
        product_id=product.id if product else None,
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
    await record_event(
        session,
        event_key=f"task.created:{task.id}",
        kind="task.created",
        product_id=task.product_id,
        task_id=task.id,
        actor_id=task.created_by,
        payload={
            "title": task.title,
            "request": task.request_text,
            "tool": tool.name,
            "args": args,
        },
    )
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
    await record_event(
        session,
        event_key=f"task.approved:{task.id}",
        kind="task.approved",
        product_id=task.product_id,
        task_id=task.id,
        actor_id=actor.id if actor else None,
        payload={"title": task.title, "steps": len(await steps_for(session, task.id))},
        source="human",
    )

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
    await record_event(
        session,
        event_key=f"task.cancel_requested:{task.id}",
        kind="task.cancel_requested",
        product_id=task.product_id,
        task_id=task.id,
        actor_id=actor.id if actor else None,
        payload={"from": previous, "to": task.status},
        source="human",
    )

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
    await record_event(
        session,
        event_key=f"task.created:{new_task.id}",
        kind="task.created",
        product_id=new_task.product_id,
        task_id=new_task.id,
        actor_id=new_task.created_by,
        payload={
            "title": new_task.title,
            "request": new_task.request_text,
            "rerun_of": str(task.id),
        },
        source="human",
    )

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
    if tool is None or tool.status != "approved":
        raise TaskError("工具不存在或已停用")

    problems = validate_args((tool.manifest or {}).get("input_schema", {}), args)
    if problems:
        raise TaskError("；".join(problems))

    before = dict(step.args or {})
    step.args = args
    await session.flush()
    await record_event(
        session,
        event_key=f"human.edited_args:{step.id}:{uuid4()}",
        kind="human.edited_args",
        product_id=task.product_id,
        task_id=task.id,
        actor_id=actor.id if actor else None,
        payload={
            "step_id": str(step.id),
            "step": step.seq,
            "tool": step.tool_name,
            "before": before,
            "after": args,
        },
        source="human",
    )

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


QUEUE_STALE_AFTER = timedelta(seconds=30)


async def requeue_task(
    session: AsyncSession, task: Task, *, actor: User | None = None
) -> Task:
    """手动重入队：不改变 queued 状态，由路由负责再次 dispatch。"""

    if task.status != "queued":
        raise TaskError(f"只有 queued 任务可以重新入队，当前状态：{task.status}")

    from app.services.audit import record

    await record(
        session,
        actor=actor,
        action="task.requeue",
        target_type="task",
        target_id=str(task.id),
        detail={"title": task.title[:120], "source": "manual"},
    )
    return task


async def requeue_queued_tasks(session: AsyncSession, pool) -> int:
    """worker 启动时补齐丢失的 queued job；30 秒内的任务交给正常 dispatch。"""

    from app.services.audit import record

    cutoff = datetime.now(UTC) - QUEUE_STALE_AFTER
    rows = await session.execute(
        select(Task).where(Task.status == "queued").order_by(Task.created_at)
    )
    requeued = 0
    for task in rows.scalars().all():
        reference = task.approved_at or task.created_at
        if reference is not None and reference >= cutoff:
            continue
        await pool.enqueue_job("execute_task_task", str(task.id))
        await record(
            session,
            actor=None,
            action="task.requeue",
            target_type="task",
            target_id=str(task.id),
            detail={"title": task.title[:120], "source": "worker_startup"},
        )
        requeued += 1
    return requeued


async def claim_queued_task(session: AsyncSession, task_id: UUID) -> bool:
    """原子认领：多个重复 job 只有一个能把 queued 改成 running。"""

    result = await session.execute(
        update(Task)
        .where(Task.id == task_id, Task.status == "queued")
        .values(status="running", heartbeat_at=datetime.now(UTC))
    )
    await session.commit()
    return result.rowcount == 1


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

        for index, step in enumerate(steps):
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
            if tool is None or tool.status != "approved":
                result = {
                    "status": "error",
                    "exit_code": None,
                    "output": {},
                    "stderr": "",
                    "error": "工具不存在或已停用",
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
            await record_event(
                session,
                event_key=f"step.finished:{step.id}",
                kind="step.finished",
                product_id=task.product_id,
                task_id=task.id,
                payload={
                    "step_id": str(step.id),
                    "seq": step.seq,
                    "tool": step.tool_name,
                    "version": step.tool_version,
                    "status": step.status,
                    "exit_code": step.exit_code,
                    "args": step.args,
                    "error": step.error,
                    "stderr": (step.output or {}).get("stderr", "")[:1200],
                    "cases": (step.output or {}).get("cases", [])[:5],
                },
                source="worker",
            )

            # Agent 恢复开启时失败即停：把剩余步骤标为跳过，模型只观察已发生的失败（D166）。
            if step.status in ("failed", "error") and get_settings().agent_recovery_enabled:
                now = datetime.now(UTC)
                for later in steps[index + 1 :]:
                    if later.status == "pending":
                        later.status = "skipped"
                        later.finished_at = now
                        later.error = "前置步骤失败，未执行"
                await session.flush()
                break

        if not cancelled:
            await session.refresh(task)
            if task.status == "cancelling":
                cancelled = True

        task.status = "cancelled" if cancelled else _aggregate(statuses)
        task.finished_at = datetime.now(UTC)
        await session.flush()
        await record_event(
            session,
            event_key=f"task.finished:{task.id}",
            kind="task.finished",
            product_id=task.product_id,
            task_id=task.id,
            payload={
                "status": task.status,
                "finished_at": task.finished_at.isoformat(),
                "steps": [
                    {
                        "seq": step.seq,
                        "tool": step.tool_name,
                        "status": step.status,
                        "exit_code": step.exit_code,
                    }
                    for step in steps
                ],
            },
            source="worker",
        )
        # 先让终态可见，再调用模型；模型慢/失败不能拖住任务页面（D165）。
        await session.commit()

        try:
            await index_task_outcome(session, task, steps)
        except Exception as exc:  # noqa: BLE001 - 知识入库失败不能覆盖执行结果
            draft = dict(task.draft or {})
            draft["knowledge_error"] = exc.__class__.__name__
            task.draft = draft
            await session.flush()

        if task.status == "passed":
            try:
                from app.services.agent_recovery import mark_recovery_resolved

                await mark_recovery_resolved(session, task)
            except Exception as exc:  # noqa: BLE001 - 结算失败不能覆盖执行结果
                draft = dict(task.draft or {})
                draft["resolution_error"] = exc.__class__.__name__
                task.draft = draft
                await session.flush()

        if task.status in ("failed", "error"):
            try:
                from app.services.agent_recovery import maybe_recover_task

                await maybe_recover_task(session, task)
            except Exception as exc:  # noqa: BLE001 - 修复规划失败不能覆盖执行结果
                draft = dict(task.draft or {})
                draft["agent_recovery"] = {
                    "status": "no_plan",
                    "reply": f"修复规划异常：{exc.__class__.__name__}",
                }
                task.draft = draft
                await session.flush()
        return task
    finally:
        stop.set()
        heartbeat.cancel()


async def execute_task_by_id(task_id: UUID) -> None:
    """worker 入口：自己开一个会话，执行完提交。"""

    from app.db.session import get_sessionmaker

    async with get_sessionmaker()() as session:
        if not await claim_queued_task(session, task_id):
            return
        task = await get_task(session, task_id)
        if task is None:
            return
        await execute_task(session, task)
        await session.commit()
