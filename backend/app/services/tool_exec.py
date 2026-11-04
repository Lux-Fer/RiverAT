"""工具进程执行（M4/D99，D112）：解压到持久目录 → 首次依赖安装 → 进程调用。

契约：stdin 收 `{"args": {...}, "product": {...}}`；stdout 必须是 JSON
（含 `cases[]`）；退出码 0 = 成功；超时杀掉整个进程树。

工具目录持久化在 `backend/var/tools/work/<sha256>/`：
* 同一份包只解压一次；
* `runtime.setup` 只在首次（成功后写 `.riverat-setup-done`）执行；
* 平台不清理该目录，清理方法见 `docs/tool-contract.md`。
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import tarfile
from pathlib import Path

from app.core.config import get_settings
from app.models import Tool, WorkProduct

MAX_CAPTURE = 64 * 1024
ALLOWED_STATUSES = {"passed", "failed", "skipped", "error"}
SETUP_MARKER = ".riverat-setup-done"

_install_locks: dict[str, asyncio.Lock] = {}


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


def _launch_kwargs() -> dict:
    if sys.platform.startswith("win"):
        return {"creationflags": 0x00000200}  # CREATE_NEW_PROCESS_GROUP
    return {"start_new_session": True}


def _workdir(sha256: str) -> Path:
    return get_settings().tools_root / "work" / sha256


def _find_root(base: Path) -> Path:
    if (base / "tool.json").is_file():
        return base
    for child in base.iterdir():
        if child.is_dir() and (child / "tool.json").is_file():
            return child
    raise ValueError("工具包里找不到 tool.json")


def _extract(bundle_path: str, destination: Path) -> Path:
    with tarfile.open(bundle_path, mode="r:gz") as tar:
        tar.extractall(destination, filter="data")
    return _find_root(destination)


def _base_env(tool: Tool, product: WorkProduct | None, task_id: str) -> dict:
    env = os.environ.copy()
    env["RIVERAT_TASK_ID"] = task_id
    env["RIVERAT_TOOL_NAME"] = tool.name
    env["RIVERAT_PRODUCT_CODE"] = product.code if product else ""
    env["RIVERAT_PRODUCT_BASE_URL"] = product.base_url if product else ""
    return env


def _error(message: str, stderr: str = "") -> dict:
    return {
        "status": "error",
        "exit_code": None,
        "output": {},
        "stderr": stderr,
        "error": message,
    }


async def _run_setup(
    argv: list[str],
    root: Path,
    *,
    timeout: float,
    env: dict,
) -> dict | None:
    """执行一次依赖安装；成功返回 None，失败返回错误结果。"""

    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        **_launch_kwargs(),
    )
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        _kill_tree(process)
        await process.wait()
        return _error(f"依赖安装超时（{timeout:g}s），已终止进程树")

    err_text = stderr[:MAX_CAPTURE].decode("utf-8", "replace")
    if process.returncode != 0:
        tail = err_text.strip()[-300:] or "无 stderr"
        return _error(
            f"依赖安装失败（退出码 {process.returncode}）：{tail}", err_text
        )
    return None


async def prepare_tool(
    tool: Tool, product: WorkProduct | None = None, task_id: str = ""
) -> tuple[Path | None, dict | None]:
    """解压并安装依赖（每份包一次），返回 (根目录, 错误结果)。"""

    sha = tool.bundle_sha256
    workdir = _workdir(sha)
    lock = _install_locks.setdefault(sha, asyncio.Lock())

    async with lock:
        try:
            if (workdir / "tool.json").is_file():
                root = workdir
            else:
                workdir.mkdir(parents=True, exist_ok=True)
                root = _extract(tool.bundle_path, workdir)
        except Exception as exc:  # noqa: BLE001 - 坏包不能卡住任务
            shutil.rmtree(workdir, ignore_errors=True)
            return None, _error(f"工具包解压失败：{exc}")

        manifest = tool.manifest or {}
        runtime = manifest.get("runtime") or {}
        setup = runtime.get("setup")
        marker = root / SETUP_MARKER
        if setup and not marker.exists():
            timeout = float(runtime.get("setup_timeout_seconds") or 300)
            failure = await _run_setup(
                [str(part) for part in setup],
                root,
                timeout=timeout,
                env=_base_env(tool, product, task_id),
            )
            if failure is not None:
                return root, failure
            marker.write_text("ok", encoding="utf-8")

    return root, None


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
        return _error("工具没有声明可用的 entrypoint")

    root, failure = await prepare_tool(tool, product, task_id)
    if failure is not None:
        return failure
    if root is None:
        return _error("工具目录准备失败")

    timeout = float(manifest.get("timeout_seconds") or 600)
    env = _base_env(tool, product, task_id)
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

    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(root),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        **_launch_kwargs(),
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(payload), timeout=timeout
        )
    except TimeoutError:
        _kill_tree(process)
        await process.wait()
        return _error(f"执行超时（{timeout:g}s），已终止进程树")

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
