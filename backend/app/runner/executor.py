"""在目标机上执行一个测试步骤（一个插件实例）。

对应 D12 的四段生命周期，把它们落到一次远程执行里：

1. **prepare** —— 打包插件目录，生成 job.json 与引导脚本，上传到独立工作目录
2. **execute** —— transport 执行入口命令；超时由 transport 负责真的杀掉进程树
3. **collect** —— 回收 stdout/stderr、``plugin_result.json``、``artifacts/``
4. **cleanup** —— 删除远端工作目录（可保留用于排障）

平台不判断用例优劣：插件写 ``plugin_result.json`` 就采信它的 status，
没写就按退出码归类（0 → passed，非 0 → failed）。超时和传输故障归 ``error``。
"""

from __future__ import annotations

import json
import shlex
import tempfile
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from app.runner.bundle import pack_bundle
from app.runner.manifest import PluginManifest, load_manifest
from app.transport.base import ConnectError, Transport, TransportError

_JOB_FILE = "job.json"
_BUNDLE_FILE = "bundle.tar.gz"


class StepStatus(str, Enum):
    """run_step 的终态；blocked 由编排层判定，runner 不产生。"""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class StepOutcome:
    status: StepStatus
    exit_code: int
    duration_ms: int
    timed_out: bool
    stdout: bytes
    stderr: bytes
    artifacts: dict[str, bytes] = field(default_factory=dict)
    reason: str = ""
    bundle_sha256: str = ""
    remote_workdir: str = ""
    truncated: bool = False


def run_step(
    transport: Transport,
    bundle_dir: Path,
    *,
    workdir: str,
    step: dict[str, Any] | None = None,
    timeout: float | None = None,
    keep_remote: bool = False,
) -> StepOutcome:
    manifest = load_manifest(bundle_dir)
    bundle_bytes, digest = pack_bundle(bundle_dir)
    target = transport.probe()
    entrypoint = manifest.entrypoint_for(target.os)
    effective_timeout = float(timeout or manifest.timeout_seconds)

    step_payload = dict(step or {})
    step_id = str(step_payload.get("step_id") or uuid.uuid4().hex[:12])
    remote = f"{workdir}/step-{step_id}"
    is_windows = target.os == "windows"

    with tempfile.TemporaryDirectory(prefix="riverat-step-") as tmp_name:
        tmp = Path(tmp_name)
        script_name = "run.ps1" if is_windows else "run.sh"
        script_text = (
            _powershell_script(entrypoint) if is_windows else _shell_script(entrypoint)
        )

        (tmp / _BUNDLE_FILE).write_bytes(bundle_bytes)
        (tmp / _JOB_FILE).write_text(
            json.dumps(step_payload, ensure_ascii=False), encoding="utf-8"
        )
        (tmp / script_name).write_bytes(script_text.encode("utf-8"))

        try:
            transport.put(tmp / _BUNDLE_FILE, f"{remote}/{_BUNDLE_FILE}")
            transport.put(tmp / _JOB_FILE, f"{remote}/{_JOB_FILE}")
            transport.put(tmp / script_name, f"{remote}/{script_name}")

            if is_windows:
                argv = [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    script_name,
                ]
            else:
                argv = ["sh", script_name]

            result = transport.exec(argv, cwd=remote, timeout=effective_timeout)
        except ConnectError:
            raise
        except TransportError as exc:
            return StepOutcome(
                status=StepStatus.ERROR,
                exit_code=-1,
                duration_ms=0,
                timed_out=False,
                stdout=b"",
                stderr=str(exc).encode("utf-8", "replace"),
                reason=f"transport: {exc}",
                bundle_sha256=digest,
                remote_workdir=remote,
            )

        artifacts: dict[str, bytes] = {}
        stdout = _fetch(transport, tmp, remote, "result/stdout.log") or result.stdout
        stderr = _fetch(transport, tmp, remote, "result/stderr.log") or result.stderr
        plugin_result = _read_plugin_result(transport, tmp, remote)

        listing = _fetch(transport, tmp, remote, "result/artifacts.txt")
        if listing:
            for name in listing.decode("utf-8", "replace").splitlines():
                name = name.strip()
                if not name or "/" in name or "\\" in name or ".." in name:
                    continue
                payload = _fetch(transport, tmp, remote, f"app/artifacts/{name}")
                if payload is not None:
                    artifacts[name] = payload

        status, reason = _classify(result.exit_code, result.timed_out, plugin_result)

        if not keep_remote:
            _cleanup(transport, remote, is_windows)

        return StepOutcome(
            status=status,
            exit_code=-1 if result.timed_out else result.exit_code,
            duration_ms=result.duration_ms,
            timed_out=result.timed_out,
            stdout=stdout,
            stderr=stderr,
            artifacts=artifacts,
            reason=reason,
            bundle_sha256=digest,
            remote_workdir=remote,
            truncated=result.truncated,
        )


# -- 结果归类 ---------------------------------------------------------


def _classify(
    exit_code: int,
    timed_out: bool,
    plugin_result: dict[str, Any] | None,
) -> tuple[StepStatus, str]:
    if timed_out:
        return StepStatus.ERROR, "timeout"

    if plugin_result:
        declared = str(plugin_result.get("status", "")).lower()
        if declared in {s.value for s in StepStatus}:
            return StepStatus(declared), str(plugin_result.get("reason", ""))

    if exit_code == 0:
        return StepStatus.PASSED, ""
    return StepStatus.FAILED, f"exit code {exit_code}"


# -- 目标机侧脚本 -----------------------------------------------------


def _shell_script(entrypoint: list[str]) -> str:
    command = " ".join(shlex.quote(part) for part in [*entrypoint, f"../{_JOB_FILE}"])
    return "\n".join(
        [
            "#!/bin/sh",
            "set -u",
            "mkdir -p app result",
            f"tar -xzf {_BUNDLE_FILE} -C app || {{ echo 'bundle extract failed' >&2; exit 91; }}",
            "cd app || exit 92",
            "set +e",
            f"{command} > ../result/stdout.log 2> ../result/stderr.log",
            "rc=$?",
            "set -e",
            "cd ..",
            "if [ -d app/artifacts ]; then ls -1 app/artifacts > result/artifacts.txt 2>/dev/null || true; fi",
            "exit $rc",
            "",
        ]
    )


def _powershell_script(entrypoint: list[str]) -> str:
    executable = entrypoint[0]
    arguments = [*entrypoint[1:], f"../{_JOB_FILE}"]
    argument_literal = ",".join(_ps_quote(arg) for arg in arguments)
    return "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            "$root = (Get-Location).Path",
            "New-Item -ItemType Directory -Force (Join-Path $root 'app'), "
            + "(Join-Path $root 'result') | Out-Null",
            f"tar -xzf {_BUNDLE_FILE} -C (Join-Path $root 'app')",
            "if ($LASTEXITCODE -ne 0) { exit 91 }",
            f"$exe = {_ps_quote(executable)}",
            f"$pluginArgs = @({argument_literal})",
            "$stdout = Join-Path $root 'result/stdout.log'",
            "$stderr = Join-Path $root 'result/stderr.log'",
            "$p = Start-Process -FilePath $exe -ArgumentList $pluginArgs -NoNewWindow "
            + "-Wait -PassThru -WorkingDirectory (Join-Path $root 'app') "
            + "-RedirectStandardOutput $stdout -RedirectStandardError $stderr",
            "if (Test-Path (Join-Path $root 'app/artifacts')) { "
            + "Get-ChildItem (Join-Path $root 'app/artifacts') -File | "
            + "ForEach-Object { $_.Name } | "
            + "Set-Content (Join-Path $root 'result/artifacts.txt') }",
            "exit $p.ExitCode",
            "",
        ]
    )


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _cleanup(transport: Transport, remote: str, is_windows: bool) -> None:
    try:
        if is_windows:
            transport.exec(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"Remove-Item -LiteralPath '{remote}' -Recurse -Force -ErrorAction SilentlyContinue",
                ],
                timeout=30,
            )
        else:
            transport.exec(["sh", "-c", f"rm -rf {shlex.quote(remote)}"], timeout=30)
    except TransportError:
        pass


# -- 回收 -------------------------------------------------------------


def _fetch(transport: Transport, tmp: Path, remote: str, relative: str) -> bytes | None:
    destination = tmp / ("fetched_" + relative.replace("/", "_"))
    try:
        transport.get(f"{remote}/{relative}", destination)
    except TransportError:
        return None
    return destination.read_bytes()


def _read_plugin_result(
    transport: Transport, tmp: Path, remote: str
) -> dict[str, Any] | None:
    raw = _fetch(transport, tmp, remote, "app/plugin_result.json")
    if not raw:
        return None
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def validate_manifest(bundle_dir: Path) -> PluginManifest:
    """给上层做"插件能不能在这台机器上跑"的预检。"""

    return load_manifest(bundle_dir)
