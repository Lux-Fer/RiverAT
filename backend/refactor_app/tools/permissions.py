from __future__ import annotations

import os, re, sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from textwrap import indent

WORKSPACE = Path(os.environ.get("RIVERAT_WORKSPACE", os.getcwd())).resolve()

class Risk(Enum):
    SAFE = "safe"
    CONFIRM = "confirm"
    DENY = "deny"

TOOL_RISK = {
    "list_dir": Risk.SAFE,
    "read_files": Risk.SAFE,
    "write_files": Risk.CONFIRM,
    "run_shell": Risk.CONFIRM,
    "fetch_url": Risk.CONFIRM
}

REMEMBERABLE = {"write_files"}

SHELL_DENY_PATTERNS = [
    r"\brm\s+(-[a-zA-Z]*[rf][a-zA-Z]*\s+)+(/|~|\*)",  # rm -rf / ~ *
    r"\bsudo\b",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r":\(\)\s*\{",                                    # fork bomb
    r"(curl|wget)\b.*\|\s*(sh|bash)\b",               # curl ... | sh
    r">\s*/dev/sd",
]

def resolve_in_workspace(path_str: str) -> Path | None:
    p = Path(path_str).expanduser()
    if not p.is_absolute():
        p = WORKSPACE / p
    p = p.resolve()
    return p if p.is_relative_to(WORKSPACE) else None

@dataclass
class Decision:
    allowed: bool
    reason: str = ""

def render_call(name: str, args: dict, max_chars: int = 400) -> str:
    if name == "run_shell":
        return f" $ {args.get('command', '')}"
    if name == "write_files":
        content = args.get("content", "")
        preview = content[:max_chars]
        if len(content) > max_chars:
            preview += f"\n...（已截断，共{len(content)}字符）"
        return f" 路径：{args.get('path')}\n" + indent(preview, "   ")
    return f" {args}"

class PermissionManager:
    def __init__(self, ask=None):
        self.always_allowed:set[str] = set()
        self.ask = ask or self._ask_terminal

    def check(self, name: str, args: dict) -> Decision:
        reason = self._hard_limits(name, args)
        if reason:
            return Decision(False, reason)
        
        risk = TOOL_RISK.get(name, Risk.CONFIRM)
        if risk is Risk.DENY:
            return Decision(False, f"工具{name}被策略禁用。")
        if risk is Risk.SAFE or name in self.always_allowed:
            return Decision(True)
        
        return self._confirm(name, args)
    
    def _hard_limits(self, name: str, args: dict) -> str | None:
        if name in ("read_files", "write_files", "list_dir"):
            path = args.get("path", ".")
            if resolve_in_workspace(path) is None:
                return f"路径 {path!r}在工作区{WORKSPACE}之外，禁止访问。"
        if name == "run_shell":
            cmd = args.get("command", "")
            for pat in SHELL_DENY_PATTERNS:
                if re.search(pat, cmd):
                    return f"命令命中危险模式，已被策略拦截：{cmd!r}"
        return None

    def _confirm(self, name: str, args:dict) -> Decision:
        answer, note = self.ask(name, args)
        if answer == "a" and name in REMEMBERABLE:
            self.always_allowed.add(name)
            return Decision(True)
        if answer in ("y", "a"):
            return Decision(True)
        msg = "用户拒绝了这次操作。"
        if note:
            msg += f"原因：{note}。"
        msg += "不要重试同一操作；请换一种方式，或向用户说明你想做什么、为什么。"
        return Decision(False, msg)
    
    @staticmethod
    def _ask_terminal(name: str, args: dict):
        if not sys.stdin.isatty():
            return "n", "当前是非交互环境，无法确认"
        print(f"\n⚠️  Agent 想执行：{name}")
        print(render_call(name, args))
        options = "[y]允许 / [n]拒绝" + (" / [a]本次会话一直允许" if name in REMEMBERABLE else "")
        while True:
            ans = input(f"{options} > ").strip().lower()
            if ans in ("y", "n") or (ans == "a" and name in REMEMBERABLE):
                break
        note = input("拒绝原因（可选，回车跳过）> ").strip() if ans == "n" else ""
        return ans, note