import json, os, subprocess
import urllib.request
from pathlib import Path
from tools.permissions import WORKSPACE, resolve_in_workspace

MAX_OUTPUT = 8000
TOOLS = {}


def tool(name, description, parameters):
    def decorator(func):
        TOOLS[name] = {
            "schema": {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters
                },
            },
            "func": func
        }
        return func
    return decorator

def get_schemas():
    return [t["schema"] for t in TOOLS.values()]

def _params(**props):
    return {
        "type": "object",
        "properties": {k: {"type": "string", "description": v} for k, v in props.items()},
        "required": list(props)
    }

@tool("list_dir", "列出某个目录下的文件和子目录", _params(path="目录路径，当前目录写."))
def list_dir(path="."):
    p = resolve_in_workspace(path)
    if p is None:
        return "[错误] 路径在工作区外！"
    return "\n".join(sorted(x.name + ("/" if x.is_dir() else "") for x in p.iterdir())) or "(空目录)"

@tool("read_files", "读取一个文本文件的内容。", _params(path="文件路径"))
def read_files(path: str) -> str:
    p = resolve_in_workspace(path)
    if p is None:
        return "[错误] 路径在工作区外！"
    return p.read_text(encoding="utf-8")


@tool("write_files", "把内容写入文件，已存在则覆盖，目录不存在会自动创建。", _params(path="文件路径", content="要写入的完整内容"))
def write_files(path, content):
    p = resolve_in_workspace(path)
    if p is None:
        return "[错误] 路径在工作区外！"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"已写入 {path}（{len(content)} 字符）"

def edit_files(path, old, new):
    return None

@tool("run_shell", "在当前目录执行一条 shell 命令，返回退出码、标准输出和错误输出。", _params(command="要执行的命令"))
def run_shell(command: str, timeout=30) -> str:
    try:
        p = subprocess.run(command, shell=True, cwd=WORKSPACE, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return f"[超时] 命令执行超过 {timeout} 秒，已终止。"
    return f"[exit {p.returncode}]\n{p.stdout}{p.stderr}"

@tool("fetch_url", "抓取一个网页或接口的文本内容。url 必须以 http 或 https 开头。", _params(url="完整的URL"))
def fetch_url(url):
    req = urllib.request.Request(url, headers={"User-Agent": "RiverAT"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")


def execute(name, args):
    if name not in TOOLS:
        return f"Error: 不存在工具 '{name}'，可用工具：{', '.join(TOOLS)}"
    try:
        result = str(TOOLS[name]["func"](**args))
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"
    if len(result) > MAX_OUTPUT:
        result = result[:MAX_OUTPUT] + f"\n...（已截断，共 {len(result)} 字符）"
    return result

