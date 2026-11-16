"""测试共用工厂与常量。"""

from datetime import datetime, timezone

from sensor_normalizer.models import Calibration, DeviceMetadata, RawReading

UTC = timezone.utc

QUALITY_MAP = {
    "OK": "GOOD",
    "WARN": ("UNCERTAIN", "SENSOR_WARN"),
    "FAIL": "BAD",
}


def utc(year, month, day, hour=0, minute=0, second=0, microsecond=0):
    return datetime(year, month, day, hour, minute, second, microsecond, tzinfo=UTC)


def make_device(device_id="dev-1", unit="celsius", **kwargs):
    kwargs.setdefault("quality_map", dict(QUALITY_MAP))
    return DeviceMetadata(device_id=device_id, temperature_unit=unit, **kwargs)


def make_calibration(
    calibration_id,
    version,
    effective_from,
    effective_to=None,
    slope=1.0,
    intercept=0.0,
    device_id="dev-1",
    received_at=None,
):
    return Calibration(
        calibration_id=calibration_id,
        device_id=device_id,
        version=version,
        effective_from=effective_from,
        effective_to=effective_to,
        slope=slope,
        intercept=intercept,
        received_at=received_at or utc(2026, 1, 10),
    )


def make_reading(
    reading_id="r-1",
    device_id="dev-1",
    value=10.0,
    device_timestamp=None,
    quality_code="OK",
    ingested_at=None,
):
    return RawReading(
        reading_id=reading_id,
        device_id=device_id,
        value=value,
        device_timestamp=device_timestamp or utc(2026, 1, 5),
        quality_code=quality_code,
        ingested_at=ingested_at or utc(2026, 1, 6),
    )


def register_identity_calibration(normalizer, device_id="dev-1"):
    """注册覆盖 2026 全年的恒等校准，便于聚焦其他行为的测试。"""

    normalizer.register_calibration(
        make_calibration(
            "cal-identity",
            1,
            utc(2026, 1, 1),
            utc(2027, 1, 1),
            device_id=device_id,
        )
    )
