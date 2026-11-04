"""工具进程执行（M4，D99）：解压 → 进程调用 → 收 stdout JSON。

契约：stdin 收 `{"args": {...}, "product": {...}}`；stdout 必须是 JSON
（含 `cases[]`）；退出码 0 = 成功；超时杀掉整个进程树。
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from app.models import Tool, WorkProduct

MAX_CAPTURE = 64 * 1024
ALLOWED_STATUSES = {"passed", "failed", "skipped", "error"}


def _kill_tree(process: asyncio.subprocess.Process) -> None:
    """超时终止整个进程树：POSIX 用进程组，Windows 用 taskkill /T。"""

    if process.pid is None:
        return
    if sys.platform.startswith("win"):
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True,
            check=False,
        )
        return
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            process.kill()
        except ProcessLookupError:
            pass


def _os_key() -> str:
    return "windows" if sys.platform.startswith("win") else "linux"


def _extract(bundle_path: str, destination: Path) -> Path:
    with tarfile.open(bundle_path, mode="r:gz") as tar:
        tar.extractall(destination, filter="data")

    # 包根目录可能多一层（打包时带上了文件夹名）
    if (destination / "tool.json").is_file():
        return destination
    for child in destination.iterdir():
        if child.is_dir() and (child / "tool.json").is_file():
            return child
    raise ValueError("工具包里找不到 tool.json")


async def run_tool(
    tool: Tool,
    *,
    args: dict,
    product: WorkProduct | None,
    task_id: str,
) -> dict:
    """执行一次工具调用，返回 {status, exit_code, output, stderr, error}。"""

    manifest = tool.manifest or {}
    entrypoints = manifest.get("entrypoint") or {}
    argv = entrypoints.get(_os_key()) or entrypoints.get("linux")
    if not argv:
        return {
            "status": "error",
            "exit_code": None,
            "output": {},
            "stderr": "",
            "error": "工具没有声明可用的 entrypoint",
        }

    timeout = float(manifest.get("timeout_seconds") or 600)
    with tempfile.TemporaryDirectory(prefix="riverat-tool-") as temp:
        root = _extract(tool.bundle_path, Path(temp))

        env = os.environ.copy()
        env["RIVERAT_TASK_ID"] = task_id
        env["RIVERAT_TOOL_NAME"] = tool.name
        if product is not None:
            env["RIVERAT_PRODUCT_CODE"] = product.code
            env["RIVERAT_PRODUCT_BASE_URL"] = product.base_url
        else:
            env["RIVERAT_PRODUCT_CODE"] = ""
            env["RIVERAT_PRODUCT_BASE_URL"] = ""

        payload = json.dumps(
            {
                "args": args,
                "product": (
                    {
                        "code": product.code,
                        "name": product.name,
                        "base_url": product.base_url,
                    }
                    if product
                    else None
                ),
            }
        ).encode()

        launch: dict = {}
        if sys.platform.startswith("win"):
            launch["creationflags"] = 0x00000200  # CREATE_NEW_PROCESS_GROUP
        else:
            launch["start_new_session"] = True

        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(root),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            **launch,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(payload), timeout=timeout
            )
        except TimeoutError:
            _kill_tree(process)
            await process.wait()
            return {
                "status": "error",
                "exit_code": None,
                "output": {},
                "stderr": "",
                "error": f"执行超时（{timeout:g}s），已终止进程树",
            }

        out_text = stdout[:MAX_CAPTURE].decode("utf-8", "replace")
        err_text = stderr[:MAX_CAPTURE].decode("utf-8", "replace")
        exit_code = process.returncode

        if exit_code != 0:
            return {
                "status": "failed",
                "exit_code": exit_code,
                "output": {"stdout": out_text[:2000]},
                "stderr": err_text,
                "error": f"退出码 {exit_code}",
            }

        try:
            output = json.loads(out_text) if out_text.strip() else {}
        except json.JSONDecodeError:
            return {
                "status": "error",
                "exit_code": exit_code,
                "output": {"stdout": out_text[:2000]},
                "stderr": err_text,
                "error": "stdout 不是合法 JSON（工具契约要求返回 JSON）",
            }

        if not isinstance(output, dict):
            return {
                "status": "error",
                "exit_code": exit_code,
                "output": {"stdout": out_text[:2000]},
                "stderr": err_text,
                "error": "stdout 必须是 JSON 对象",
            }

        declared = output.get("status")
        status = declared if declared in ALLOWED_STATUSES else "passed"
        return {
            "status": status,
            "exit_code": exit_code,
            "output": output,
            "stderr": err_text,
            "error": (output.get("reason") if status != "passed" else None),
        }
