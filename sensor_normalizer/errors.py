"""归一化组件的异常类型。"""


class NormalizerError(Exception):
    """所有归一化相关异常的基类。"""


class UnknownDeviceError(NormalizerError):
    """原始读数引用了未注册的设备。"""


class UnknownUnitError(NormalizerError):
    """设备元数据声明了组件不认识的温度单位。"""


class InvalidReadingError(NormalizerError):
    """原始读数缺少必要字段或字段取值非法。"""


class CalibrationError(NormalizerError):
    """校准区间/系数非法，或校准版本无法确定修订顺序。"""


class DuplicateConflictError(NormalizerError):
    """同一记录 ID 被再次写入，但原始内容与已存证据不一致。"""
