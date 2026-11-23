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

def run(task: str) -> None:
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": task}
    ]

    for step in range(1, MAX_STEPS+1):
        response = client.chat.completions.create(model=MODEL, messages=messages, tools=tools.TOOLS)
        msg = response.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            print(f"\n[完成，共 {step} 步]\n{msg.content}")
            return
        
        for call in msg.tool_calls:
            name = call.function.name
            print(f"[第 {step} 步] {name}({call.function.arguments[:80]})")

            try:
                args = json.loads(call.function.arguments)
                result = tools.TOOL_FUNCS[name](**args)
            except Exception as e:
                result = f"工具执行出错：{type(e).__name__}: {e}"
            
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
    
    print(f"\n[达到 {MAX_STEPS} 步上限，已停止]")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit('用法：python main.py "你的任务"')
    
    run(sys.argv[1])
