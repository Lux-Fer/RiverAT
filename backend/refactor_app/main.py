from openai import OpenAI
from tools import tools
import os
import sys
import json

client = OpenAI(
    api_key="sk-b97d83a1b16247278b967ddf3db4b154",
    base_url="https://api.deepseek.com"
)

SYSTEM = (
    "你是我的测试交付助手，你叫RiverAT。"
    "需要时调用工具，完成任务后直接用文字总结，不要再调用工具。"
)
MODEL = "deepseek-flash"
MAX_STEPS = 20

def run(user_input, messages):
    messages.append({"role": "user", "content": user_input})

    for step in range(1, MAX_STEPS+1):
        response = client.chat.completions.create(model=MODEL, messages=messages, tools=tools.get_schemas())
        msg = response.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            return msg.content or ""
        
        for call in msg.tool_calls:
            name = call.function.name

            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                result = "Error: 参数不是合法的 JSON"
            else:
                print(f"🔧 {name}({call.function.arguments[:80]})")
                result = tools.execute(name, args)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
    
    print(f"\n[达到 {MAX_STEPS} 步上限，已停止]")

if __name__ == "__main__":
    messages = [{"role": "user", "content": SYSTEM}]

    while True:
        q = input("你> ").strip()
        if q in ("exit", "quit"):
            break
        print("\n" + run(q, messages) + "\n")