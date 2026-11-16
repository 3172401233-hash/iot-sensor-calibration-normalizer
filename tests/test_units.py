"""单位换算测试。"""

import unittest

from sensor_normalizer.errors import UnknownUnitError
from sensor_normalizer.units import canonical_unit, to_celsius


class UnitConversionTest(unittest.TestCase):
    def test_celsius_alias_normalization(self):
        for alias in ("celsius", "C", " °C ", "DEG C", "degree_celsius"):
            with self.subTest(alias=alias):
                self.assertEqual(canonical_unit(alias), "celsius")

    def test_fahrenheit_to_celsius(self):
        self.assertAlmostEqual(to_celsius(32.0, "fahrenheit"), 0.0)
        self.assertAlmostEqual(to_celsius(212.0, "F"), 100.0)
        self.assertAlmostEqual(to_celsius(-40.0, "degF"), -40.0)

    def test_kelvin_to_celsius(self):
        self.assertAlmostEqual(to_celsius(273.15, "kelvin"), 0.0)
        self.assertAlmostEqual(to_celsius(373.15, "K"), 100.0)

    def test_unknown_unit_raises(self):
        with self.assertRaises(UnknownUnitError):
            to_celsius(1.0, "rankine")

    def test_normalizer_uses_device_unit(self):
        from sensor_normalizer import Normalizer

        from tests._helpers import make_device, make_reading, utc

        normalizer = Normalizer()
        normalizer.register_device(make_device(unit="fahrenheit"))
        result = normalizer.ingest(
            make_reading(value=50.0, device_timestamp=utc(2026, 1, 5))
        )
        self.assertAlmostEqual(
            result.normalized.temperature_celsius, 10.0, places=9
        )
        self.assertEqual(result.normalized.unit, "celsius")


if __name__ == "__main__":
    unittest.main()
