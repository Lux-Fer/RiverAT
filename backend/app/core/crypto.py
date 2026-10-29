"""凭据加密：用 ``SECRET_KEY`` 派生 Fernet 密钥。

注意：换 ``SECRET_KEY`` 会让已存的测试机凭据全部解不开 —— 换之前要先轮换凭据。
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


class CryptoError(RuntimeError):
    """密文无法解开（通常是因为 SECRET_KEY 变了）。"""


def _fernet() -> Fernet:
    digest = hashlib.sha256(get_settings().secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise CryptoError("凭据解密失败：SECRET_KEY 可能已更换") from exc
