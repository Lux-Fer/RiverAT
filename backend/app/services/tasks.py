"""v1.1 任务草案（M3，D95）：把一句话需求变成可确认的工具调用草案。

平台只做三件事：把已审核工具转成 function schema、调用模型、校验参数。
**不执行任何工具**（执行在 M4）。
"""

from __future__ import annotations

import json
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
