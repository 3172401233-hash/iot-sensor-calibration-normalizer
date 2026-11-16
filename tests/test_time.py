"""设备时间戳、时区与时钟漂移测试。"""

import unittest
from datetime import timedelta

from sensor_normalizer import Normalizer
from sensor_normalizer.errors import InvalidReadingError

from tests._helpers import (
    make_device,
    make_reading,
    register_identity_calibration,
    utc,
)


class TimestampTest(unittest.TestCase):
    def setUp(self):
        self.normalizer = Normalizer()
        self.normalizer.register_device(make_device())
        register_identity_calibration(self.normalizer)

    def test_timezone_aware_datetime_converts_to_utc(self):
        self.normalizer.register_device(make_device(timezone="Asia/Shanghai"))
        from zoneinfo import ZoneInfo

        local = utc(2026, 1, 5, 8, 0).replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        result = self.normalizer.ingest(make_reading(device_timestamp=local))
        self.assertEqual(
            result.normalized.timestamp_utc, utc(2026, 1, 5, 0, 0)
        )

    def test_naive_datetime_uses_device_timezone(self):
        normalizer = Normalizer()
        normalizer.register_device(make_device(timezone="+08:00"))
        register_identity_calibration(normalizer)
        from datetime import datetime

        naive = datetime(2026, 1, 5, 8, 0)
        result = normalizer.ingest(make_reading(device_timestamp=naive))
        self.assertEqual(
            result.normalized.timestamp_utc, utc(2026, 1, 5, 0, 0)
        )

    def test_iso_string_with_z_suffix(self):
        self.normalizer.register_device(make_device())
        result = self.normalizer.ingest(
            make_reading(device_timestamp="2026-01-05T08:00:00Z")
        )
        self.assertEqual(
            result.normalized.timestamp_utc, utc(2026, 1, 5, 8, 0)
        )
        self.assertEqual(result.normalized.time_precision, "seconds")

    def test_epoch_seconds_and_subsecond_precision(self):
        self.normalizer.register_device(make_device())
        epoch = int(utc(2026, 1, 5).timestamp())
        second_result = self.normalizer.ingest(
            make_reading("r-epoch", device_timestamp=epoch)
        )
        self.assertEqual(
            second_result.normalized.timestamp_utc, utc(2026, 1, 5)
        )
        self.assertEqual(second_result.normalized.time_precision, "seconds")

        float_result = self.normalizer.ingest(
            make_reading("r-float", device_timestamp=epoch + 0.25)
        )
        self.assertEqual(
            float_result.normalized.time_precision, "milliseconds"
        )
        micro_result = self.normalizer.ingest(
            make_reading("r-micro", device_timestamp=epoch + 0.123456)
        )
        self.assertEqual(
            micro_result.normalized.time_precision, "microseconds"
        )
        self.assertEqual(
            float_result.normalized.timestamp_utc,
            utc(2026, 1, 5) + timedelta(seconds=0.25),
        )

    def test_millisecond_precision_detected(self):
        self.normalizer.register_device(make_device())
        result = self.normalizer.ingest(
            make_reading(
                "r-ms", device_timestamp="2026-01-05T08:00:00.500+00:00"
            )
        )
        self.assertEqual(result.normalized.time_precision, "milliseconds")

    def test_invalid_timestamp_raises(self):
        self.normalizer.register_device(make_device())
        with self.assertRaises(InvalidReadingError):
            self.normalizer.ingest(
                make_reading(device_timestamp="not-a-timestamp")
            )


class ClockModelTest(unittest.TestCase):
    def test_fast_clock_offset_is_subtracted(self):
        normalizer = Normalizer()
        normalizer.register_device(make_device(clock_offset_seconds=60.0))
        register_identity_calibration(normalizer)
        result = normalizer.ingest(
            make_reading(device_timestamp=utc(2026, 1, 5, 0, 1))
        )
        self.assertEqual(
            result.normalized.timestamp_utc, utc(2026, 1, 5, 0, 0)
        )

    def test_linear_drift_correction(self):
        normalizer = Normalizer()
        normalizer.register_device(
            make_device(
                clock_drift_ppm=100.0,
                drift_reference_time=utc(2026, 1, 1),
            )
        )
        register_identity_calibration(normalizer)
        observed = utc(2026, 1, 2)
        result = normalizer.ingest(make_reading(device_timestamp=observed))
        elapsed = (observed - utc(2026, 1, 1)).total_seconds()
        expected = observed - timedelta(seconds=elapsed * 100.0 / 1_000_000.0)
        self.assertEqual(result.normalized.timestamp_utc, expected)

    def test_offset_and_drift_combined(self):
        normalizer = Normalizer()
        normalizer.register_device(
            make_device(
                clock_offset_seconds=10.0,
                clock_drift_ppm=50.0,
                drift_reference_time=utc(2026, 1, 1),
            )
        )
        register_identity_calibration(normalizer)
        observed = utc(2026, 1, 3)
        result = normalizer.ingest(make_reading(device_timestamp=observed))
        elapsed = (observed - utc(2026, 1, 1)).total_seconds()
        expected = observed - timedelta(
            seconds=10.0 + elapsed * 50.0 / 1_000_000.0
        )
        self.assertEqual(result.normalized.timestamp_utc, expected)

    def test_large_skew_adds_quality_flag(self):
        normalizer = Normalizer(clock_skew_seconds=30.0)
        normalizer.register_device(make_device(clock_offset_seconds=120.0))
        register_identity_calibration(normalizer)
        result = normalizer.ingest(make_reading())
        self.assertEqual(result.normalized.quality_status, "UNCERTAIN")
        self.assertIn("CLOCK_SKEW", result.normalized.quality_flags)

    def test_small_skew_keeps_good_status(self):
        normalizer = Normalizer(clock_skew_seconds=30.0)
        normalizer.register_device(make_device(clock_offset_seconds=5.0))
        register_identity_calibration(normalizer)
        result = normalizer.ingest(make_reading())
        self.assertEqual(result.normalized.quality_status, "GOOD")
        self.assertNotIn("CLOCK_SKEW", result.normalized.quality_flags)


if __name__ == "__main__":
    unittest.main()
