"""校验和工具。

统一使用 SHA-256，对规范化后的 JSON 字节取摘要，保证不同进程/平台下
同一逻辑对象得到相同的校验和。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any


def canonical_json(obj: Any) -> bytes:
    """把对象序列化为确定性 JSON 字节串。

    - 键排序、无多余空白；
    - ``datetime`` 统一输出带时区的 ISO 8601 字符串；
    - ``tuple`` 与 ``list`` 均按数组处理。
    """

    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_default,
    ).encode("utf-8")


def sha256_hex(obj: Any) -> str:
    """计算对象的 SHA-256 十六进制摘要。"""

    return hashlib.sha256(canonical_json(obj)).hexdigest()


def _default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(f"无法计算校验和的对象类型: {type(value)!r}")
