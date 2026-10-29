"""插件清单（plugin.json）。

清单是插件与平台之间的唯一契约：平台只读这些字段，不猜插件的内部结构。

```json
{
  "name": "fake-pass",
  "version": "0.1.0",
  "timeout_seconds": 30,
  "entrypoints": {
    "linux":   ["sh", "main.sh"],
    "windows": ["powershell", "-NoProfile", "-File", "main.ps1"]
  }
}
```

插件运行时收到的唯一参数是 job.json 的路径；需要产出结果时写
``plugin_result.json``（可选）与 ``artifacts/`` 目录（可选）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

MANIFEST_NAME = "plugin.json"


@dataclass(frozen=True, slots=True)
class PluginManifest:
    name: str
    version: str
    entrypoints: dict[str, list[str]]
    timeout_seconds: float = 60.0
    description: str = ""
    capabilities: tuple[str, ...] = field(default_factory=tuple)

    def entrypoint_for(self, os_name: str) -> list[str]:
        """按目标系统取入口；未声明时回退到 linux，再不行就报错。"""

        candidate = self.entrypoints.get(os_name) or self.entrypoints.get("linux")
        if not candidate:
            raise ValueError(
                f"插件 {self.name} 没有为 {os_name} 声明 entrypoint"
            )
        return list(candidate)


def load_manifest(directory: Path) -> PluginManifest:
    path = Path(directory) / MANIFEST_NAME
    if not path.is_file():
        raise ValueError(f"缺少插件清单: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    entrypoints = data.get("entrypoints") or {}
    if not isinstance(entrypoints, dict):
        raise TypeError("entrypoints 必须是 {系统: [命令...]} 的形式")

    return PluginManifest(
        name=str(data.get("name") or directory.name),
        version=str(data.get("version") or "0.0.0"),
        entrypoints={k: [str(part) for part in v] for k, v in entrypoints.items()},
        timeout_seconds=float(data.get("timeout_seconds") or 60.0),
        description=str(data.get("description") or ""),
        capabilities=tuple(str(c) for c in (data.get("capabilities") or ())),
    )
