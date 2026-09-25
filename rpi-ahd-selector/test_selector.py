"""Offline contract tests; no Pi, capture device, GPIO or serial hardware needed.

Reading map: ControlTests covers input priority and JSON framing; ConfigTests
covers editable settings and dry-run validation; PlaybackTests covers process
switch/retry/debounce; SerialTests covers reconnect and command acknowledgements.
FakeProcess/FakeStop replace real processes and elapsed time for worker tests.
"""
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import types
import unittest
from unittest.mock import patch

import selector

CONFIG = json.loads(Path(__file__).with_name("config.json").read_text())


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.state = selector.State(3)

    def test_each_camera_input(self):
        for camera in range(1, 5):
            values = [int(i == camera) for i in range(1, 5)]
            self.assertEqual(selector.resolve_inputs(values, 3), camera)

    def test_priority_and_hold(self):
        self.assertEqual(selector.resolve_inputs([0, 0, 0, 0], 3), 3)
        self.assertEqual(selector.resolve_inputs([0, 1, 1, 1], 3), 2)

    def test_bad_inputs_do_not_change_state(self):
        for values in ([1, 2, 0, 0], [1, 0], None, "0001", [1.0, 0, 0, 0]):
            with self.assertRaises(ValueError):
                self.state.inputs(values)
            self.assertEqual(self.state.selected, 3)

    def test_commands_and_arbitration(self):
        self.assertTrue(selector.apply_message(self.state, '{"camera":4}')["ok"])
        self.state.inputs([0, 1, 0, 0])
        self.assertEqual(self.state.selected, 2)
        self.assertTrue(selector.apply_message(self.state, '{"camera":1}')["ok"])
        self.assertEqual(self.state.selected, 1)

    def test_bad_commands_do_not_change_selection(self):
        for line in ('{"camera":true}', '{"camera":0}', '{"camera":5}', '[]',
                     '{"status":1}', '{}', '{"camera":2,"inputs":[1,0,0,0]}',
                     '{', b'\xff', '{"inputs":[0,-1,0,0]}'):
            self.assertFalse(selector.apply_message(self.state, line)["ok"])
            self.assertEqual(self.state.selected, 3)

    def test_status_is_acceptance_not_frame_health(self):
        result = selector.apply_message(self.state, '{"status":true}')
        self.assertTrue(result["ok"])
        self.assertIsNone(result["pipeline_camera"])

    def test_split_and_batched_serial_commands(self):
        lines = selector.Lines()
        self.assertEqual(list(selector.responses(self.state, lines, b'{"cam')), [])
        replies = list(selector.responses(self.state, lines,
                       b'era":4}\r\n{"inputs":[0,1,0,0]}\n'))
        self.assertEqual(len(replies), 2)
        self.assertEqual(json.loads(replies[0])["selected_camera"], 4)
        self.assertEqual(self.state.selected, 2)

    def test_oversized_line_discards_its_entire_suffix(self):
        lines = selector.Lines()
        self.assertEqual(lines.feed(b'x' * 2000), [])
        replies = list(selector.responses(self.state, lines,
                       b'{"camera":1}\n{"camera":4}\n'))
        self.assertFalse(json.loads(replies[0])["ok"])
        self.assertEqual(self.state.selected, 4)
        self.assertLessEqual(len(lines.buffer), 1024)

    def test_command_generator(self):
        result = subprocess.run([sys.executable, str(Path(__file__).with_name("control.py")),
                                 "--inputs", "0", "0", "1", "0"],
                                capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), {"inputs": [0, 0, 1, 0]})


class ConfigTests(unittest.TestCase):
    def test_default_config_is_local_and_live_only(self):
        selector.validate(CONFIG)
        for camera in range(1, 5):
            args = selector.command(CONFIG, camera)
            self.assertIn("v4l2src", args)
            self.assertIn("kmssink", args)
            self.assertIn("watchdog", args)
            self.assertFalse(any("rtsp" in arg or "filesink" in arg for arg in args))
            self.assertIn("video/x-raw,width=1280,height=720,pixel-aspect-ratio=1/1,framerate=60/1", args)

    def test_demo_requires_no_capture_devices(self):
        args = selector.command(CONFIG, 2, demo=True, headless=True)
        self.assertIn("videotestsrc", args)
        self.assertIn("fakesink", args)
        self.assertNotIn("v4l2src", args)
        self.assertNotIn("kmssink", args)

    def test_invalid_config(self):
        for field, value in (("initial_camera", True), ("sources", []),
                             ("gpio_pins", None), ("gpio_pins", [17, 17, 22, 23]),
                             ("gpio_pins", [17, 27, 22, 99]), ("gpio_active_low", 1),
                             ("serial_baud", -1), ("serial_port", ""),
                             ("serial_port", "/dev/ttyUSB0\0"), ("sink", ""),
                             ("sink", "kmssink\0")):
            config = copy.deepcopy(CONFIG)
            config[field] = value
            with self.assertRaises(ValueError, msg=field):
                selector.validate(config)

    def test_older_config_gets_unchanged_defaults_without_mutation(self):
        config = {"initial_camera": 1, "sources": CONFIG["sources"]}
        result = selector.validate(config)
        self.assertEqual(set(config), {"initial_camera", "sources"})
        for key, value in selector.DEFAULTS.items():
            self.assertEqual(result[key], value, key)
        self.assertEqual(selector.command(result, 1), selector.command(CONFIG, 1))

    def test_config_typos_and_bad_pipeline_quotes_are_named(self):
        cases = [({**CONFIG, "output_fsp": 30}, "output_fsp"),
                 ({**CONFIG, "sink": 'kmssink name="unfinished'}, "sink"),
                 ({**CONFIG, "sources": ['v4l2src device="unfinished'] + CONFIG["sources"][1:]},
                  "sources[0]")]
        for config, name in cases:
            with self.subTest(name=name), self.assertRaises(ValueError) as error:
                selector.validate(config)
            self.assertIn(name, str(error.exception))

    def test_numeric_limits_reject_invalid_types_nonfinite_and_out_of_range(self):
        for name, (minimum, maximum, integer_only) in selector.NUMERIC_LIMITS.items():
            invalid = [True, None, "1", float("nan"), float("inf"), float("-inf"),
                       minimum - 1, maximum + 1]
            if integer_only:
                invalid.append(float(minimum))
            for value in invalid:
                with self.subTest(name=name, value=value):
                    with self.assertRaises(ValueError) as error:
                        selector.validate({**CONFIG, name: value})
                    self.assertIn(name, str(error.exception))
            for value in (minimum, maximum):
                with self.subTest(name=name, boundary=value):
                    self.assertEqual(selector.validate({**CONFIG, name: value})[name], value)

    def test_output_tuning_changes_generated_pipeline(self):
        config = selector.validate({**CONFIG, "output_width": 640, "output_height": 480,
                                    "output_fps": 30, "watchdog_timeout_ms": 1500})
        args = selector.command(config, 1)
        self.assertIn("video/x-raw,width=640,height=480,pixel-aspect-ratio=1/1,framerate=30/1", args)
        self.assertIn("timeout=1500", args)

    def test_check_config_reports_effective_settings_without_device_dependencies(self):
        config = {"initial_camera": 1, "sources": CONFIG["sources"],
                  "gpio_pins": [17, 27, 22, 23], "serial_port": "/dev/ttyUSB0"}
        with patch.object(Path, "read_text", return_value=json.dumps(config)), \
             patch.object(selector.shutil, "which", side_effect=AssertionError("dependency check")), \
             patch.object(selector.subprocess, "Popen", side_effect=AssertionError("process start")), \
             patch.dict(sys.modules, {"serial": None, "gpiozero": None}), \
             patch.object(sys, "stdout", new_callable=io.StringIO) as output:
            selector.main(["--check-config"])
        report = json.loads(output.getvalue())
        self.assertEqual(report["config"]["output_fps"], 60)
        self.assertEqual(report["config"]["serial_port"], "/dev/ttyUSB0")
        self.assertEqual(len(report["pipelines"]), 4)
        self.assertIn("device=/dev/video6", report["pipelines"][3])

    def test_demo_headless_check_still_rejects_original_bad_pipelines(self):
        for field in ("sources", "sink"):
            config = copy.deepcopy(CONFIG)
            if field == "sources":
                config[field][0] = 'v4l2src device="unfinished'
            else:
                config[field] = 'kmssink name="unfinished'
            with self.subTest(field=field), \
                 patch.object(Path, "read_text", return_value=json.dumps(config)), \
                 patch.object(sys, "stderr", new_callable=io.StringIO) as errors:
                with self.assertRaises(SystemExit) as exit_result:
                    selector.main(["--check-config", "--demo", "--headless"])
                self.assertEqual(exit_result.exception.code, 2)
                self.assertIn(field, errors.getvalue())


class FakeProcess:
    """Small Popen substitute that records termination and avoids OS processes."""
    def __init__(self):
        self.returncode = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


class FakeStop:
    """Event substitute advancing one deterministic worker tick on each wait."""
    def __init__(self, callback, limit=5):
        self.ticks = 0
        self.callback = callback
        self.limit = limit

    def is_set(self):
        return self.ticks >= self.limit

    def wait(self, seconds):
        self.ticks += 1
        self.callback(self.ticks)
        return self.is_set()


class PlaybackTests(unittest.TestCase):
    def test_switch_stops_old_capture_and_cleanup_stops_new(self):
        state = selector.State(1)
        first, second = FakeProcess(), FakeProcess()
        stop = FakeStop(lambda tick: state.select(4) if tick == 1 else None)
        with patch.object(selector.subprocess, "Popen", side_effect=[first, second]) as start:
            selector.player(state, CONFIG, stop)
        self.assertEqual(start.call_count, 2)
        self.assertIn("device=/dev/video6", start.call_args_list[1].args[0])
        self.assertTrue(first.terminated)
        self.assertTrue(second.terminated)
        self.assertIsNone(state.snapshot()["pipeline_camera"])

    def test_failed_camera_can_be_switched_without_waiting_for_retry(self):
        state = selector.State(1)
        first, second = FakeProcess(), FakeProcess()
        def tick(count):
            if count == 1:
                first.returncode = 1
            if count == 2:
                state.select(2)
        stop = FakeStop(tick)
        with patch.object(selector.subprocess, "Popen", side_effect=[first, second]) as start:
            selector.player(state, CONFIG, stop)
        self.assertEqual(start.call_count, 2)
        self.assertIn("device=/dev/video2", start.call_args_list[1].args[0])

    def test_failed_pipeline_retries_same_selection(self):
        state = selector.State(1)
        first, second = FakeProcess(), FakeProcess()
        stop = FakeStop(lambda tick: setattr(first, "returncode", 1) if tick == 1 else None,
                        limit=7)
        with patch.object(selector.time, "monotonic", side_effect=lambda: stop.ticks), \
             patch.object(selector.subprocess, "Popen", side_effect=[first, second]) as start:
            selector.player(state, CONFIG, stop)
        self.assertEqual(start.call_count, 2)
        self.assertEqual(start.call_args_list[0], start.call_args_list[1])

    def test_custom_retry_delay_controls_restart_time(self):
        state = selector.State(1)
        first, second = FakeProcess(), FakeProcess()
        stop = FakeStop(lambda tick: setattr(first, "returncode", 1) if tick == 1 else None,
                        limit=7)
        started_at = []
        processes = iter([first, second])
        def start(*args):
            started_at.append(stop.ticks)
            return next(processes)
        with patch.object(selector.time, "monotonic", side_effect=lambda: stop.ticks), \
             patch.object(selector.subprocess, "Popen", side_effect=start):
            selector.player(state, {**CONFIG, "retry_delay_seconds": 4}, stop)
        self.assertEqual(started_at, [0, 5])

    def test_kills_unresponsive_capture(self):
        process = FakeProcess()
        with patch.object(process, "wait", side_effect=[subprocess.TimeoutExpired("gst", 2), -9]):
            selector.stop_process(process)
        self.assertTrue(process.killed)

    def test_gpio_debounce_and_release_hold(self):
        state = selector.State(1)
        buttons = [type("Button", (), {"is_pressed": False})() for _ in range(4)]
        def tick(count):
            buttons[2].is_pressed = 2 <= count < 12
        stop = FakeStop(tick, limit=20)
        with patch.object(selector.time, "monotonic", side_effect=lambda: stop.ticks * 0.01):
            selector.poll_gpio(state, buttons, stop)
        self.assertEqual(state.selected, 3)

    def test_custom_gpio_timing_rejects_short_pulse_and_accepts_stable_input(self):
        state = selector.State(1)
        buttons = [type("Button", (), {"is_pressed": False})() for _ in range(4)]
        selections = []
        intervals = []
        def tick(count):
            selections.append(state.selected)
            buttons[2].is_pressed = 2 <= count < 4 or 7 <= count
        stop = FakeStop(tick, limit=16)
        original_wait = stop.wait
        def wait(seconds):
            intervals.append(seconds)
            return original_wait(seconds)
        stop.wait = wait
        with patch.object(selector.time, "monotonic", side_effect=lambda: stop.ticks * 0.02):
            selector.poll_gpio(state, buttons, stop,
                               {"gpio_sample_seconds": 0.02, "gpio_debounce_seconds": 0.06})
        self.assertEqual(selections[:7], [1] * 7)
        self.assertEqual(state.selected, 3)
        self.assertTrue(all(value == 0.02 for value in intervals))


class SerialTests(unittest.TestCase):
    def test_serial_disconnect_reconnect_and_command_acknowledgement(self):
        state = selector.State(1)
        stop = FakeStop(lambda _: None, limit=2)
        writes = []
        class Port:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, size):
                return b'{"inputs":[0,0,0,1]}\n'

            def write(self, reply):
                writes.append(json.loads(reply))
                stop.ticks = 2

        class Disconnected(OSError):
            pass

        from unittest.mock import Mock
        constructor = Mock(side_effect=[Disconnected("unplugged"), Port()])
        module = types.SimpleNamespace(Serial=constructor, SerialException=Disconnected)
        with patch.dict(sys.modules, {"serial": module}):
            selector.serial_control(state, {"serial_port": "/dev/ttyUSB0"}, stop)
        self.assertEqual(constructor.call_count, 2)
        self.assertEqual(state.selected, 4)
        self.assertTrue(writes[0]["ok"])
        self.assertEqual(writes[0]["selected_camera"], 4)

    def test_custom_serial_timeouts_and_reconnect_delay(self):
        from unittest.mock import Mock
        state = selector.State(1)
        stop = types.SimpleNamespace(is_set=Mock(side_effect=[False, True]), wait=Mock())
        constructor = Mock(side_effect=OSError("unplugged"))
        module = types.SimpleNamespace(Serial=constructor, SerialException=OSError)
        config = {**CONFIG, "serial_port": "/dev/ttyUSB0", "serial_baud": 9600,
                  "serial_read_timeout_seconds": 0.25, "serial_write_timeout_seconds": 0.75,
                  "retry_delay_seconds": 3}
        with patch.dict(sys.modules, {"serial": module}):
            selector.serial_control(state, config, stop)
        constructor.assert_called_once_with("/dev/ttyUSB0", 9600, timeout=0.25, write_timeout=0.75)
        stop.wait.assert_called_once_with(3)


if __name__ == "__main__":
    unittest.main()
