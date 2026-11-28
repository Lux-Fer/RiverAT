from openai import OpenAI
from tools import tools
import os, sys, json
from permissions import PermissionManager
from tools.tools import execute
from context import (truncate_tool_result, clear_old_tool_result, compact, save_session, load_session)
import skills

client = OpenAI(
    api_key="sk-b97d83a1b16247278b967ddf3db4b154",
    base_url="https://api.deepseek.com"
)

SOFT_LIMIT = 16000
HARD_LIMIT = 24000

SYSTEM = (
    "你是我的测试交付助手，你叫RiverAT。"
    "需要时调用工具，完成任务后直接用文字总结，不要再调用工具。"
)
MODEL = "deepseek-flash"
MAX_STEPS = 20
BASE_SYSTEM = (
    "你是一个能使用工具的助手，在用户的工作区内完成任务。"
    "必要时调用工具，完成后用简洁的语言汇报结果。"
)

usage = {"prompt_tokens": 0}

def handle_call(call, perms):
    name = call.function.name
    try:
        args = json.loads(call.function.arguments or "{}")
    except json.JSONDecodeError:
        return "Error: 参数不是合法的 JSON"
    decision = perms.check(name, args)
    if not decision.allowed:
        return f"[权限拒绝] {decision.reason}"
    return execute(name, args)

def build_system():
    return BASE_SYSTEM + skills.project_notes() + skills.skills_section()

def run(user_input, messages, perms):
    messages.append({"role": "user", "content": user_input})

    for _ in range(MAX_STEPS):
        if usage["prompt_tokens"] > HARD_LIMIT:
            messages[:] = compact(client, MODEL, messages)
        elif usage["prompt_tokens"] > SOFT_LIMIT:
            clear_old_tool_result(messages)
        response = client.chat.completions.create(model=MODEL, messages=messages, tools=tools.get_schemas())
        usage["prompt_tokens"] = response.usage.prompt_tokens if response.usage else 0
        print(f"   [prompt_tokens={usage['prompt_tokens']}]")
        msg = response.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            return msg.content or ""
        
        for call in msg.tool_calls:
            print(f"🔧 {call.function.name}({call.function.arguments[:80]})")
            result = handle_call(call, perms)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": truncate_tool_result(result)})
    
    print(f"\n[达到 {MAX_STEPS} 步上限，已停止]")

def main():
    messages = load_session("default") or [{"role": "system", "content": ""}]
    messages[0] = {"role": "system", "content": build_system()}
    
    perms = PermissionManager()
    while True:
        q = input("你> ").strip()
        if q in ("exit", "quit"):
            break
        print("\n" + run(q, messages, perms) + "\n")
        save_session("default", messages)

if __name__ == "__main__":
    main()