"""Hardware-free regression tests for the current SafetySense behavior."""

from __future__ import annotations

import builtins
import importlib.util
import io
import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


class FakeSerialPort:
    def __init__(self, data: bytes = b"") -> None:
        self.data = bytearray(data)

    def read(self, size: int = 1) -> bytes:
        result = bytes(self.data[:size])
        del self.data[:size]
        return result


def load_runtime():
    config_text = (ROOT / "config.json").read_text(encoding="utf-8")
    real_open = builtins.open

    def config_open(file, *args, **kwargs):
        normalized = str(file).replace("\\", "/")
        if normalized in {"/opt/safety_sense/config.json", "opt/safety_sense/config.json"}:
            return io.StringIO(config_text)
        return real_open(file, *args, **kwargs)

    serial_module = types.SimpleNamespace(
        SerialException=type("SerialException", (Exception,), {}),
        Serial=lambda *args, **kwargs: FakeSerialPort(),
    )
    lgpio_module = types.SimpleNamespace()
    module_name = "safety_sense_under_test"
    spec = importlib.util.spec_from_file_location(module_name, ROOT / "safety_sense.py")
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"serial": serial_module, "lgpio": lgpio_module}), mock.patch(
        "builtins.open", side_effect=config_open
    ):
        assert spec.loader is not None
        spec.loader.exec_module(module)
    return module


RUNTIME = load_runtime()
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def frame(distance: int, strength: int = 100, valid_checksum: bool = True) -> bytes:
    payload = [
        0x59,
        0x59,
        distance & 0xFF,
        (distance >> 8) & 0xFF,
        strength & 0xFF,
        (strength >> 8) & 0xFF,
        0,
        0,
    ]
    checksum = sum(payload) & 0xFF
    if not valid_checksum:
        checksum = (checksum + 1) & 0xFF
    return bytes(payload + [checksum])


class DistanceBehaviorTests(unittest.TestCase):
    def test_current_zone_boundaries(self):
        zones = CONFIG["zones"]
        self.assertEqual(RUNTIME.zone_label(zones["clear_cm"] + 1), "CLEAR")
        self.assertEqual(RUNTIME.zone_label(zones["clear_cm"]), "FAR")
        self.assertEqual(RUNTIME.zone_label(zones["far_cm"]), "MID")
        self.assertEqual(RUNTIME.zone_label(zones["near_cm"]), "SOLID")

    def test_current_buzzer_outputs(self):
        zones = CONFIG["zones"]
        buzzer = CONFIG["buzzer"]
        self.assertEqual(RUNTIME.interpolate_freq(zones["clear_cm"] + 1), 0.0)
        self.assertEqual(RUNTIME.interpolate_freq(zones["clear_cm"]), buzzer["freq_far_hz"])
        self.assertEqual(RUNTIME.interpolate_freq(zones["far_cm"]), buzzer["freq_mid_hz"])
        self.assertIsNone(RUNTIME.interpolate_freq(zones["near_cm"]))

    def test_rolling_median(self):
        self.assertEqual(RUNTIME.rolling_median([300, 100, 200]), 200)
        self.assertEqual(RUNTIME.rolling_median([100, 200]), 150)


class UartFrameTests(unittest.TestCase):
    def read(self, data: bytes):
        sensor = RUNTIME.TFminiPlus.__new__(RUNTIME.TFminiPlus)
        sensor.ser = FakeSerialPort(data)
        return sensor.read()

    def test_valid_frame(self):
        self.assertEqual(self.read(frame(123, 456)), (123, 456))

    def test_parser_resynchronizes_after_noise(self):
        self.assertEqual(self.read(b"\x00\x59\x01" + frame(123, 456)), (123, 456))

    def test_bad_checksum_is_rejected(self):
        self.assertEqual(self.read(frame(123, valid_checksum=False)), (None, None))

    def test_zero_distance_is_clear_and_keeps_strength(self):
        expected = CONFIG["sensor"]["max_dist_cm"] + 1
        self.assertEqual(self.read(frame(0, 456)), (expected, 456))

    def test_beyond_maximum_is_clear(self):
        maximum = CONFIG["sensor"]["max_dist_cm"]
        self.assertEqual(self.read(frame(maximum + 50, 456)), (maximum + 1, 456))

    def test_below_minimum_is_rejected(self):
        minimum = CONFIG["sensor"]["min_dist_cm"]
        self.assertEqual(self.read(frame(minimum - 1, 456)), (None, None))


class ZoneFilterTests(unittest.TestCase):
    def test_commits_after_required_consecutive_frames(self):
        zone_filter = RUNTIME.ZoneFilter(hysteresis=3, min_hold=0)
        self.assertIsNone(zone_filter.update("CLEAR"))
        self.assertIsNone(zone_filter.update("CLEAR"))
        self.assertEqual(zone_filter.update("CLEAR"), "CLEAR")
        self.assertEqual(zone_filter.committed_zone, "CLEAR")

    def test_candidate_count_resets_when_zone_changes(self):
        zone_filter = RUNTIME.ZoneFilter(hysteresis=2, min_hold=0)
        self.assertIsNone(zone_filter.update("CLEAR"))
        self.assertIsNone(zone_filter.update("FAR"))
        self.assertEqual(zone_filter.update("FAR"), "FAR")

    def test_minimum_hold_delays_a_new_commit(self):
        zone_filter = RUNTIME.ZoneFilter(hysteresis=1, min_hold=1.0)
        with mock.patch.object(RUNTIME.time, "monotonic", side_effect=[0.0, 0.5, 1.0]):
            self.assertEqual(zone_filter.update("CLEAR"), "CLEAR")
            self.assertIsNone(zone_filter.update("FAR"))
            self.assertEqual(zone_filter.update("FAR"), "FAR")


if __name__ == "__main__":
    unittest.main()
