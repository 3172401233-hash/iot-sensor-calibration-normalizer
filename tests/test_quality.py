"""质量码归一化与重复读数测试。"""

import unittest

from sensor_normalizer import Normalizer
from sensor_normalizer.errors import DuplicateConflictError, UnknownDeviceError

from tests._helpers import (
    make_device,
    make_reading,
    register_identity_calibration,
    utc,
)


class QualityCodeTest(unittest.TestCase):
    def setUp(self):
        self.normalizer = Normalizer()
        self.normalizer.register_device(make_device())
        register_identity_calibration(self.normalizer)

    def test_mapped_good_and_bad_codes(self):
        good = self.normalizer.ingest(make_reading("r-good", quality_code="OK"))
        bad = self.normalizer.ingest(make_reading("r-bad", quality_code="FAIL"))
        uncertain = self.normalizer.ingest(
            make_reading("r-warn", quality_code="WARN")
        )

        self.assertEqual(good.normalized.quality_status, "GOOD")
        self.assertEqual(bad.normalized.quality_status, "BAD")
        self.assertIsNone(bad.normalized.temperature_celsius)
        self.assertIsNotNone(bad.normalized.raw_temperature_celsius)
        self.assertEqual(uncertain.normalized.quality_status, "UNCERTAIN")
        self.assertIn("SENSOR_WARN", uncertain.normalized.quality_flags)

    def test_unknown_quality_code_is_bad(self):
        result = self.normalizer.ingest(
            make_reading("r-unknown", quality_code="MYSTERY")
        )
        self.assertEqual(result.normalized.quality_status, "BAD")
        self.assertIn("INVALID_QUALITY_CODE", result.normalized.quality_flags)
        self.assertIsNone(result.normalized.temperature_celsius)

    def test_unknown_device_rejected(self):
        with self.assertRaises(UnknownDeviceError):
            self.normalizer.ingest(make_reading(device_id="ghost"))


class DuplicateReadingTest(unittest.TestCase):
    def setUp(self):
        self.normalizer = Normalizer()
        self.normalizer.register_device(make_device())
        register_identity_calibration(self.normalizer)
        self.first = self.normalizer.ingest(make_reading())

    def test_exact_duplicate_is_idempotent(self):
        repeat = self.normalizer.ingest(make_reading())
        self.assertTrue(repeat.duplicate)
        self.assertEqual(
            repeat.normalized.checksum, self.first.normalized.checksum
        )
        self.assertEqual(len(self.normalizer.store.all_raw()), 1)
        self.assertEqual(
            len(self.normalizer.store.get_revisions("r-1")), 1
        )

    def test_same_id_different_payload_rejected(self):
        with self.assertRaises(DuplicateConflictError):
            self.normalizer.ingest(make_reading(value=42.0))
        self.assertEqual(len(self.normalizer.store.all_raw()), 1)

    def test_duplicate_after_correction_returns_latest_revision(self):
        from tests._helpers import make_calibration

        late = make_calibration(
            "cal-2", 2, utc(2026, 1, 1), None, intercept=1.0,
            received_at=utc(2026, 1, 20),
        )
        self.normalizer.register_calibration(late)
        repeat = self.normalizer.ingest(make_reading())
        self.assertTrue(repeat.duplicate)
        self.assertEqual(repeat.normalized.revision, 2)
        self.assertEqual(repeat.normalized.temperature_celsius, 11.0)


if __name__ == "__main__":
    unittest.main()
