#!/usr/bin/env python3
"""text_doc_check：检查本地文本文档。按 RiverAT 工具契约 v2 从 stdin 读 JSON、stdout 写 JSON。"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

DEFAULT_ROOT = "/app/backend/var/documents"


def case(case_id: str, status: str, reason: str = "") -> dict:
    return {
        "case_id": case_id,
        "status": status,
        "duration_ms": 0,
        "reason": reason,
    }


def emit(status: str, cases: list[dict], *, reason: str = "", **extra) -> None:
    out = {
        "status": status,
        "reason": reason or ("检查通过" if status == "passed" else "有检查未通过"),
        "cases": cases,
        **extra,
    }
    sys.stdout.write(json.dumps(out, ensure_ascii=False))
    sys.stdout.write("\n")


def main() -> int:
    started = time.monotonic()
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError) as exc:
        sys.stderr.write(f"读取工具输入失败：{exc}\n")
        return 2

    args = payload.get("args") or {}
    if not isinstance(args, dict):
        args = {}
    raw_path = args.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        emit(
            "failed",
            [case("doc-exists", "failed", "缺少参数 path")],
            reason="缺少文本文档路径",
        )
        return 0

    root = os.environ.get("RIVERAT_DOCS_ROOT") or DEFAULT_ROOT
    path = Path(raw_path.strip()).expanduser()
    if not path.is_absolute():
        path = Path(root) / path

    try:
        path = path.resolve()
    except OSError as exc:
        emit(
            "failed",
            [case("doc-exists", "failed", f"路径无法解析：{exc}")],
            reason="路径无法解析",
        )
        return 0

    cases: list[dict] = []
    if not path.exists():
        emit(
            "failed",
            [case("doc-exists", "failed", f"文件不存在：{path}")],
            reason="文件不存在",
            path=str(path),
        )
        return 0
    if not path.is_file():
        emit(
            "failed",
            [case("doc-exists", "failed", f"不是普通文件：{path}")],
            reason="路径不是普通文件",
            path=str(path),
        )
        return 0

    try:
        size = path.stat().st_size
    except OSError as exc:
        emit(
            "failed",
            [case("doc-size", "failed", f"读取文件信息失败：{exc}")],
            reason="读取文件信息失败",
            path=str(path),
        )
        return 0

    cases.append(case("doc-exists", "passed", str(path)))
    max_bytes = args.get("max_bytes", 5_000_000)
    if not isinstance(max_bytes, int) or max_bytes <= 0:
        max_bytes = 5_000_000
    if size > max_bytes:
        cases.append(case("doc-size", "failed", f"{size} 字节，超过上限 {max_bytes}"))
        cases.append(case("doc-encoding", "skipped", "文件过大，未读取"))
        cases.append(case("doc-min-chars", "skipped", "文件过大，未读取"))
        if isinstance(args.get("contains"), str) and args["contains"]:
            cases.append(case("doc-contains", "skipped", "文件过大，未读取"))
        emit("failed", cases, reason="文件超过大小上限", path=str(path), bytes=size)
        return 0
    cases.append(case("doc-size", "passed", f"{size} 字节"))

    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        cases.append(case("doc-encoding", "failed", f"读取失败：{exc}"))
        emit("failed", cases, reason="读取文件失败", path=str(path), bytes=size)
        return 0

    encoding = args.get("encoding") or "utf-8"
    if encoding not in {"utf-8", "utf-8-sig", "gbk", "latin-1"}:
        encoding = "utf-8"
    try:
        text = raw_bytes.decode(encoding)
    except UnicodeDecodeError as exc:
        cases.append(
            case("doc-encoding", "failed", f"按 {encoding} 解码失败：{exc.reason}")
        )
        cases.append(case("doc-min-chars", "skipped", "编码失败，未检查"))
        if isinstance(args.get("contains"), str) and args["contains"]:
            cases.append(case("doc-contains", "skipped", "编码失败，未检查"))
        emit(
            "failed",
            cases,
            reason=f"不是合法的 {encoding} 文本",
            path=str(path),
            bytes=size,
        )
        return 0
    cases.append(case("doc-encoding", "passed", f"{encoding} 解码通过"))

    min_chars = args.get("min_chars", 1)
    if not isinstance(min_chars, int) or min_chars < 0:
        min_chars = 1
    stripped_chars = len(text.strip())
    if stripped_chars < min_chars:
        cases.append(
            case("doc-min-chars", "failed", f"去空白后 {stripped_chars} 字，少于 {min_chars}")
        )
    else:
        cases.append(case("doc-min-chars", "passed", f"去空白后 {stripped_chars} 字"))

    contains = args.get("contains")
    if isinstance(contains, str) and contains:
        if contains in text:
            cases.append(case("doc-contains", "passed", f"包含「{contains}」"))
        else:
            cases.append(case("doc-contains", "failed", f"未找到「{contains}」"))

    failed = [item for item in cases if item["status"] == "failed"]
    elapsed = round((time.monotonic() - started) * 1000)
    if failed:
        emit(
            "failed",
            cases,
            reason="；".join(item["reason"] for item in failed),
            path=str(path),
            bytes=size,
            duration_ms=elapsed,
        )
    else:
        sys.stdout.write(
            json.dumps(
                {
                    "status": "passed",
                    "cases": cases,
                    "path": str(path),
                    "bytes": size,
                    "duration_ms": elapsed,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    try:
        raise SystemExit(main())
    except Exception as exc:
        sys.stderr.write(f"text_doc_check 异常：{exc}\n")
        raise SystemExit(2) from exc
