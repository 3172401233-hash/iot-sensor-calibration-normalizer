"""传感器读数归一化器。

处理流程：

1. 校验设备与原始读数，原始载荷计算 SHA-256 后作为不可变证据落库；
2. 温度统一换算到摄氏度，再按生效校准应用线性修正；
3. 设备时间戳解析为 UTC，修正固定时钟偏差与线性漂移；
4. 厂商质量码映射为 ``GOOD`` / ``UNCERTAIN`` / ``BAD`` 并附加质量标记；
5. 迟到校准注册时，对受影响历史读数生成更正批次：旧版本只做
   ``superseded_by`` 标记，原始证据与旧归一化记录均不被覆盖。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional

from . import quality as q
from .calibration import (
    apply_calibration,
    select_calibration,
    validate_calibration,
)
from .checksum import sha256_hex
from .errors import (
    CalibrationError,
    DuplicateConflictError,
    InvalidReadingError,
    UnknownDeviceError,
)
from .models import (
    Calibration,
    CorrectionBatch,
    DeviceMetadata,
    IngestResult,
    NormalizedReading,
    RawEvidence,
    RawReading,
)
from .store import EvidenceStore
from .timeutils import apply_clock_model, parse_device_timestamp
from .units import CELSIUS, canonical_unit, to_celsius

_DEFAULT_CLOCK_SKEW_SECONDS = 300.0


class Normalizer:
    """归一化组件入口，状态保存在 :class:`EvidenceStore` 中。"""

    def __init__(
        self,
        store: Optional[EvidenceStore] = None,
        clock_skew_seconds: float = _DEFAULT_CLOCK_SKEW_SECONDS,
    ) -> None:
        self.store = store if store is not None else EvidenceStore()
        self.clock_skew_seconds = float(clock_skew_seconds)
        self._devices: Dict[str, DeviceMetadata] = {}
        self._calibrations: Dict[str, Calibration] = {}
        self._by_device: Dict[str, List[Calibration]] = defaultdict(list)

    # -- 注册 -----------------------------------------------------------

    def register_device(self, device: DeviceMetadata) -> None:
        """注册或替换设备元数据；单位名在注册时即做合法性校验。"""

        if not device.device_id:
            raise InvalidReadingError("device_id 不能为空")
        canonical_unit(device.temperature_unit)
        self._devices[device.device_id] = device

    def register_calibration(
        self, calibration: Calibration
    ) -> Optional[CorrectionBatch]:
        """注册校准版本。

        若校准在其生效区间内迟到（区间内已有按旧系数归一化的读数），
        则生成并返回 :class:`CorrectionBatch`；没有受影响读数时返回
        ``None``。同一校准重复注册是幂等的，直接返回已有批次。
        """

        validate_calibration(calibration)
        if calibration.device_id not in self._devices:
            raise UnknownDeviceError(
                f"校准引用了未注册的设备: {calibration.device_id!r}"
            )
        existing = self._calibrations.get(calibration.calibration_id)
        if existing is not None:
            if existing != calibration:
                raise CalibrationError(
                    f"校准 {calibration.calibration_id} 已存在且内容不一致"
                )
            return self.store.get_batch(calibration.calibration_id)
        for item in self._by_device[calibration.device_id]:
            if item.version == calibration.version:
                raise CalibrationError(
                    f"设备 {calibration.device_id} 已存在版本号 "
                    f"{calibration.version} 的校准"
                )
        self._calibrations[calibration.calibration_id] = calibration
        self._by_device[calibration.device_id].append(calibration)
        return self._build_correction_batch(calibration)

    # -- 读数写入 -------------------------------------------------------

    def ingest(self, raw: RawReading) -> IngestResult:
        """写入一条原始读数并返回归一化结果，按 ``reading_id`` 幂等。"""

        device = self._devices.get(raw.device_id)
        if device is None:
            raise UnknownDeviceError(f"未注册的设备: {raw.device_id!r}")
        if not raw.reading_id:
            raise InvalidReadingError("reading_id 不能为空")
        try:
            numeric_value = float(raw.value)
        except (TypeError, ValueError) as exc:
            raise InvalidReadingError(
                f"读数 {raw.reading_id} 的数值非法: {raw.value!r}"
            ) from exc

        ingested_at = raw.ingested_at or datetime.now(timezone.utc)
        if ingested_at.tzinfo is None:
            raise InvalidReadingError("ingested_at 必须带 UTC 时区")

        evidence = self._build_evidence(raw, numeric_value, ingested_at)
        previous = self.store.get_raw(raw.reading_id)
        if previous is not None:
            if previous.checksum != evidence.checksum:
                raise DuplicateConflictError(
                    f"读数 {raw.reading_id} 已存在但内容不同，原始证据不可覆盖"
                )
            current = self.store.get_current(raw.reading_id)
            return IngestResult(
                normalized=current, raw_evidence=previous, duplicate=True
            )

        normalized = self._compute(
            raw,
            device,
            numeric_value,
            ingested_at,
            revision=1,
            source_checksum=evidence.checksum,
        )
        self.store.put_raw(evidence)
        self.store.add_normalized(normalized)
        return IngestResult(
            normalized=normalized, raw_evidence=evidence, duplicate=False
        )

    # -- 内部：归一化计算 -----------------------------------------------

    def _compute(
        self,
        raw: RawReading,
        device: DeviceMetadata,
        numeric_value: float,
        ingested_at: datetime,
        revision: int,
        force_calibration: Optional[Calibration] = None,
        source_checksum: Optional[str] = None,
    ) -> NormalizedReading:
        observed_utc, precision = parse_device_timestamp(raw.device_timestamp, device)
        timestamp_utc = apply_clock_model(observed_utc, device)
        skew_seconds = abs((observed_utc - timestamp_utc).total_seconds())

        raw_celsius = to_celsius(numeric_value, device.temperature_unit)
        status, flags = q.normalize_quality(raw.quality_code, device)
        flags = list(flags)

        calibration = force_calibration or select_calibration(
            self._by_device[device.device_id], timestamp_utc
        )
        if calibration is None:
            self._add_flag(flags, q.UNCALIBRATED)
            if status == q.GOOD:
                status = q.UNCERTAIN

        if status == q.BAD:
            temperature = None
        elif calibration is None:
            temperature = raw_celsius
        else:
            temperature = apply_calibration(raw_celsius, calibration)

        if skew_seconds > self.clock_skew_seconds:
            self._add_flag(flags, q.CLOCK_SKEW)
            if status == q.GOOD:
                status = q.UNCERTAIN
        if force_calibration is not None:
            self._add_flag(flags, q.CORRECTED)

        if source_checksum is None:
            source_checksum = self._raw_checksum(raw, numeric_value, ingested_at)
        body = {
            "reading_id": raw.reading_id,
            "device_id": device.device_id,
            "timestamp_utc": timestamp_utc,
            "time_precision": precision,
            "temperature_celsius": self._round(temperature),
            "raw_temperature_celsius": self._round(raw_celsius),
            "unit": CELSIUS,
            "quality_status": status,
            "quality_flags": tuple(flags),
            "calibration_id": calibration.calibration_id if calibration else None,
            "calibration_version": calibration.version if calibration else None,
            "source_checksum": source_checksum,
            "revision": revision,
        }
        return NormalizedReading(
            timestamp_utc=timestamp_utc,
            time_precision=precision,
            temperature_celsius=body["temperature_celsius"],
            raw_temperature_celsius=body["raw_temperature_celsius"],
            unit=CELSIUS,
            quality_status=status,
            quality_flags=tuple(flags),
            calibration_id=body["calibration_id"],
            calibration_version=body["calibration_version"],
            source_checksum=source_checksum,
            revision=revision,
            superseded_by=None,
            checksum=sha256_hex(body),
            reading_id=raw.reading_id,
            device_id=device.device_id,
        )

    def _build_correction_batch(
        self, calibration: Calibration
    ) -> Optional[CorrectionBatch]:
        affected: List[NormalizedReading] = []
        for evidence in self.store.all_raw():
            if evidence.device_id != calibration.device_id:
                continue
            current = self.store.get_current(evidence.reading_id)
            if current is None:
                continue
            if self._in_interval(current.timestamp_utc, calibration):
                affected.append(current)

        if not affected:
            return None

        corrected_ids: List[str] = []
        superseded_checksums: List[str] = []
        new_checksums: List[str] = []
        timestamps: List[datetime] = []
        for old in affected:
            evidence = self.store.get_raw(old.reading_id)
            payload = evidence.raw_payload
            raw = RawReading(
                reading_id=payload["reading_id"],
                device_id=payload["device_id"],
                value=payload["value"],
                device_timestamp=payload["device_timestamp"],
                quality_code=payload["quality_code"],
                ingested_at=payload["ingested_at"],
            )
            device = self._devices[evidence.device_id]
            new = self._compute(
                raw,
                device,
                float(payload["value"]),
                evidence.stored_at,
                revision=old.revision + 1,
                force_calibration=calibration,
                source_checksum=evidence.checksum,
            )
            self.store.mark_superseded(old.reading_id, old.revision, new.checksum)
            self.store.add_normalized(new)
            corrected_ids.append(old.reading_id)
            superseded_checksums.append(old.checksum)
            new_checksums.append(new.checksum)
            timestamps.append(new.timestamp_utc)

        content = {
            "calibration_id": calibration.calibration_id,
            "device_id": calibration.device_id,
            "affected_from": min(timestamps),
            "affected_to": max(timestamps),
            "affected_reading_ids": tuple(corrected_ids),
            "superseded_reading_ids": tuple(superseded_checksums),
            "checksums": tuple(new_checksums),
            "created_at": calibration.received_at,
        }
        digest = sha256_hex(content)
        batch = CorrectionBatch(
            batch_id=f"BATCH-{digest[:16]}",
            calibration_id=calibration.calibration_id,
            device_id=calibration.device_id,
            affected_from=content["affected_from"],
            affected_to=content["affected_to"],
            affected_reading_ids=tuple(corrected_ids),
            corrected_reading_ids=tuple(corrected_ids),
            superseded_reading_ids=tuple(superseded_checksums),
            created_at=calibration.received_at,
            checksums=tuple(new_checksums),
            checksum=digest,
        )
        self.store.add_batch(batch)
        return batch

    # -- 内部：工具 -----------------------------------------------------

    def _build_evidence(
        self, raw: RawReading, numeric_value: float, ingested_at: datetime
    ) -> RawEvidence:
        payload = self._raw_payload(raw, numeric_value, ingested_at)
        return RawEvidence(
            reading_id=raw.reading_id,
            device_id=raw.device_id,
            raw_payload=payload,
            checksum=sha256_hex(payload),
            stored_at=ingested_at,
        )

    def _raw_checksum(
        self, raw: RawReading, numeric_value: float, ingested_at: datetime
    ) -> str:
        return sha256_hex(self._raw_payload(raw, numeric_value, ingested_at))

    @staticmethod
    def _raw_payload(
        raw: RawReading, numeric_value: float, ingested_at: datetime
    ) -> dict:
        timestamp = raw.device_timestamp
        if isinstance(timestamp, datetime):
            timestamp = timestamp.isoformat()
        return {
            "reading_id": raw.reading_id,
            "device_id": raw.device_id,
            "value": numeric_value,
            "device_timestamp": timestamp,
            "quality_code": raw.quality_code,
            "ingested_at": ingested_at.isoformat(),
        }

    @staticmethod
    def _in_interval(timestamp_utc: datetime, calibration: Calibration) -> bool:
        if timestamp_utc < calibration.effective_from:
            return False
        return (
            calibration.effective_to is None
            or timestamp_utc < calibration.effective_to
        )

    @staticmethod
    def _add_flag(flags: List[str], flag: str) -> None:
        if flag not in flags:
            flags.append(flag)

    @staticmethod
    def _round(value: Optional[float]) -> Optional[float]:
        if value is None:
            return None
        return round(float(value), 9)
