"""测试用插件包构造器：一个目录 + plugin.json + 两个平台的入口脚本。"""

from __future__ import annotations

import json
from pathlib import Path


def make_plugin(tmp_path: Path, name: str, sh_body: str, ps_body: str) -> Path:
    directory = tmp_path / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "plugin.json").write_text(
        json.dumps(
            {
                "name": name,
                "version": "0.1.0",
                "timeout_seconds": 10,
                "entrypoints": {
                    "linux": ["sh", "main.sh"],
                    "windows": [
                        "powershell",
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        "main.ps1",
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    # .sh 必须 LF：CRLF 会让 `exit 7\r` 变成 "Illegal number"
    (directory / "main.sh").write_text(sh_body, encoding="utf-8", newline="\n")
    (directory / "main.ps1").write_text(ps_body, encoding="utf-8")
    return directory
