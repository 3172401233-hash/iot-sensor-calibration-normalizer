"""校准边界、迟到校准、多次修订与更正批次测试。"""

import unittest

from sensor_normalizer import Normalizer
from sensor_normalizer.errors import CalibrationError, DuplicateConflictError

from tests._helpers import make_calibration, make_device, make_reading, utc


class CalibrationBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.normalizer = Normalizer()
        self.normalizer.register_device(make_device())

    def test_half_open_interval_uses_right_calibration(self):
        first = make_calibration(
            "cal-1", 1, utc(2026, 1, 1), utc(2026, 1, 5), slope=1.0, intercept=0.0
        )
        second = make_calibration(
            "cal-2", 2, utc(2026, 1, 5), None, slope=2.0, intercept=1.0
        )
        self.normalizer.register_calibration(first)
        self.normalizer.register_calibration(second)

        on_boundary = self.normalizer.ingest(
            make_reading("r-boundary", value=10.0, device_timestamp=utc(2026, 1, 5))
        ).normalized
        before_boundary = self.normalizer.ingest(
            make_reading("r-before", value=10.0, device_timestamp=utc(2026, 1, 4, 23, 59, 59))
        ).normalized

        self.assertEqual(on_boundary.calibration_id, "cal-2")
        self.assertEqual(on_boundary.temperature_celsius, 21.0)
        self.assertEqual(before_boundary.calibration_id, "cal-1")
        self.assertEqual(before_boundary.temperature_celsius, 10.0)

    def test_missing_calibration_marks_uncalibrated(self):
        result = self.normalizer.ingest(make_reading())
        self.assertEqual(result.normalized.quality_status, "UNCERTAIN")
        self.assertIn("UNCALIBRATED", result.normalized.quality_flags)
        self.assertIsNone(result.normalized.calibration_id)
        self.assertAlmostEqual(
            result.normalized.temperature_celsius,
            result.normalized.raw_temperature_celsius,
        )

    def test_overlapping_intervals_prefer_highest_version(self):
        old = make_calibration("cal-1", 1, utc(2026, 1, 1), None, intercept=1.0)
        new = make_calibration(
            "cal-2",
            2,
            utc(2026, 1, 1),
            None,
            intercept=2.0,
            received_at=utc(2026, 1, 12),
        )
        self.normalizer.register_calibration(old)
        self.normalizer.register_calibration(new)
        result = self.normalizer.ingest(make_reading(value=10.0))
        self.assertEqual(result.normalized.calibration_id, "cal-2")
        self.assertEqual(result.normalized.temperature_celsius, 12.0)

    def test_invalid_interval_rejected(self):
        bad = make_calibration("cal-bad", 1, utc(2026, 1, 5), utc(2026, 1, 1))
        with self.assertRaises(CalibrationError):
            self.normalizer.register_calibration(bad)

    def test_duplicate_version_rejected(self):
        self.normalizer.register_calibration(
            make_calibration("cal-1", 1, utc(2026, 1, 1))
        )
        with self.assertRaises(CalibrationError):
            self.normalizer.register_calibration(
                make_calibration("cal-other", 1, utc(2026, 1, 2))
            )


class LateCalibrationTest(unittest.TestCase):
    def setUp(self):
        self.normalizer = Normalizer()
        self.normalizer.register_device(make_device())
        self.normalizer.register_calibration(
            make_calibration("cal-1", 1, utc(2026, 1, 1), None, intercept=0.0)
        )
        for index, day in enumerate((2, 6, 9), start=1):
            self.normalizer.ingest(
                make_reading(
                    f"r-{index}",
                    value=10.0,
                    device_timestamp=utc(2026, 1, day),
                    ingested_at=utc(2026, 1, day + 1),
                )
            )

    def test_late_calibration_creates_scoped_correction_batch(self):
        late = make_calibration(
            "cal-2",
            2,
            utc(2026, 1, 5),
            utc(2026, 1, 8),
            slope=1.0,
            intercept=5.0,
            received_at=utc(2026, 1, 20),
        )
        batch = self.normalizer.register_calibration(late)

        self.assertIsNotNone(batch)
        self.assertEqual(batch.affected_reading_ids, ("r-2",))
        self.assertEqual(batch.affected_from, utc(2026, 1, 6))
        self.assertEqual(batch.affected_to, utc(2026, 1, 6))
        self.assertEqual(len(batch.superseded_reading_ids), 1)

        corrected = self.normalizer.store.get_current("r-2")
        self.assertEqual(corrected.revision, 2)
        self.assertEqual(corrected.temperature_celsius, 15.0)
        self.assertEqual(corrected.calibration_id, "cal-2")
        self.assertIn("CORRECTED", corrected.quality_flags)

        untouched = self.normalizer.store.get_current("r-1")
        self.assertEqual(untouched.revision, 1)
        self.assertEqual(untouched.temperature_celsius, 10.0)

    def test_raw_evidence_never_overwritten(self):
        before = self.normalizer.store.get_raw("r-1")
        late = make_calibration(
            "cal-2", 2, utc(2026, 1, 1), None, intercept=5.0,
            received_at=utc(2026, 1, 20),
        )
        self.normalizer.register_calibration(late)
        after = self.normalizer.store.get_raw("r-1")
        self.assertEqual(before, after)
        self.assertEqual(len(self.normalizer.store.all_raw()), 3)

        conflicting = make_reading(
            "r-1", value=99.0, device_timestamp=utc(2026, 1, 2)
        )
        with self.assertRaises(DuplicateConflictError):
            self.normalizer.ingest(conflicting)

    def test_superseded_chain_points_to_replacement(self):
        late = make_calibration(
            "cal-2", 2, utc(2026, 1, 1), None, intercept=5.0,
            received_at=utc(2026, 1, 20),
        )
        batch = self.normalizer.register_calibration(late)
        old = self.normalizer.store.get_revisions("r-1")[0]
        new = self.normalizer.store.get_current("r-1")
        self.assertEqual(old.superseded_by, new.checksum)
        self.assertIn(old.checksum, batch.superseded_reading_ids)
        self.assertIn(new.checksum, batch.checksums)
        self.assertIsNone(new.superseded_by)

    def test_multiple_revisions_accumulate(self):
        first_late = make_calibration(
            "cal-2", 2, utc(2026, 1, 1), None, intercept=1.0,
            received_at=utc(2026, 1, 20),
        )
        second_late = make_calibration(
            "cal-3", 3, utc(2026, 1, 1), None, intercept=2.0,
            received_at=utc(2026, 1, 21),
        )
        self.normalizer.register_calibration(first_late)
        self.normalizer.register_calibration(second_late)

        revisions = self.normalizer.store.get_revisions("r-1")
        self.assertEqual([item.revision for item in revisions], [1, 2, 3])
        self.assertEqual(
            [item.temperature_celsius for item in revisions], [10.0, 11.0, 12.0]
        )
        self.assertEqual(revisions[0].superseded_by, revisions[1].checksum)
        self.assertEqual(revisions[1].superseded_by, revisions[2].checksum)
        self.assertIsNone(revisions[2].superseded_by)

    def test_register_calibration_is_idempotent(self):
        late = make_calibration(
            "cal-2", 2, utc(2026, 1, 1), None, received_at=utc(2026, 1, 20)
        )
        first_batch = self.normalizer.register_calibration(late)
        second_batch = self.normalizer.register_calibration(late)
        self.assertEqual(first_batch, second_batch)
        self.assertEqual(len(self.normalizer.store.all_batches()), 1)
        revisions = self.normalizer.store.get_revisions("r-1")
        self.assertEqual(len(revisions), 2)

    def test_batch_not_created_when_no_affected_reading(self):
        future = make_calibration(
            "cal-future",
            2,
            utc(2030, 1, 1),
            None,
            received_at=utc(2026, 1, 20),
        )
        self.assertIsNone(self.normalizer.register_calibration(future))
        self.assertEqual(self.normalizer.store.all_batches(), [])

    def test_bad_quality_reading_included_in_correction_scope(self):
        bad_reading = make_reading(
            "r-bad",
            quality_code="FAIL",
            device_timestamp=utc(2026, 1, 6),
            ingested_at=utc(2026, 1, 7),
        )
        self.normalizer.ingest(bad_reading)
        late = make_calibration(
            "cal-2",
            2,
            utc(2026, 1, 1),
            None,
            intercept=5.0,
            received_at=utc(2026, 1, 20),
        )
        batch = self.normalizer.register_calibration(late)
        self.assertIn("r-bad", batch.affected_reading_ids)
        corrected = self.normalizer.store.get_current("r-bad")
        self.assertEqual(corrected.revision, 2)
        self.assertIsNone(corrected.temperature_celsius)
        self.assertEqual(corrected.quality_status, "BAD")
        self.assertIn("CORRECTED", corrected.quality_flags)


if __name__ == "__main__":
    unittest.main()
