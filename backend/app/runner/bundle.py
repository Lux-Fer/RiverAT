"""插件打包：把插件目录打成 tar.gz，并给出内容哈希。

用 tar.gz 而不是 zip：Linux/macOS 自带 tar，Windows 10+ 也带 bsdtar，
不需要目标机额外装解压工具。
"""

from __future__ import annotations

import hashlib
import io
import tarfile
from pathlib import Path


def pack_bundle(directory: Path) -> tuple[bytes, str]:
    """返回 (tar.gz 字节, sha256 十六进制)。"""

    root = Path(directory)
    if not root.is_dir():
        raise ValueError(f"插件目录不存在: {root}")

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                tar.add(path, arcname=str(path.relative_to(root)))
    data = buffer.getvalue()
    return data, hashlib.sha256(data).hexdigest()
