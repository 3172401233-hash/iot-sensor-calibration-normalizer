"""组件的数据模型。

所有模型均为不可变 ``frozen`` dataclass，保证进入证据链后不会被就地修改。
基准温度单位为摄氏度（Celsius, ``celsius``），基准时间为带 UTC 时区的
``datetime``（``tzinfo=timezone.utc``）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class DeviceMetadata:
    """设备元数据。

    :param device_id: 设备唯一标识。
    :param temperature_unit: 上报温度单位，支持 ``celsius`` / ``fahrenheit`` /
        ``kelvin``（大小写不敏感）。
    :param timezone: 设备时间戳所在时区，可为 IANA 名称（如 ``Asia/Shanghai``）
        或固定偏移（如 ``+08:00``）；为 ``None`` 时按 UTC 处理。
    :param clock_offset_seconds: 已知的设备时钟固定偏差（秒）。设备时钟比 UTC
        快时取正值，修正方式为 ``utc = device_time - offset``。
    :param clock_drift_ppm: 设备时钟漂移率，单位 ppm（百万分之一），按
        :attr:`drift_reference_time` 起算的经过时间线性修正。
    :param drift_reference_time: 漂移率的参考时刻（UTC），为 ``None`` 时
        漂移项视为 0。
    :param quality_map: 厂商质量码到标准质量状态的映射表。
    """

    device_id: str
    temperature_unit: str = "celsius"
    timezone: Optional[str] = None
    clock_offset_seconds: float = 0.0
    clock_drift_ppm: float = 0.0
    drift_reference_time: Optional[datetime] = None
    quality_map: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Calibration:
    """一条校准版本及其生效区间。

    生效区间为左闭右开 ``[effective_from, effective_to)``；
    ``effective_to`` 为 ``None`` 表示当前仍生效。
    归一化采用线性模型::

        calibrated = raw_base * slope + intercept

    其中 ``raw_base`` 是已换算到基准单位（摄氏度）的原始值。
    """

    calibration_id: str
    device_id: str
    version: int
    effective_from: datetime
    effective_to: Optional[datetime]
    slope: float
    intercept: float
    received_at: datetime


@dataclass(frozen=True)
class RawReading:
    """设备上报的一条原始读数。

    :param reading_id: 读数唯一标识，也是幂等键。
    :param device_id: 来源设备标识。
    :param value: 原始温度数值。
    :param device_timestamp: 设备本地时间戳，支持 ``datetime``、epoch 秒
        （``int``/``float``）或 ISO 8601 字符串。
    :param quality_code: 厂商质量码，缺省按 ``"OK"`` 处理。
    :param ingested_at: 平台接收时间（UTC），用于判定校准是否迟到。
    """

    reading_id: str
    device_id: str
    value: float
    device_timestamp: object
    quality_code: object = "OK"
    ingested_at: Optional[datetime] = None


@dataclass(frozen=True)
class RawEvidence:
    """已落库的原始证据，追加后不可修改、不可删除。"""

    reading_id: str
    device_id: str
    raw_payload: dict
    checksum: str
    stored_at: datetime


@dataclass(frozen=True)
class NormalizedReading:
    """归一化结果。

    被后续校准修订替换的读数不会被删除，而是通过 :attr:`superseded_by`
    指向替换它的新读数，形成可追溯的版本链。
    """

    reading_id: str
    device_id: str
    timestamp_utc: datetime
    time_precision: str
    temperature_celsius: Optional[float]
    raw_temperature_celsius: Optional[float]
    unit: str
    quality_status: str
    quality_flags: tuple
    calibration_id: Optional[str]
    calibration_version: Optional[int]
    source_checksum: str
    revision: int
    superseded_by: Optional[str]
    checksum: str


@dataclass(frozen=True)
class CorrectionBatch:
    """一次迟到校准触发的更正批次。"""

    batch_id: str
    calibration_id: str
    device_id: str
    affected_from: Optional[datetime]
    affected_to: Optional[datetime]
    affected_reading_ids: tuple
    corrected_reading_ids: tuple
    superseded_reading_ids: tuple
    created_at: datetime
    checksums: tuple
    checksum: str


@dataclass(frozen=True)
class IngestResult:
    """单条读数写入的处理结果。"""

    normalized: NormalizedReading
    raw_evidence: RawEvidence
    duplicate: bool
