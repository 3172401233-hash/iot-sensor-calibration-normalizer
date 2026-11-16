"""设备时间戳解析与时钟修正。

支持三类设备时间戳：

- ``datetime``（带时区或 naive，naive 按设备元数据时区解释）；
- epoch 秒，``int`` 视为秒级精度，``float`` 视为亚秒级精度；
- ISO 8601 字符串，精度按字符串中的小数位推断。

输出统一为带 UTC 时区的 ``datetime``，并报告原始时间精度
（``seconds`` / ``milliseconds`` / ``microseconds``）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

from .errors import InvalidReadingError
from .models import DeviceMetadata

SECONDS = "seconds"
MILLISECONDS = "milliseconds"
MICROSECONDS = "microseconds"


def resolve_timezone(name: Optional[str]) -> tzinfo:
    """把时区名称解析为 ``tzinfo``；``None``/``"UTC"`` 返回 UTC。"""

    if name is None:
        return timezone.utc
    text = name.strip()
    if text.upper() in ("UTC", "Z", "GMT"):
        return timezone.utc
    if text[0] in "+-" and ":" in text:
        sign = 1 if text[0] == "+" else -1
        hours, minutes = text[1:].split(":")
        return timezone(sign * timedelta(hours=int(hours), minutes=int(minutes)))
    return ZoneInfo(text)


def parse_device_timestamp(value: object, device: DeviceMetadata) -> Tuple[datetime, str]:
    """解析设备时间戳并换算为 UTC，返回 ``(utc_datetime, 原始精度)``。"""

    if isinstance(value, datetime):
        precision = MICROSECONDS if value.microsecond else SECONDS
        if value.tzinfo is None:
            value = value.replace(tzinfo=resolve_timezone(device.timezone))
        return value.astimezone(timezone.utc), precision

    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise InvalidReadingError(
            f"设备 {device.device_id} 的时间戳类型不受支持: {type(value)!r}"
        )

    if isinstance(value, int):
        return datetime.fromtimestamp(value, tz=timezone.utc), SECONDS

    if isinstance(value, float):
        return _from_epoch_float(value), _numeric_precision(repr(value))

    text = value.strip()
    try:
        number = float(text)
    except ValueError:
        return _parse_iso(text, device)
    return _from_epoch_float(number), _numeric_precision(text)


def apply_clock_model(utc_time: datetime, device: DeviceMetadata) -> datetime:
    """按设备元数据修正固定偏差与线性漂移。

    修正模型::

        true_utc = observed_utc
                   - clock_offset_seconds
                   - elapsed_seconds * clock_drift_ppm / 1_000_000

    漂移参考时刻缺失时漂移项为 0。漂移率为正表示设备时钟走得偏快。
    """

    correction = float(device.clock_offset_seconds)
    reference = device.drift_reference_time
    if reference is not None and device.clock_drift_ppm:
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)
        elapsed = (utc_time - reference.astimezone(timezone.utc)).total_seconds()
        correction += elapsed * float(device.clock_drift_ppm) / 1_000_000.0
    corrected = utc_time - timedelta(seconds=correction)
    return corrected.astimezone(timezone.utc)


def _from_epoch_float(number: float) -> datetime:
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=number)


def _numeric_precision(text: str) -> str:
    fractional = text.split(".", 1)[1] if "." in text else ""
    if not fractional:
        return SECONDS
    if len(fractional) <= 3:
        return MILLISECONDS
    return MICROSECONDS


def _parse_iso(text: str, device: DeviceMetadata) -> Tuple[datetime, str]:
    iso = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(iso)
    except ValueError as exc:
        raise InvalidReadingError(
            f"设备 {device.device_id} 的时间戳无法解析: {text!r}"
        ) from exc
    precision = _iso_precision(parsed)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=resolve_timezone(device.timezone))
    return parsed.astimezone(timezone.utc), precision


def _iso_precision(parsed: datetime) -> str:
    if parsed.microsecond == 0:
        return SECONDS
    if parsed.microsecond % 1000 == 0:
        return MILLISECONDS
    return MICROSECONDS
