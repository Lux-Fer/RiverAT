"""示例工具 text_doc_check 的本地契约测试（不依赖 RiverAT 服务）。"""

from __future__ import annotations

import json
import subprocess
import sys

from app.core.config import BASE_DIR

TOOL = BASE_DIR.parent / "tools" / "text-doc-check" / "main.py"


def _run(args: dict) -> dict:
    result = subprocess.run(
        [sys.executable, str(TOOL)],
        input=json.dumps({"args": args}, ensure_ascii=False),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_text_doc_tool_passes_valid_document(tmp_path):
    doc = tmp_path / "sample.txt"
    doc.write_text("RiverAT 本地文档验收\n中文内容\n", encoding="utf-8")

    output = _run({"path": str(doc), "contains": "RiverAT", "encoding": "utf-8"})

    assert output["status"] == "passed"
    assert [case["case_id"] for case in output["cases"]] == [
        "doc-exists",
        "doc-size",
        "doc-encoding",
        "doc-min-chars",
        "doc-contains",
    ]
    assert all(case["status"] == "passed" for case in output["cases"])


def test_text_doc_tool_reports_missing_file(tmp_path):
    output = _run({"path": str(tmp_path / "missing.txt")})

    assert output["status"] == "failed"
    assert output["cases"][0]["case_id"] == "doc-exists"
    assert output["cases"][0]["status"] == "failed"
