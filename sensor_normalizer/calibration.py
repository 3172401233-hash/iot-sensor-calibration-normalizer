"""校准版本管理与生效区间选择。"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from .errors import CalibrationError
from .models import Calibration


def validate_calibration(calibration: Calibration) -> None:
    """校验单条校准记录的字段合法性。"""

    if not calibration.calibration_id or not calibration.device_id:
        raise CalibrationError("校准 ID 与设备 ID 均不能为空")
    if not isinstance(calibration.version, int) or calibration.version < 1:
        raise CalibrationError("校准版本号必须是 >= 1 的整数")
    _require_utc(calibration.effective_from, "effective_from")
    if calibration.effective_to is not None:
        _require_utc(calibration.effective_to, "effective_to")
        if calibration.effective_to <= calibration.effective_from:
            raise CalibrationError("校准生效区间必须满足 effective_from < effective_to")
    _require_utc(calibration.received_at, "received_at")


def select_calibration(
    calibrations: List[Calibration], timestamp_utc: datetime
) -> Optional[Calibration]:
    """选择在给定 UTC 时刻生效的校准。

    区间为左闭右开 ``[effective_from, effective_to)``。同一时刻命中多条
    （数据迟到导致的版本交叠）时，取版本号最大者；版本号相同再取
    ``received_at`` 更晚者，保证选择结果确定且可解释。
    """

    candidates = [
        item
        for item in calibrations
        if item.effective_from <= timestamp_utc
        and (item.effective_to is None or timestamp_utc < item.effective_to)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item.version, item.received_at))


def apply_calibration(raw_celsius: float, calibration: Calibration) -> float:
    """按线性模型应用校准系数。"""

    return raw_celsius * calibration.slope + calibration.intercept


def _require_utc(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise CalibrationError(f"校准字段 {field_name} 必须是 datetime")
    if value.tzinfo is None:
        raise CalibrationError(f"校准字段 {field_name} 必须带 UTC 时区")
