"""Transport 一致性测试（契约测试）。

每一个实现（local / ssh / 将来的 winrm）都要跑这套断言。
本地模拟是否"准确"，由这里定义；是否"权威"，由同一套断言在真实
目标上同样通过来证明。
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from app.transport.base import ConnectError, TransferError, TransportError
from app.transport.ssh import SshTransport


def run_shell(transport, target_os: str, ps_shell: str, script: str, **kwargs):
    """在目标机上跑一段 shell 脚本（Windows 用 PowerShell）。"""

    if target_os == "windows":
        return transport.exec(
            [ps_shell, "-NoProfile", "-NonInteractive", "-Command", script], **kwargs
        )
    return transport.exec(["sh", "-c", script], **kwargs)


# -- 基础契约 ---------------------------------------------------------


def test_probe_reports_identity(transport):
    info = transport.probe()
    assert info.os in {"linux", "windows", "darwin"}, info
    assert info.hostname, "hostname 不能为空"
    assert info.arch, "arch 不能为空"


def test_exec_success_returns_stdout(transport, target_os, ps_shell):
    result = run_shell(transport, target_os, ps_shell, "echo riverat-contract")

    assert result.exit_code == 0
    assert result.timed_out is False
    assert "riverat-contract" in result.stdout_text
    assert result.duration_ms >= 0


def test_nonzero_exit_is_data_not_exception(transport, target_os, ps_shell):
    result = run_shell(transport, target_os, ps_shell, "exit 3")

    assert result.exit_code == 3, "非零退出码必须原样返回"
    assert result.timed_out is False


def test_missing_command_returns_error(transport):
    result = transport.exec(["riverat-nonexistent-command"])

    assert result.exit_code != 0
    assert result.stderr_text.strip(), "命令不存在时必须有错误输出"


def test_stderr_is_separate_from_stdout(transport, target_os, ps_shell):
    if target_os == "windows":
        script = "[Console]::Error.WriteLine('err-line'); Write-Output 'out-line'"
    else:
        script = "echo out-line; echo err-line >&2"

    result = run_shell(transport, target_os, ps_shell, script)

    assert "out-line" in result.stdout_text
    assert "err-line" not in result.stdout_text
    assert "err-line" in result.stderr_text


# -- 执行上下文 -------------------------------------------------------


def test_cwd_is_applied(transport, target_os, ps_shell, workdir):
    if target_os == "windows":
        result = transport.exec(
            [ps_shell, "-NoProfile", "-Command", "(Get-Location).Path"], cwd=workdir
        )
    else:
        result = transport.exec(["pwd"], cwd=workdir)

    assert result.exit_code == 0
    assert Path(result.stdout_text.strip()).resolve() == Path(workdir).resolve()


def test_env_is_passed(transport, target_os, ps_shell):
    if target_os == "windows":
        result = transport.exec(
            [ps_shell, "-NoProfile", "-Command", "$env:RIVERAT_CONTRACT"],
            env={"RIVERAT_CONTRACT": "value-42"},
        )
    else:
        result = transport.exec(
            ["sh", "-c", 'printf %s "$RIVERAT_CONTRACT"'],
            env={"RIVERAT_CONTRACT": "value-42"},
        )

    assert result.stdout_text.strip() == "value-42"


def test_stdin_is_forwarded(transport, target_os, ps_shell):
    payload = b"hello-stdin"
    if target_os == "windows":
        result = transport.exec(
            [ps_shell, "-NoProfile", "-Command", "[Console]::In.ReadToEnd()"],
            stdin=payload,
        )
    else:
        result = transport.exec(["cat"], stdin=payload)

    assert result.stdout_text.strip() == payload.decode()


def test_unicode_survives_roundtrip(transport, target_os, ps_shell):
    text = "中文-é-✓"
    if target_os == "windows":
        result = transport.exec(
            [ps_shell, "-NoProfile", "-Command", f"Write-Output '{text}'"]
        )
    else:
        result = transport.exec(["sh", "-c", f"printf %s '{text}'"])

    assert text in result.stdout_text


def test_large_output_does_not_deadlock(transport, target_os, ps_shell):
    size = 200_000
    if target_os == "windows":
        result = transport.exec(
            [
                ps_shell,
                "-NoProfile",
                "-Command",
                f"[Console]::Out.Write('x' * {size})",
            ],
            timeout=120,
        )
    else:
        result = transport.exec(["sh", "-c", f"yes x | head -c {size}"], timeout=120)

    assert result.exit_code == 0
    assert len(result.stdout) == size


def test_timeout_is_reported_not_raised(transport, target_os, ps_shell):
    if target_os == "windows":
        result = transport.exec(
            [ps_shell, "-NoProfile", "-Command", "Start-Sleep -Seconds 10"], timeout=1.5
        )
    else:
        result = transport.exec(["sleep", "10"], timeout=1.5)

    assert result.timed_out is True
    assert result.exit_code == -1
    assert result.duration_ms < 8_000, "超时后应立即返回，而不是等进程自己结束"


# -- 文件传输 ---------------------------------------------------------


def test_file_roundtrip_creates_parents(transport, workdir, tmp_path):
    payload = os.urandom(256 * 1024)
    source = tmp_path / "payload.bin"
    source.write_bytes(payload)

    remote = f"{workdir}/nested/dir/payload.bin"
    transport.put(source, remote)

    restored = tmp_path / "restored.bin"
    transport.get(remote, restored)

    assert hashlib.sha256(restored.read_bytes()).digest() == hashlib.sha256(
        payload
    ).digest()


def test_put_missing_local_file_raises(transport, workdir):
    with pytest.raises((TransferError, TransportError)):
        transport.put(Path(workdir) / "does-not-exist.bin", f"{workdir}/x.bin")


# -- 连接失败 ---------------------------------------------------------


def test_ssh_connect_error_is_typed():
    transport = SshTransport(
        host="127.0.0.1", username="nobody", port=1, connect_timeout=1.0
    )
    with pytest.raises(ConnectError):
        transport.probe()
