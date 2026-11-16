"""传感器读数归一化组件。

对外提供设备/校准/原始读数的数据模型、归一化器以及异常类型。
所有处理仅依赖 Python 标准库，且原始证据一经写入不可修改。
"""

from .errors import (
    CalibrationError,
    DuplicateConflictError,
    InvalidReadingError,
    UnknownDeviceError,
    UnknownUnitError,
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
from .normalizer import Normalizer
from .store import EvidenceStore

__all__ = [
    "Calibration",
    "CalibrationError",
    "CorrectionBatch",
    "DeviceMetadata",
    "DuplicateConflictError",
    "EvidenceStore",
    "IngestResult",
    "InvalidReadingError",
    "NormalizedReading",
    "Normalizer",
    "RawEvidence",
    "RawReading",
    "UnknownDeviceError",
    "UnknownUnitError",
]
