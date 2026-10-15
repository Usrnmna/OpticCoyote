"""Host-only diagnostic evidence tests; no V4L2 or Pi hardware is accessed."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import MagicMock
import types

import diagnose_adapter as diagnostic


CONFIG = json.loads(Path(__file__).with_name("diagnostic.json").read_text())
FORMATS = """ioctl: VIDIOC_ENUM_FMT
    Type: Video Capture
    [0]: 'MJPG' (Motion-JPEG, compressed)
        Size: Discrete 1280x720
            Interval: Discrete 0.017s (59.940 fps)
            Interval: Discrete 0.017s (60.000 fps)
        Size: Discrete 1920x1080
            Interval: Discrete 0.033s (30.000 fps)
    [1]: 'YUYV' (YUYV 4:2:2)
        Size: Discrete 1280x720
            Interval: Discrete 0.100s (10.000 fps)
"""


def measurement(phase="capture"):
    """Return synthetic complete evidence for classification tests only."""
    caps = {"media_type": "image/jpeg", "width": 1280, "height": 720,
            "fps_numerator": 60, "fps_denominator": 1}
    return {"phase": phase, "eos": True, "errors": [], "warnings": [],
            "caps": [caps], "output_caps": [{**caps, "media_type": "video/x-raw" if phase == "decode" else "image/jpeg"}],
            "input_buffers": 660, "invalid_input_buffers": 0, "timing_errors": 0,
            "measurement_intervals": 600, "max_buffer_gap_seconds": 1 / 60,
            "total_buffers": 660, "measured_buffers": 600,
            "measurement_seconds": 10, "measured_fps": 60,
            "empty_buffers": 0, "corrupted_buffers": 0}


def execution(output="", returncode=0, stderr="", timed_out=False):
    return {"command": ["synthetic"], "returncode": returncode, "stdout": output,
            "stderr": stderr, "timed_out": timed_out, "elapsed_seconds": 11,
            "cleanup_complete": True, "pid": 123}


class ConfigurationTests(unittest.TestCase):
    def test_defaults_and_invalid_settings(self):
        diagnostic.validate(CONFIG)
        for key, value in (("fps", True), ("fps", 59.94), ("width", 0),
                           ("measurement_buffers", 1), ("warmup_buffers", -1),
                           ("rate_tolerance_percent", float("nan")),
                           ("test_timeout_seconds", 11), ("device", "video0"),
                           ("device", "/dev/video0\n"), ("width", 10 ** 1000),
                           ("max_buffer_gap_seconds", 0), ("cleanup_timeout_seconds", float("inf"))):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                diagnostic.validate({**CONFIG, key: value})
        for config in ({}, [], {**CONFIG, "typo": 1}):
            with self.assertRaises(ValueError):
                diagnostic.validate(config)

    def test_check_config_from_another_directory_never_probes(self):
        script = Path(diagnostic.__file__).resolve()
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, str(script), "--check-config"],
                                    cwd=directory, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), CONFIG)

    def test_device_requires_explicit_selection(self):
        with patch.object(diagnostic, "diagnose") as diagnose, patch("sys.stderr"):
            with self.assertRaises(SystemExit) as error:
                diagnostic.main([])
        self.assertEqual(error.exception.code, 2)
        diagnose.assert_not_called()


class CapabilityTests(unittest.TestCase):
    def test_modes_are_scoped_to_format_and_size(self):
        modes = diagnostic.detected_modes(FORMATS)
        self.assertEqual(len(modes), 4)
        self.assertEqual(modes[0]["fps"], 59.94)
        self.assertEqual(modes[1]["fps"], 60)
        self.assertEqual(modes[2]["width"], 1920)
        self.assertEqual(modes[3]["fourcc"], "YUYV")

    def test_ranges_and_missing_size_cannot_inherit_old_mode(self):
        output = FORMATS + """
        Size: Stepwise 16x16 - 4096x2160 with step 2/2
            Interval: Discrete 0.017s (60.000 fps)
    [2]: 'H264'
            Interval: Discrete 0.017s (60.000 fps)
"""
        self.assertEqual(len(diagnostic.detected_modes(output)), 4)

    def test_detected_modes_never_pass_hardware_tests(self):
        with patch.object(diagnostic, "run_command", return_value=execution(FORMATS)) as run:
            report = diagnostic.diagnose({**CONFIG, "device": "/dev/video0"}, True)
        self.assertTrue(report["target_mode_detected"])
        self.assertEqual(run.call_count, 2)
        self.assertEqual([test["status"] for test in report["tests"].values()], ["SKIPPED", "SKIPPED"])
        text = diagnostic.render_report(report)
        self.assertIn("DETECTED CAPABILITIES (NOT HARDWARE TEST PASSES)", text)
        self.assertIn("CAPTURE: SKIPPED", text)

    def test_5994_and_failed_probes_do_not_confirm_60(self):
        for response in (execution(FORMATS.replace("60.000", "59.940")),
                         execution(FORMATS, returncode=1),
                         execution(FORMATS, timed_out=True)):
            with patch.object(diagnostic, "run_command", return_value=response):
                report = diagnostic.diagnose({**CONFIG, "device": "/dev/video0"}, True)
            self.assertFalse(report["target_mode_detected"])

    def test_malformed_driver_rate_remains_raw_evidence(self):
        self.assertEqual(len(diagnostic.detected_modes(FORMATS.replace("60.000", "..."))), 3)


class MeasurementTests(unittest.TestCase):
    def test_boundary_interval_after_warmup_is_included(self):
        counter = diagnostic.BufferMeasurements(2)
        for now in (0, 5, 20, 20.5, 21):
            counter.observe(now, 100)
        result = counter.result()
        self.assertEqual(result["total_buffers"], 5)
        self.assertEqual(result["measured_buffers"], 3)
        self.assertEqual(result["measurement_seconds"], 16)
        self.assertEqual(result["measured_fps"], 3 / 16)
        self.assertEqual(result["max_buffer_gap_seconds"], 15)

    def test_zero_warmup_uses_count_minus_one_intervals(self):
        counter = diagnostic.BufferMeasurements(0)
        for now in (0, 0.5, 1):
            counter.observe(now, 100)
        self.assertEqual(counter.result()["measurement_intervals"], 2)
        self.assertEqual(counter.result()["measured_fps"], 2)

    def test_clock_regression_is_retained(self):
        counter = diagnostic.BufferMeasurements(0)
        for now in (0, 0.5, 0.4, 1):
            counter.observe(now, 100)
        self.assertEqual(counter.result()["timing_errors"], 1)

    def test_empty_corrupted_and_missing_duration_preserved(self):
        counter = diagnostic.BufferMeasurements(1)
        counter.observe(0, 0, True)
        counter.observe(1, 100)
        counter.observe(1, 100)
        result = counter.result()
        self.assertEqual(result["measured_fps"], 2)
        self.assertEqual(result["empty_buffers"], 1)
        self.assertEqual(result["corrupted_buffers"], 1)


class ClassificationTests(unittest.TestCase):
    def classify(self, changes=None, **run_changes):
        result = {**measurement(), **(changes or {})}
        rate = result["measured_fps"]
        if type(rate) in (int, float) and rate > 0:
            result["measurement_seconds"] = 600 / rate
            result["max_buffer_gap_seconds"] = 1 / rate
        return diagnostic.evaluate(CONFIG, execution(json.dumps(result), **run_changes))["status"]

    def test_complete_evidence_and_tolerance(self):
        self.assertEqual(self.classify(), "PASS")
        self.assertEqual(self.classify({"measured_fps": 57}), "PASS")
        self.assertEqual(self.classify({"measured_fps": 56.99}), "FAIL")
        self.assertEqual(self.classify({"measured_fps": 64}), "FAIL")

    def test_incomplete_buffers_mode_eos_and_errors_fail(self):
        for changes in ({"eos": False}, {"total_buffers": 659}, {"measured_buffers": 599},
                        {"empty_buffers": 1}, {"corrupted_buffers": 1},
                        {"errors": ["decoder error"]}, {"caps": []}):
            with self.subTest(changes=changes):
                self.assertEqual(self.classify(changes), "FAIL")
        caps = copy.deepcopy(measurement()["caps"])
        caps[0].update(fps_numerator=60000, fps_denominator=1001)
        self.assertEqual(self.classify({"caps": caps}), "FAIL")

    def test_warning_stderr_timeout_and_missing_worker(self):
        self.assertEqual(self.classify({"warnings": ["lost frames"]}), "INCONCLUSIVE")
        self.assertEqual(self.classify(stderr="GStreamer warning"), "INCONCLUSIVE")
        self.assertEqual(self.classify(timed_out=True), "FAIL")
        self.assertEqual(self.classify(returncode=2), "INCONCLUSIVE")

    def test_missing_malformed_or_nonfinite_evidence_cannot_pass(self):
        for output in ("", "{}", "[]", "null", "garbage"):
            self.assertEqual(diagnostic.evaluate(CONFIG, execution(output))["status"], "INCONCLUSIVE")
        for fps in (None, True, float("nan"), float("inf")):
            self.assertEqual(self.classify({"measured_fps": fps}), "INCONCLUSIVE")
        for changes in ({"measurement_seconds": float("nan")}, {"measured_buffers": 600.0},
                        {"measurement_seconds": 1}, {"warnings": None}, {"measured_fps": 10 ** 1000}):
            output = json.dumps({**measurement(), **changes})
            self.assertEqual(diagnostic.evaluate(CONFIG, execution(output))["status"], "INCONCLUSIVE")

    def test_capture_pass_does_not_mask_decode_failure(self):
        responses = [execution("identity"), execution(FORMATS),
                     execution(json.dumps(measurement())),
                     execution(json.dumps({**measurement("decode"), "errors": ["bad JPEG"]}))]
        with patch.object(diagnostic, "run_command", side_effect=responses):
            report = diagnostic.diagnose({**CONFIG, "device": "/dev/video0"})
        self.assertEqual(report["tests"]["capture"]["status"], "PASS")
        self.assertEqual(report["tests"]["decode"]["status"], "FAIL")

    def test_correct_mean_rate_cannot_hide_a_stall(self):
        result = {**measurement(), "max_buffer_gap_seconds": 1.0}
        outcome = diagnostic.evaluate(CONFIG, execution(json.dumps(result)))
        self.assertEqual(outcome["status"], "FAIL")
        self.assertIn("stall", outcome["reason"])

    def test_plausibility_and_caps_types(self):
        for changes in ({"max_buffer_gap_seconds": float("nan")},
                        {"max_buffer_gap_seconds": 0.001}, {"max_buffer_gap_seconds": 11}):
            result = {**measurement(), **changes}
            self.assertEqual(diagnostic.evaluate(CONFIG, execution(json.dumps(result)))["status"], "INCONCLUSIVE")
        run = execution(json.dumps(measurement()))
        run["elapsed_seconds"] = 1
        self.assertEqual(diagnostic.evaluate(CONFIG, run)["status"], "INCONCLUSIVE")
        result = measurement()
        result["caps"][0]["fps_denominator"] = True
        self.assertEqual(diagnostic.evaluate(CONFIG, execution(json.dumps(result)))["status"], "INCONCLUSIVE")
        run = execution(json.dumps(measurement()))
        run["elapsed_seconds"] = CONFIG["test_timeout_seconds"] + 1
        self.assertEqual(diagnostic.evaluate(CONFIG, run)["status"], "FAIL")

    def test_zero_warmup_pass_requires_correct_interval_count(self):
        config = {**CONFIG, "warmup_buffers": 0}
        result = {**measurement(), "input_buffers": 600, "total_buffers": 600,
                  "measurement_intervals": 599, "measurement_seconds": 599 / 60}
        self.assertEqual(diagnostic.evaluate(config, execution(json.dumps(result)))["status"], "PASS")
        result["measurement_intervals"] = 600
        self.assertEqual(diagnostic.evaluate(config, execution(json.dumps(result)))["status"], "FAIL")

    def test_decode_requires_raw_output_correct_size_and_matching_phase(self):
        for changes in ({"phase": "capture"}, {"invalid_input_buffers": 1}, {"input_buffers": 659},
                        {"output_caps": measurement()["output_caps"]}):
            result = {**measurement("decode"), **changes}
            self.assertEqual(diagnostic.evaluate(CONFIG, execution(json.dumps(result)), "decode")["status"], "FAIL")
        result = measurement("decode")
        result["output_caps"][0]["width"] = 640
        self.assertEqual(diagnostic.evaluate(CONFIG, execution(json.dumps(result)), "decode")["status"], "FAIL")


class ExecutionTests(unittest.TestCase):
    def test_timeout_and_missing_executable_are_reported(self):
        process = MagicMock()
        process.returncode = -9
        process.communicate.side_effect = [subprocess.TimeoutExpired(["tool"], 1), ("partial", "")]
        with patch.object(subprocess, "Popen", return_value=process):
            result = diagnostic.run_command(["tool"], 1)
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["stdout"], "partial")
        self.assertTrue(result["cleanup_complete"])
        process.kill.assert_called_once()
        with patch.object(subprocess, "Popen", side_effect=FileNotFoundError("tool missing")):
            result = diagnostic.run_command(["tool"], 1)
        self.assertIsNone(result["returncode"])

    def test_unreaped_worker_blocks_further_device_operations(self):
        process = MagicMock()
        process.pid, process.returncode = 321, None
        process.communicate.side_effect = subprocess.TimeoutExpired(["worker"], 1, b"partial")
        with patch.object(subprocess, "Popen", return_value=process):
            failed = diagnostic.run_command(["worker"], 1, cleanup_timeout=0.2)
        self.assertFalse(failed["cleanup_complete"])
        process.communicate.assert_called_with(timeout=0.2)
        with patch.object(diagnostic, "run_command", side_effect=[execution(), execution(FORMATS), failed]) as run:
            report = diagnostic.diagnose({**CONFIG, "device": "/dev/video0"})
        self.assertEqual(run.call_count, 3)
        self.assertEqual(report["tests"]["capture"]["status"], "FAIL")
        self.assertEqual(report["tests"]["decode"]["status"], "SKIPPED")
        with patch.object(diagnostic, "run_command", return_value=failed) as run:
            report = diagnostic.diagnose({**CONFIG, "device": "/dev/video0"})
        self.assertEqual(run.call_count, 1)
        self.assertTrue(all(test["status"] == "SKIPPED" for test in report["tests"].values()))

    def test_interrupt_kills_and_reaps_before_propagation(self):
        process = MagicMock()
        process.communicate.side_effect = [KeyboardInterrupt(), ("", "")]
        with patch.object(subprocess, "Popen", return_value=process):
            with self.assertRaises(KeyboardInterrupt):
                diagnostic.run_command(["worker"], 1)
        process.kill.assert_called_once()
        self.assertEqual(process.communicate.call_count, 2)

    def test_slow_spawn_consumes_communication_budget(self):
        process = MagicMock()
        process.communicate.return_value = ("", "")
        process.returncode = 0
        with patch.object(subprocess, "Popen", return_value=process):
            with patch.object(diagnostic.time, "monotonic", side_effect=[0, 0.75, 0.9]):
                diagnostic.run_command(["worker"], 1)
        process.communicate.assert_called_once_with(input=None, timeout=0.25)

    def test_real_timed_out_child_is_reaped(self):
        original_popen = subprocess.Popen
        children = []

        def spawn(*args, **kwargs):
            child = original_popen(*args, **kwargs)
            children.append(child)
            return child

        with patch.object(subprocess, "Popen", side_effect=spawn):
            result = diagnostic.run_command([sys.executable, "-c", "import time; time.sleep(60)"], 0.2)
        self.assertTrue(result["timed_out"])
        self.assertTrue(result["cleanup_complete"])
        self.assertIsNotNone(children[0].poll())
        self.assertLess(result["elapsed_seconds"], 5)

    def test_report_files_and_exit_status(self):
        with patch.object(diagnostic, "run_command", return_value=execution(FORMATS)):
            report = diagnostic.diagnose({**CONFIG, "device": "/dev/video0"}, True)
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(diagnostic, "diagnose", return_value=report), patch("builtins.print"):
                status = diagnostic.main(["--device", "/dev/video0", "--capabilities-only", "--report-dir", directory])
            files = list(Path(directory).iterdir())
            self.assertEqual({path.suffix for path in files}, {".txt", ".json"})
            saved = json.loads(next(path for path in files if path.suffix == ".json").read_text())
        self.assertEqual(status, 1)
        self.assertEqual(saved, report)

    def test_zero_exit_requires_both_passes(self):
        with patch.object(diagnostic, "run_command", side_effect=[
                execution("identity"), execution(FORMATS),
                execution(json.dumps(measurement())), execution(json.dumps(measurement("decode")))]):
            report = diagnostic.diagnose({**CONFIG, "device": "/dev/video0"})
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(diagnostic, "diagnose", return_value=report), patch("builtins.print"):
                self.assertEqual(diagnostic.main(["--device", "/dev/video0", "--report-dir", directory]), 0)

    def run_fake_worker(self, output_width=1280, invalid_input=False, drop_output=False,
                        late_error=False, teardown_failure=False):
        # A fake Gst boundary exercises callback wiring and finite pipeline cleanup.
        # It does not substitute for a GStreamer/Pi integration test.
        gst = MagicMock()
        gst.State.PLAYING, gst.State.NULL, gst.StateChangeReturn.FAILURE = 1, 0, -1
        gst.MessageType.ERROR, gst.MessageType.WARNING, gst.MessageType.EOS = 1, 2, 4
        gst.SECOND = 1000000000
        gst.version_string.return_value = "synthetic Gst"
        pipeline, source, capsfilter, decoder, sink = [MagicMock() for _ in range(5)]
        gst.Pipeline.new.return_value = pipeline
        pipeline.get_state.return_value = (0, gst.State.NULL, 0)
        gst.ElementFactory.make.side_effect = [source, capsfilter, sink, decoder]
        caps = capsfilter.get_static_pad.return_value.get_current_caps.return_value
        caps.is_empty.return_value = False
        structure = caps.get_structure.return_value
        structure.get_fraction.return_value = (True, 60, 1)
        structure.get_name.return_value = "image/jpeg"
        structure.get_value.side_effect = lambda key: {"width": 1280, "height": 720}[key]
        output_pad = MagicMock()
        output_caps = output_pad.get_current_caps.return_value
        output_caps.is_empty.return_value = False
        output_structure = output_caps.get_structure.return_value
        output_structure.get_fraction.return_value = (True, 60, 1)
        output_structure.get_name.return_value = "video/x-raw"
        output_structure.get_value.side_effect = lambda key: {"width": output_width, "height": 720}[key]
        buffer = MagicMock()
        buffer.get_size.return_value = 100
        buffer.has_flags.return_value = False
        input_buffer = MagicMock()
        input_buffer.get_size.return_value = 100
        gst.BufferFlags.CORRUPTED, gst.BufferFlags.GAP, gst.BufferFlags.DECODE_ONLY = 1, 2, 4
        input_buffer.has_flags.side_effect = lambda flag: invalid_input and flag == gst.BufferFlags.GAP
        probe_info = MagicMock()
        probe_info.get_buffer.return_value = input_buffer

        def set_state(state):
            if state == gst.State.PLAYING:
                callback = sink.connect.call_args.args[1]
                probe = capsfilter.get_static_pad.return_value.add_probe.call_args.args[1]
                for index in range(660):
                    probe(capsfilter.get_static_pad.return_value, probe_info)
                    if not drop_output or index != 659:
                        callback(sink, buffer, output_pad)
            elif teardown_failure:
                return gst.StateChangeReturn.FAILURE
            return 0

        pipeline.set_state.side_effect = set_state
        eos = MagicMock()
        eos.type = gst.MessageType.EOS
        error = MagicMock()
        error.type = gst.MessageType.ERROR
        error.parse_error.return_value = ("late decoder error", "details")
        pipeline.get_bus.return_value.timed_pop_filtered.side_effect = [eos] + ([error] if late_error else []) + [None]
        repository = types.ModuleType("gi.repository")
        repository.Gst = gst
        with patch.dict(sys.modules, {"gi": MagicMock(), "gi.repository": repository}):
            with patch.object(diagnostic.time, "monotonic", side_effect=[i / 60 for i in range(660)]):
                result = diagnostic.hardware_worker({**CONFIG, "device": "/dev/video0"}, "decode")
        self.assertIn(unittest.mock.call("jpegdec", "decoder"), gst.ElementFactory.make.call_args_list)
        source.set_property.assert_any_call("device", "/dev/video0")
        pipeline.set_state.assert_called_with(gst.State.NULL)
        return result

    def test_worker_counts_actual_handoffs_and_tears_down(self):
        result = self.run_fake_worker()
        self.assertEqual(diagnostic.evaluate(CONFIG, execution(json.dumps(result)), "decode")["status"], "PASS")

    def test_worker_decoder_failure_paths_cannot_pass(self):
        for option in ({"output_width": 640}, {"invalid_input": True}, {"drop_output": True},
                       {"late_error": True}, {"teardown_failure": True}):
            with self.subTest(option=option):
                result = self.run_fake_worker(**option)
                self.assertEqual(diagnostic.evaluate(CONFIG, execution(json.dumps(result)), "decode")["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
