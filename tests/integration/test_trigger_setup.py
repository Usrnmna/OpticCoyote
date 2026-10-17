"""Configuration evidence tests with synthetic filesystem metadata, without hardware."""
import io
import json
from pathlib import Path
import stat
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import check_trigger_setup as setup

CAMERA = setup.selector.validate({
    **json.loads((ROOT / "rpi-ahd-selector/config.json").read_text()), "trigger_enabled": True,
})
REVERSE = {**setup.reverse_control.load_config(ROOT / "rpi-oled-bridge/reverse.json"), "reverse_gpio_pin": 22}
DEVICE_PATHS = ["sensor", "display", "/dev/video0", "/dev/video2"]


def metadata(number, mode=stat.S_IFCHR):
    return SimpleNamespace(st_mode=mode, st_dev=1, st_ino=number + 100, st_rdev=number)


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.nodes = {path: metadata(index + 1) for index, path in enumerate(DEVICE_PATHS)}

    def check(self, camera=None, buzzer=None):
        def inspect(path):
            value = self.nodes.get(path, FileNotFoundError(path))
            if isinstance(value, Exception):
                raise value
            return value
        with patch.object(setup.os, "stat", side_effect=inspect):
            return setup.check_assignments(camera or CAMERA, REVERSE, "sensor", "display", buzzer)

    def test_all_character_device_metadata_can_complete_configuration_check(self):
        result = self.check()
        self.assertEqual(result["result"], "NO_CONFLICTS_IN_INSPECTED_ASSIGNMENTS")
        self.assertEqual(result["device_issues"], [])
        self.assertIn("no hardware tests", result["limits"])

    def test_missing_dangling_permission_and_stat_errors_remain_distinct(self):
        for error, exists, expected in (
            (FileNotFoundError("missing"), False, "MISSING"),
            (FileNotFoundError("target absent"), True, "DANGLING_LINK"),
            (PermissionError("denied"), False, "INACCESSIBLE"),
            (OSError("device error"), False, "STAT_ERROR"),
            (NotADirectoryError("parent is file"), False, "STAT_ERROR"),
        ):
            with self.subTest(expected=expected, error=error), patch.object(setup.os.path, "lexists", return_value=exists):
                self.nodes["sensor"] = error
                report = self.check()
                self.assertEqual(report["result"], "INCOMPLETE")
                self.assertEqual(report["device_issues"][0]["status"], expected)
                self.assertIn("sensor", report["unresolved_paths"])

    def test_regular_files_directories_and_block_devices_cannot_pass(self):
        for mode in (stat.S_IFREG, stat.S_IFDIR, stat.S_IFBLK):
            with self.subTest(mode=mode):
                self.nodes["sensor"] = metadata(1, mode)
                report = self.check()
                self.assertEqual(report["result"], "INCOMPLETE")
                self.assertEqual(report["device_issues"][0]["status"], "NOT_CHARACTER_DEVICE")

    def test_distinct_names_and_inodes_for_same_character_device_are_conflicts(self):
        self.nodes["display"] = metadata(1)
        self.nodes["display"].st_ino = 999
        self.nodes["display"].st_dev = 44
        with self.assertRaisesRegex(ValueError, "Device conflict"):
            self.check()

    def test_inode_alias_is_conflict_even_if_metadata_not_character_device(self):
        self.nodes["sensor"] = metadata(1, stat.S_IFREG)
        self.nodes["display"] = metadata(1, stat.S_IFREG)
        with self.assertRaisesRegex(ValueError, "Device conflict"):
            self.check()

    def test_known_linear_capture_forms_are_inspectable(self):
        for fragment in (
            'v4l2src device="/dev/video0" do-timestamp=true ! decodebin',
            "v4l2src device=/dev/video0 ! image/jpeg,width=1280,height=720,framerate=60/1 ! jpegdec",
            "v4l2src device=/dev/video0 ! video/x-raw,format=YUY2,width=1280,height=720,framerate=10/1",
        ):
            with self.subTest(fragment=fragment):
                report = self.check({**CAMERA, "sources": [fragment, *CAMERA["sources"][1:]]})
                self.assertEqual(report["sources_requiring_manual_inspection"], [])
                self.assertEqual(report["result"], "NO_CONFLICTS_IN_INSPECTED_ASSIGNMENTS")

    def test_complex_sources_never_pass_based_on_a_single_v4l2_token(self):
        for fragment in (
            "v4l2src device=/dev/video0 ! tee name=t t. ! filesink location=hidden",
            "v4l2src device=/dev/video0 ! decodebin filesrc location=hidden",
            "v4l2src device=/dev/video0 ! queue ! decodebin",
            "v4l2src device=/dev/video0 extra-controls=anything ! decodebin",
            "v4l2src device=/dev/video0 do-timestamp=true do-timestamp=false ! decodebin",
            "v4l2src device=/dev/video0 ! image/jpeg,width=1280,width=640 ! jpegdec",
            "v4l2src device=/dev/video0 ! image/jpeg-malformed ! jpegdec",
            "v4l2src device=/dev/video0 ! decodebin !",
            "( v4l2src device=/dev/video0 ! decodebin )",
            "v4l2src device=/dev/video0 ! decodebin name=d",
            "filesrc location=sensor ! decodebin",
            'v4l2src device="/dev/video0 ! filesrc location=hidden" ! decodebin',
        ):
            with self.subTest(fragment=fragment):
                report = self.check({**CAMERA, "sources": [fragment, *CAMERA["sources"][1:]]})
                self.assertEqual(report["sources_requiring_manual_inspection"], [1])
                self.assertEqual(report["result"], "INCOMPLETE")

    def test_explicit_conflict_in_complex_pipeline_is_still_detected(self):
        with self.assertRaisesRegex(ValueError, "Device conflict"):
            self.check({**CAMERA, "sources": ["v4l2src device=sensor ! queue ! decodebin", *CAMERA["sources"][1:]]})

    def test_custom_sinks_require_review(self):
        for sink in ("filesink location=sensor", "autovideosink", "kmssink device=sensor",
                     "kmssink ! filesink location=hidden", "kmssink fd=4", "kmssink name=custom"):
            with self.subTest(sink=sink):
                report = self.check({**CAMERA, "sink": sink})
                self.assertTrue(report["sink_requires_manual_inspection"])
                self.assertEqual(report["result"], "INCOMPLETE")
        self.assertFalse(self.check({**CAMERA, "sink": "fakesink sync=false"})["sink_requires_manual_inspection"])

    def test_disabled_unconfigured_buzzer_is_reported_and_assigned_pin_is_reserved(self):
        report = self.check(buzzer={"enabled": False, "hardware_type": None, "gpio_pin": None})
        self.assertEqual(report["result"], "NO_CONFLICTS_IN_INSPECTED_ASSIGNMENTS")
        self.assertTrue(report["buzzer_unconfigured"])
        for pin in (17, 27, 22):
            with self.subTest(pin=pin), self.assertRaisesRegex(ValueError, "buzzer"):
                self.check(buzzer={"enabled": False, "hardware_type": None, "gpio_pin": pin})
        self.assertEqual(self.check(buzzer={"enabled": False, "hardware_type": "active", "gpio_pin": 18})["gpio_bcm"]["buzzer"], 18)

    def test_cli_complete_incomplete_and_conflict_exit_statuses(self):
        configs = {"camera": json.dumps(CAMERA), "reverse": json.dumps(REVERSE)}
        args = ["--selector-config", "camera", "--reverse-config", "reverse", "--sensor-port", "sensor", "--display-port", "display"]
        for expected in (0, 1, 2):
            if expected == 1:
                self.nodes["sensor"] = FileNotFoundError("missing")
            if expected == 2:
                args[-1] = "sensor"
            def inspect(path):
                result = self.nodes[path]
                if isinstance(result, Exception):
                    raise result
                return result
            with self.subTest(expected=expected), \
                    patch.object(Path, "read_text", autospec=True, side_effect=lambda path, **_: configs[str(path)]), \
                    patch.object(setup.os, "stat", side_effect=inspect), \
                    patch("sys.stdout", new_callable=io.StringIO) as output, \
                    patch("sys.stderr", new_callable=io.StringIO):
                self.assertEqual(setup.main(args), expected)
                if expected != 2:
                    self.assertEqual(json.loads(output.getvalue())["result"], "INCOMPLETE" if expected else "NO_CONFLICTS_IN_INSPECTED_ASSIGNMENTS")

    def test_cli_optional_buzzer_uses_real_validator_and_reserves_disabled_pins(self):
        buzzer = json.loads((ROOT / "rpi-buzzer/buzzer.json").read_text())
        args = ["--selector-config", "camera", "--reverse-config", "reverse", "--sensor-port", "sensor",
                "--display-port", "display", "--buzzer-config", "buzzer"]
        for change, expected in (({}, 0), ({"gpio_pin": 17}, 2), ({"gpio_pin": 18, "hardware_type": "passive"}, 0),
                                 ({"enabled": True}, 2), ({"hardware_type": "unknown"}, 2)):
            configs = {"camera": json.dumps(CAMERA), "reverse": json.dumps(REVERSE), "buzzer": json.dumps({**buzzer, **change})}
            with self.subTest(change=change), \
                    patch.object(Path, "read_text", autospec=True, side_effect=lambda path, **_: configs[str(path)]), \
                    patch.object(setup.os, "stat", side_effect=self.nodes.__getitem__), \
                    patch("sys.stdout", new_callable=io.StringIO) as output, \
                    patch("sys.stderr", new_callable=io.StringIO):
                self.assertEqual(setup.main(args), expected)
                if expected == 0:
                    report = json.loads(output.getvalue())
                    self.assertTrue(report["buzzer_checked"])
                    self.assertEqual(report["buzzer_unconfigured"], not bool(change))

    def test_duplicate_json_settings_cannot_receive_complete_verdict(self):
        args = ["--selector-config", "camera", "--reverse-config", "reverse",
                "--sensor-port", "sensor", "--display-port", "display"]
        for role in ("camera", "reverse"):
            configs = {"camera": json.dumps(CAMERA), "reverse": json.dumps(REVERSE)}
            configs[role] = configs[role][:-1] + ',"' + (
                'trigger_left_pin":18}' if role == "camera" else 'reverse_gpio_pin":18}')
            with self.subTest(role=role), \
                    patch.object(Path, "read_text", autospec=True, side_effect=lambda path, **_: configs[str(path)]), \
                    patch("sys.stderr", new_callable=io.StringIO) as errors:
                self.assertEqual(setup.main(args), 2)
            self.assertIn("Duplicate", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
