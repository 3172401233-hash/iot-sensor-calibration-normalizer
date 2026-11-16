"""追加式证据存储（内存实现）。

存储分三类，均只追加、不就地修改：

- :class:`~sensor_normalizer.models.RawEvidence`：原始读数证据，写入后
  任何路径都不能覆盖或删除；
- :class:`~sensor_normalizer.models.NormalizedReading`：归一化读数，
  被修订的旧版本通过 ``superseded_by`` 标记，而非删除；
- :class:`~sensor_normalizer.models.CorrectionBatch`：迟到校准产生的
  更正批次。
"""

from __future__ import annotations
from typing import Dict, List, Optional

from .errors import DuplicateConflictError
from .models import CorrectionBatch, NormalizedReading, RawEvidence


class EvidenceStore:
    """进程内 append-only 存储；持久化场景可按相同接口替换实现。"""

    def __init__(self) -> None:
        self._raw: Dict[str, RawEvidence] = {}
        self._raw_order: List[str] = []
        self._normalized: Dict[str, List[NormalizedReading]] = {}
        self._batches: List[CorrectionBatch] = []

    # -- 原始证据 -------------------------------------------------------

    def put_raw(self, evidence: RawEvidence) -> None:
        existing = self._raw.get(evidence.reading_id)
        if existing is not None:
            if existing.checksum != evidence.checksum:
                raise DuplicateConflictError(
                    f"读数 {evidence.reading_id} 的原始证据已存在且内容不一致，"
                    "原始证据不可覆盖"
                )
            return
        self._raw[evidence.reading_id] = evidence
        self._raw_order.append(evidence.reading_id)

    def get_raw(self, reading_id: str) -> Optional[RawEvidence]:
        return self._raw.get(reading_id)

    def all_raw(self) -> List[RawEvidence]:
        return [self._raw[reading_id] for reading_id in self._raw_order]

    # -- 归一化读数 -----------------------------------------------------

    def add_normalized(self, reading: NormalizedReading) -> None:
        self._normalized.setdefault(reading.reading_id, []).append(reading)

    def get_revisions(self, reading_id: str) -> List[NormalizedReading]:
        return list(self._normalized.get(reading_id, []))

    def get_current(self, reading_id: str) -> Optional[NormalizedReading]:
        revisions = self._normalized.get(reading_id)
        return revisions[-1] if revisions else None

    def mark_superseded(self, reading_id: str, revision: int, new_checksum: str) -> None:
        """把指定修订版本标记为被新读数替换（对象不可变，重建后放回）。"""

        revisions = self._normalized[reading_id]
        index = revision - 1
        old = revisions[index]
        if old.revision != revision:
            raise KeyError(f"读数 {reading_id} 修订 {revision} 不存在")
        revisions[index] = NormalizedReading(
            reading_id=old.reading_id,
            device_id=old.device_id,
            timestamp_utc=old.timestamp_utc,
            time_precision=old.time_precision,
            temperature_celsius=old.temperature_celsius,
            raw_temperature_celsius=old.raw_temperature_celsius,
            unit=old.unit,
            quality_status=old.quality_status,
            quality_flags=old.quality_flags,
            calibration_id=old.calibration_id,
            calibration_version=old.calibration_version,
            source_checksum=old.source_checksum,
            revision=old.revision,
            superseded_by=new_checksum,
            checksum=old.checksum,
        )

    def all_normalized(self) -> List[NormalizedReading]:
        result: List[NormalizedReading] = []
        for reading_id in self._raw_order:
            result.extend(self._normalized.get(reading_id, ()))
        return result

    def current_normalized(self) -> List[NormalizedReading]:
        result: List[NormalizedReading] = []
        for reading_id in self._raw_order:
            revisions = self._normalized.get(reading_id)
            if revisions:
                result.append(revisions[-1])
        return result

    # -- 更正批次 -------------------------------------------------------

    def add_batch(self, batch: CorrectionBatch) -> None:
        self._batches.append(batch)

    def get_batch(self, calibration_id: str) -> Optional[CorrectionBatch]:
        for batch in self._batches:
            if batch.calibration_id == calibration_id:
                return batch
        return None

    def all_batches(self) -> List[CorrectionBatch]:
        return list(self._batches)
