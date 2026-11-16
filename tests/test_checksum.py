"""校验和、证据链完整性与批次幂等测试。"""

import unittest

from sensor_normalizer.checksum import canonical_json, sha256_hex
from sensor_normalizer.models import NormalizedReading

from tests._helpers import make_calibration, make_device, make_reading, utc
from sensor_normalizer import Normalizer


class ChecksumTest(unittest.TestCase):
    def test_canonical_json_is_deterministic(self):
        payload = {"b": 2, "a": [1, 2], "nested": {"z": 1, "y": 2}}
        self.assertEqual(
            canonical_json(payload), canonical_json({"nested": {"y": 2, "z": 1}, "a": [1, 2], "b": 2})
        )

    def test_normalized_checksum_recomputes_from_body(self):
        normalizer = Normalizer()
        normalizer.register_device(make_device())
        result = normalizer.ingest(make_reading())
        reading = result.normalized
        body = {
            "reading_id": reading.reading_id,
            "device_id": reading.device_id,
            "timestamp_utc": reading.timestamp_utc,
            "time_precision": reading.time_precision,
            "temperature_celsius": reading.temperature_celsius,
            "raw_temperature_celsius": reading.raw_temperature_celsius,
            "unit": reading.unit,
            "quality_status": reading.quality_status,
            "quality_flags": reading.quality_flags,
            "calibration_id": reading.calibration_id,
            "calibration_version": reading.calibration_version,
            "source_checksum": reading.source_checksum,
            "revision": reading.revision,
        }
        self.assertEqual(sha256_hex(body), reading.checksum)

    def test_tampered_value_breaks_checksum(self):
        normalizer = Normalizer()
        normalizer.register_device(make_device())
        reading = normalizer.ingest(make_reading()).normalized
        tampered = NormalizedReading(
            reading_id=reading.reading_id,
            device_id=reading.device_id,
            timestamp_utc=reading.timestamp_utc,
            time_precision=reading.time_precision,
            temperature_celsius=999.0,
            raw_temperature_celsius=reading.raw_temperature_celsius,
            unit=reading.unit,
            quality_status=reading.quality_status,
            quality_flags=reading.quality_flags,
            calibration_id=reading.calibration_id,
            calibration_version=reading.calibration_version,
            source_checksum=reading.source_checksum,
            revision=reading.revision,
            superseded_by=reading.superseded_by,
            checksum=reading.checksum,
        )
        body = {
            "reading_id": tampered.reading_id,
            "device_id": tampered.device_id,
            "timestamp_utc": tampered.timestamp_utc,
            "time_precision": tampered.time_precision,
            "temperature_celsius": tampered.temperature_celsius,
            "raw_temperature_celsius": tampered.raw_temperature_celsius,
            "unit": tampered.unit,
            "quality_status": tampered.quality_status,
            "quality_flags": tampered.quality_flags,
            "calibration_id": tampered.calibration_id,
            "calibration_version": tampered.calibration_version,
            "source_checksum": tampered.source_checksum,
            "revision": tampered.revision,
        }
        self.assertNotEqual(sha256_hex(body), tampered.checksum)

    def test_evidence_checksum_stable_through_corrections(self):
        normalizer = Normalizer()
        normalizer.register_device(make_device())
        normalizer.register_calibration(
            make_calibration("cal-1", 1, utc(2026, 1, 1))
        )
        first = normalizer.ingest(make_reading())
        raw_checksum = first.raw_evidence.checksum

        for version, intercept in ((2, 1.0), (3, 2.0)):
            normalizer.register_calibration(
                make_calibration(
                    f"cal-{version}",
                    version,
                    utc(2026, 1, 1),
                    None,
                    intercept=intercept,
                    received_at=utc(2026, 1, 20 + version),
                )
            )

        evidence = normalizer.store.get_raw("r-1")
        self.assertEqual(evidence.checksum, raw_checksum)
        for revision in normalizer.store.get_revisions("r-1"):
            self.assertEqual(revision.source_checksum, raw_checksum)

    def test_batch_checksum_covers_full_correction_scope(self):
        normalizer = Normalizer()
        normalizer.register_device(make_device())
        normalizer.register_calibration(
            make_calibration("cal-1", 1, utc(2026, 1, 1))
        )
        for index in range(3):
            normalizer.ingest(
                make_reading(
                    f"r-{index}",
                    device_timestamp=utc(2026, 1, 2 + index),
                )
            )
        late = make_calibration(
            "cal-2", 2, utc(2026, 1, 1), None, intercept=3.0,
            received_at=utc(2026, 1, 20),
        )
        batch = normalizer.register_calibration(late)
        content = {
            "calibration_id": batch.calibration_id,
            "device_id": batch.device_id,
            "affected_from": batch.affected_from,
            "affected_to": batch.affected_to,
            "affected_reading_ids": batch.affected_reading_ids,
            "superseded_reading_ids": batch.superseded_reading_ids,
            "checksums": batch.checksums,
            "created_at": batch.created_at,
        }
        self.assertEqual(sha256_hex(content), batch.checksum)
        self.assertEqual(batch.batch_id, f"BATCH-{batch.checksum[:16]}")

        repeat = normalizer.register_calibration(late)
        self.assertEqual(repeat, batch)


if __name__ == "__main__":
    unittest.main()
