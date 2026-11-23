import json, os, subprocess

def read_files(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()

def write_files(path: str, content: str) -> str:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"已写入{len(content)}字符到{path}中！"

def run_shell(command: str) -> str:
    if input(f"\n[需要确认] 执行命令：{command}\n允许？(y/n) ").strip().lower() != "y":
        return "用户拒绝执行命令！"
    try:
        p = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return "命令超时（60s）!"
    return (p.stdout + p.stderr)[-4000:] or "（无输出）"

TOOL_FUNCS = {"read_files": read_files, "write_files": write_files, "run_shell": run_shell}

def _tool(name, desc, props):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {
                "type": "object",
                "properties": {k: {"type": "string", "description": v} for k, v in props.items()},
                "required": list(props)
            },
        },
    }

TOOLS = [
    _tool("read_files", "读取文件内容", {"path": "文件路径"}),
    _tool("write_files", "写入文件（覆盖）", {"path": "文件路径", "content": "完整文件内容"}),
    _tool("run_shell", "执行shell命令并返回输出", {"command": "要执行的命令"}),
]