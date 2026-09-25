"""Software checks; no Arduino, Pi, GPIO voltage, or camera hardware exercised."""

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import itertools
import json
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import warning_receiver as receiver


class ReceiverTests(unittest.TestCase):
    def test_every_wire_combination(self):
        """Each single wire maps to its camera; all ambiguous combinations fail."""
        for values in itertools.product((False, True), repeat=4):
            with self.subTest(values=values):
                count = sum(values)
                expected = -1 if count > 1 else values.index(True) + 1 if count else 0
                self.assertEqual(receiver.decode_camera(values), expected)

    def test_incomplete_snapshot_rejected(self):
        with self.assertRaises(ValueError):
            receiver.decode_camera([True, False])

    def test_held_startup_warning_is_received_once(self):
        stable = receiver.StableCamera(0.03)
        self.assertIsNone(stable.update(3, 1.0))
        self.assertEqual(stable.update(3, 1.04), 3)
        self.assertIsNone(stable.update(3, 20.0))

    def test_switch_gap_and_bounce_do_not_publish_false_clear(self):
        stable = receiver.StableCamera(0.03)
        stable.update(1, 0.0)
        self.assertEqual(stable.update(1, 0.04), 1)
        for camera, now in [(0, 0.05), (2, 0.06), (0, 0.07), (2, 0.08)]:
            self.assertIsNone(stable.update(camera, now))
        self.assertEqual(stable.update(2, 0.12), 2)

    def test_clear_conflict_and_recovery_to_same_camera(self):
        stable = receiver.StableCamera(0.03)
        for camera, start in [(0, 0), (4, 1), (-1, 2), (4, 3), (0, 4)]:
            self.assertIsNone(stable.update(camera, start))
            self.assertEqual(stable.update(camera, start + 0.04), camera)

    def test_monitor_reads_pins_and_reports_only_changes(self):
        inputs = [SimpleNamespace(value=False) for _ in range(4)]
        samples = iter([(False, True, False, False), (False, True, False, False),
                        (False, False, False, False)])
        stop = Mock()
        stop.is_set.side_effect = [False, False, False, False, True]

        def advance(_):
            values = next(samples, (False,) * 4)
            for pin, value in zip(inputs, values):
                pin.value = value

        stop.wait.side_effect = advance
        with patch.object(receiver, "report_camera") as report:
            receiver.monitor(inputs, stop, 0.01, 0, False)
        self.assertEqual([call.args[0] for call in report.call_args_list], [0, 2, 0])

    def test_default_reports_are_plain_numbers(self):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            self.assertEqual(receiver.main(["--simulate", "0", "1", "4", "-1"]), 0)
        self.assertEqual(output.getvalue(), "0\n1\n4\n-1\n")
        self.assertIn("conflict", errors.getvalue())

    def test_commands_work_with_unchanged_camera_selector(self):
        """Use the real selector parser and state, without launching video."""
        path = Path(__file__).resolve().parents[1] / "rpi-ahd-selector" / "selector.py"
        spec = importlib.util.spec_from_file_location("existing_selector", path)
        selector = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(selector)
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(io.StringIO()):
            receiver.main(["--selector-json", "--simulate", "0", "1", "2", "3", "4", "-1", "0"])
        commands = output.getvalue().splitlines()
        self.assertEqual([json.loads(line)["camera"] for line in commands], [1, 2, 3, 4])
        state = selector.State(1)
        for expected, line in enumerate(commands, 1):
            reply = selector.apply_message(state, line)
            self.assertTrue(reply["ok"])
            self.assertEqual(reply["selected_camera"], expected)

    def test_bad_settings_rejected_before_gpio(self):
        cases = [["--pins", "17", "17", "22", "23"],
                 ["--pins", "17", "28", "22", "23"],
                 ["--sample-seconds", "0"], ["--sample-seconds", "nan"],
                 ["--debounce-seconds", "-1"], ["--debounce-seconds", "inf"],
                 ["--simulate", "5"]]
        for args in cases:
            with self.subTest(args=args), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    receiver.parse_args(args)
                self.assertEqual(error.exception.code, 2)

    def fake_gpio(self, device_factory, factory):
        """Supply only the GPIO interface used by the listener for cleanup tests."""
        return patch.dict("sys.modules", {
            "gpiozero": SimpleNamespace(DigitalInputDevice=device_factory),
            "gpiozero.pins": SimpleNamespace(),
            "gpiozero.pins.lgpio": SimpleNamespace(LGPIOFactory=lambda: factory),
        })

    def test_partial_gpio_open_failure_closes_earlier_pin_and_factory(self):
        pin, factory = Mock(), Mock()
        devices = Mock(side_effect=[pin, RuntimeError("pin busy")])
        with self.fake_gpio(devices, factory), self.assertRaisesRegex(RuntimeError, "pin busy"):
            receiver.listen(receiver.parse_args([]), threading.Event())
        pin.close.assert_called_once()
        factory.close.assert_called_once()

    def test_shutdown_closes_all_pins_with_expected_polarity(self):
        for active_high in (False, True):
            pins, factory = [Mock() for _ in range(4)], Mock()
            devices = Mock(side_effect=pins)
            args = receiver.parse_args(["--active-high"] if active_high else [])
            with self.fake_gpio(devices, factory), patch.object(receiver, "monitor"), redirect_stderr(io.StringIO()):
                receiver.listen(args, threading.Event())
            for pin in pins:
                pin.close.assert_called_once()
            factory.close.assert_called_once()
            self.assertEqual([call.args[0] for call in devices.call_args_list], [17, 27, 22, 23])
            self.assertTrue(all(call.kwargs["pull_up"] == (not active_high)
                                for call in devices.call_args_list))


if __name__ == "__main__":
    unittest.main()
