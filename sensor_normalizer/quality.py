"""厂商质量码归一化。

标准质量状态：

- ``GOOD``：读数可信；
- ``UNCERTAIN``：读数可用但可信度存疑（如无匹配校准、时钟修正超阈）；
- ``BAD``：读数无效，温度输出为 ``None``，不参与正常报表统计。

质量标记 ``quality_flags`` 给出附加原因，允许多个并存。
"""

from __future__ import annotations

from typing import Any, Mapping, Tuple

from .errors import InvalidReadingError
from .models import DeviceMetadata

GOOD = "GOOD"
UNCERTAIN = "UNCERTAIN"
BAD = "BAD"

VALID_STATUSES = (GOOD, UNCERTAIN, BAD)

UNCALIBRATED = "UNCALIBRATED"
DUPLICATE = "DUPLICATE"
CORRECTED = "CORRECTED"
CLOCK_SKEW = "CLOCK_SKEW"
INVALID_QUALITY_CODE = "INVALID_QUALITY_CODE"


def normalize_quality(code: Any, device: DeviceMetadata) -> Tuple[str, Tuple[str, ...]]:
    """把厂商质量码映射为标准状态与附加标记。

    映射表值可以是状态字符串，或 ``(状态, 标记/标记列表)``。
    映射表中不存在的质量码一律判为 ``BAD`` 并附加
    ``INVALID_QUALITY_CODE`` 标记，避免把未知码静默当作正常值。
    """

    mapping: Mapping = device.quality_map or {}
    if code is None:
        code = "OK"
    if code not in mapping:
        return BAD, (INVALID_QUALITY_CODE,)
    entry = mapping[code]
    if isinstance(entry, str):
        status, extra = entry, ()
    elif isinstance(entry, tuple) and len(entry) == 2:
        status, raw_flags = entry
        if isinstance(raw_flags, str):
            extra = (raw_flags,)
        else:
            extra = tuple(raw_flags)
    else:
        raise InvalidReadingError(
            f"设备 {device.device_id} 的质量码映射配置非法: {entry!r}"
        )
    if status not in VALID_STATUSES:
        raise InvalidReadingError(f"未知的标准质量状态: {status!r}")
    return status, extra
