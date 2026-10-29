"""Runner 端到端：插件包 → 目标机执行 → 证据回收。

与 transport 测试共用夹具，因此 local 与真实 sshd 跑的是同一套断言。
"""

from __future__ import annotations

import shlex

from app.runner.executor import StepStatus, run_step
from tests.plugins import make_plugin


def test_step_passes_and_captures_stdout(transport, workdir, tmp_path):
    bundle = make_plugin(
        tmp_path,
        "passer",
        'echo "hello from plugin"\n',
        'Write-Output "hello from plugin"\n',
    )

    outcome = run_step(
        transport, bundle, workdir=workdir, step={"step_id": "pass-1"}, timeout=30
    )

    assert outcome.status is StepStatus.PASSED
    assert outcome.exit_code == 0
    assert "hello from plugin" in outcome.stdout.decode("utf-8", "replace")
    assert len(outcome.bundle_sha256) == 64


def test_step_failure_keeps_exit_code_and_stderr(transport, workdir, tmp_path):
    bundle = make_plugin(
        tmp_path,
        "failer",
        'echo "boom" >&2\nexit 7\n',
        '[Console]::Error.WriteLine("boom")\nexit 7\n',
    )

    outcome = run_step(
        transport, bundle, workdir=workdir, step={"step_id": "fail-1"}, timeout=30
    )

    assert outcome.status is StepStatus.FAILED
    assert outcome.exit_code == 7
    assert "boom" in outcome.stderr.decode("utf-8", "replace")


def test_step_can_declare_skipped(transport, workdir, tmp_path):
    bundle = make_plugin(
        tmp_path,
        "skipper",
        "printf '%s' '{\"status\":\"skipped\",\"reason\":\"no device\"}' > plugin_result.json\n",
        "Set-Content -Path plugin_result.json -NoNewline "
        "-Value '{\"status\":\"skipped\",\"reason\":\"no device\"}'\n",
    )

    outcome = run_step(
        transport, bundle, workdir=workdir, step={"step_id": "skip-1"}, timeout=30
    )

    assert outcome.status is StepStatus.SKIPPED
    assert outcome.reason == "no device"


def test_step_timeout_becomes_error(transport, workdir, tmp_path):
    bundle = make_plugin(
        tmp_path,
        "sleeper",
        "sleep 30\n",
        "Start-Sleep -Seconds 30\n",
    )

    outcome = run_step(
        transport, bundle, workdir=workdir, step={"step_id": "timeout-1"}, timeout=2
    )

    assert outcome.status is StepStatus.ERROR
    assert outcome.timed_out is True
    assert outcome.reason == "timeout"
    assert outcome.duration_ms < 10_000


def test_step_collects_artifacts(transport, workdir, tmp_path):
    bundle = make_plugin(
        tmp_path,
        "artist",
        'mkdir -p artifacts\necho ok > artifacts/result.txt\n',
        'New-Item -ItemType Directory -Force artifacts | Out-Null\n'
        "Set-Content -Path artifacts/result.txt -Value 'ok'\n",
    )

    outcome = run_step(
        transport, bundle, workdir=workdir, step={"step_id": "art-1"}, timeout=30
    )

    assert outcome.status is StepStatus.PASSED
    assert outcome.artifacts["result.txt"].decode("utf-8", "replace").strip() == "ok"


def test_remote_workdir_is_cleaned(transport, target_os, workdir, tmp_path):
    bundle = make_plugin(
        tmp_path, "cleaner", 'echo "done"\n', 'Write-Output "done"\n'
    )

    outcome = run_step(
        transport, bundle, workdir=workdir, step={"step_id": "clean-1"}, timeout=30
    )
    assert outcome.status is StepStatus.PASSED

    if target_os == "windows":
        check = transport.exec(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"Test-Path -LiteralPath '{outcome.remote_workdir}'",
            ]
        )
        assert check.stdout_text.strip().lower() == "false"
    else:
        check = transport.exec(
            ["sh", "-c", f"test -e {shlex.quote(outcome.remote_workdir)}; echo $?"]
        )
        assert check.stdout_text.strip() == "1"
