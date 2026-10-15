"""Diagnostic evidence/false-PASS checks; simulated I/O is not bench evidence."""
import io
import json
from pathlib import Path
import subprocess
import signal
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock

import diagnose_reverse as diagnostic
import reverse_control as reverse
from test_reverse_control import Clock, Port, CONFIG, ARGS


SETTINGS = diagnostic.load_settings(diagnostic.DEFAULT_CONFIG)


def finish_quiet_window(audit):
    """Supply simulated polling coverage after release at t=1, through t=2.5."""
    audit.begin_observation(1)
    for ms in range(1000, 2501, 5):
        audit.input(False, ms / 1000)
        for role in ("sensor", "display"):
            audit.poll(role, ms / 1000, empty=True)


class ReportTests(unittest.TestCase):
    def test_input_reset_cannot_stitch_a_partial_ack_across_connections(self):
        audit = diagnostic.Audit(CONFIG, SETTINGS)
        audit.input(False, 0)
        audit.input(True, 0.1)
        audit.write("sensor", b"R,42,1500\n", 0.3, 0.3, (True, 0.1))
        audit.write("display", b"R,99,1500\n", 0.3, 0.3, (True, 0.1))
        audit.read("display", b"A,99,", 0.4)
        diagnostic.ObservedPort(Port(Clock()), "display", audit).reset_input_buffer()
        audit.read("display", b"0\n", 0.5)
        self.assertEqual(audit.display_acks, 0)
        audit.read("display", b"A,99,0\n", 0.6)
        self.assertEqual(audit.display_acks, 1)

    def test_fault_invalidates_display_ack_ownership_without_resetting_sensor(self):
        audit = diagnostic.Audit(CONFIG, SETTINGS)
        audit.input(False, 0)
        audit.input(True, 0.1)
        audit.write("sensor", b"R,42,1500\n", 0.3, 0.3, (True, 0.1))
        audit.write("display", b"R,99,1500\n", 0.3, 0.3, (True, 0.1))
        session = audit.session
        audit.display_fault(OSError("OLED disconnected"))
        audit.read("display", b"A,99,0\n", 0.5)
        self.assertEqual(audit.display_acks, 0)
        self.assertIs(audit.session, session)
        self.assertIsNone(audit.display_session)

    def test_silent_ack_expiry_then_idle_reopen_cannot_stitch_a_passing_cycle(self):
        clock = Clock(3500)
        config = {**CONFIG, "boot_ms": 0, "reconnect_ms": 200}
        settings = {**SETTINGS, "max_observation_gap_ms": 5000}
        audit = diagnostic.Audit(config, settings, clock.now)
        audit.begin_observation(0)
        sensor, first, replacement = Port(clock, True), Port(clock), Port(clock)
        for port in (sensor, first, replacement):
            port.close = lambda port=port: setattr(port, "closed", True)

        def silence_after_first_renewal(packet):
            if packet.startswith(b"K,"):
                first.reply = False
        first.on_write = silence_after_first_renewal
        display = reverse.DisplayLink(config, port=diagnostic.ObservedPort(first, "display", audit),
                                      open_port=lambda: diagnostic.ObservedPort(replacement, "display", audit),
                                      on_fault=audit.display_fault)

        def read_gpio():
            high = 50 <= clock.ms < 100 or 200 <= clock.ms < 1700
            audit.input(high, clock.now())
            return high

        with patch("sys.stderr", new_callable=io.StringIO):
            reverse.pump(diagnostic.ObservedPort(sensor, "sensor", audit), display, ARGS, config,
                         clock, reverse.ReverseGate(0.1), read_gpio, clock.now, new_token=lambda: 42)
        report = audit.report(audit.complete())
        self.assertTrue(audit.complete())
        self.assertEqual(audit.observation_gaps, 0)
        self.assertTrue(first.closed)
        self.assertFalse(any(b"R," in packet for _, packet in replacement.writes))
        self.assertTrue(all(item["status"] == "PASS" for item in report["checks"][:-1]), report)
        self.assertEqual(report["checks"][-1]["status"], "FAIL")
        self.assertTrue(any("Display acknowledgement expired" in error for error in report["errors"]))
        display.close()

    def test_display_ack_history_is_independent_of_sensor_requests_and_token(self):
        audit = diagnostic.Audit(CONFIG, SETTINGS)
        audit.input(False, 0)
        audit.input(True, 0.1)
        audit.write("sensor", b"R,42,1500\n", 0.3, 0.3, (True, 0.1))
        audit.write("display", b"R,99,1500\n", 0.3, 0.3, (True, 0.1))
        audit.write("sensor", b"K,42,1\n", 0.4, 0.4, (True, 0.1))
        audit.read("display", b"A,42,1\nA,99,1\n", 0.5)
        self.assertEqual(audit.display_acks, 0)
        audit.write("display", b"K,99,1\n", 0.6, 0.6, (True, 0.1))
        audit.read("display", b"A,99,1\n", 0.7)
        self.assertEqual(audit.display_acks, 1)
        audit.read("sensor", b"S,42,1,400,305,0,610,0,914,0,1219,0\n", 0.7)
        audit.write("display", b"D,99,305,610,914,1219\n", 0.7, 0.7, (True, 0.1))
        self.assertEqual(audit.fresh_distance_packets, 1)
        self.assertEqual(audit.invalid_distance_packets, 0)

    def test_absorbed_display_io_faults_remain_visible_in_diagnostic_report(self):
        audit = diagnostic.Audit(CONFIG, SETTINGS)
        class FaultPort:
            @property
            def in_waiting(self):
                raise OSError("poll failed")
            def read(self, _count):
                raise OSError("read failed")
            def reset_input_buffer(self):
                raise OSError("reset failed")
        port = diagnostic.ObservedPort(FaultPort(), "display", audit)
        for operation in (lambda: port.in_waiting, lambda: port.read(1), port.reset_input_buffer):
            with self.assertRaises(OSError):
                operation()
        self.assertEqual(len(audit.errors), 3)
        self.assertEqual(audit.report(True)["checks"][-1]["status"], "FAIL")

    def test_software_checks_pass_without_hardware_imports(self):
        checks = diagnostic.software_checks(CONFIG)
        self.assertEqual(len(checks), 3)
        self.assertTrue(all(item["status"] == "PASS" for item in checks))
        with patch.object(reverse.SensorSession, "receive", return_value=False):
            self.assertIn("FAIL", [item["status"] for item in diagnostic.software_checks(CONFIG)])

    def test_no_input_no_packets_or_cleanup_alone_cannot_pass(self):
        audit = diagnostic.Audit(CONFIG, SETTINGS, lambda: 2)
        for role in ("sensor", "display"):
            audit.write(role, b"\nX\n", 1, 1.1, (False, None))
        report = audit.report(False)
        self.assertFalse(any(item["status"] == "PASS" for item in report["checks"]))
        self.assertEqual(report["checks"][-1]["status"], "FAIL")

    def test_real_pump_with_simulated_ports_produces_required_observations(self):
        clock = Clock(2600)
        audit = diagnostic.Audit(CONFIG, SETTINGS, clock.now)
        audit.begin_observation(0)
        sensor, display = (diagnostic.ObservedPort(Port(clock, role == "sensor"), role, audit)
                           for role in ("sensor", "display"))

        def read_gpio():
            high = 50 <= clock.ms < 100 or 200 <= clock.ms < 800
            audit.input(high, clock.now())
            return high

        with patch("sys.stderr", new_callable=io.StringIO):
            reverse.pump(sensor, display, ARGS, CONFIG, clock, reverse.ReverseGate(0.1),
                         read_gpio, clock.now, new_token=lambda: 42)
        report = audit.report(audit.complete())
        self.assertTrue(all(item["status"] == "PASS" for item in report["checks"]), report)
        self.assertEqual(audit.short_pulses, 1)
        self.assertEqual(audit.fresh_sensors, {1, 2, 3, 4})

    def test_no_short_pulse_leaves_the_required_check_unmeasured(self):
        audit = diagnostic.Audit(CONFIG, SETTINGS)
        check = next(item for item in audit.report(True)["checks"] if item["name"] == "short_high_rejected")
        self.assertEqual(check["status"], "NOT_TESTED")

    def test_initial_high_is_failure(self):
        audit = diagnostic.Audit(CONFIG, SETTINGS)
        audit.low_edge(-0.01)
        audit.input(True, 0)
        self.assertEqual(audit.report(False)["checks"][0]["status"], "FAIL")

    def test_ack_is_not_oled_proof_and_all_invalid_sensors_are_not_four_good_sensors(self):
        audit = diagnostic.Audit(CONFIG, SETTINGS)
        audit.input(False, 0)
        audit.input(True, 0.1)
        audit.write("sensor", b"R,42,1500\n", 0.3, 0.3, (True, 0.1))
        audit.write("display", b"R,42,1500\n", 0.3, 0.3, (True, 0.1))
        audit.read("sensor", b"S,42,0,100,-1,0,-1,0,-1,0,-1,0\n", 0.4)
        audit.read("display", b"A,42,0\nA,42,0\n", 0.4)
        self.assertEqual(audit.sensor_packets, 1)
        self.assertEqual(audit.display_acks, 1)
        checks = {item["name"]: item for item in audit.report(False)["checks"]}
        self.assertEqual(checks["four_sensor_values"]["status"], "FAIL")
        self.assertIn("OLED pixels not measured", checks["display_controller_usb"]["detail"])

    def test_low_during_an_inflight_write_is_not_an_early_high(self):
        clock = Clock()
        audit = diagnostic.Audit(CONFIG, SETTINGS, clock.now)
        audit.input(False, 0)
        audit.input(True, 0.1)
        clock.ms = 250
        raw = Port(clock, True)
        raw.on_write = lambda _data: audit.input(False, 0.26)
        diagnostic.ObservedPort(raw, "sensor", audit).write(b"R,42,1500\n")
        self.assertEqual(audit.early_starts, 0)
        self.assertEqual(audit.post_low_commands, 0)
        self.assertEqual(audit.low_at, 0.26)

    def test_post_low_commands_and_late_release_fail(self):
        audit = diagnostic.Audit(CONFIG, SETTINGS)
        audit.low_at = 1
        audit.write("display", b"D,42,1,2,3,4\n", 1.1, 1.1, (False, None))
        for role in ("sensor", "display"):
            audit.write(role, b"X\n", 1.4, 1.4, (False, None))
        checks = {item["name"]: item for item in audit.report(True)["checks"]}
        self.assertEqual(checks["low_release_writes"]["status"], "FAIL")

    def test_post_settle_telemetry_fails_quiet_check(self):
        for chunk in (b"S,old,damaged\n", b"S,42,0,", b"x" * 300, b"305,610,914,1219\n"):
            with self.subTest(chunk=chunk):
                audit = diagnostic.Audit(CONFIG, SETTINGS)
                audit.released = {"sensor": 1, "display": 1}
                audit.read("sensor", chunk, 1.6)
                finish_quiet_window(audit)
                check = next(item for item in audit.report(True)["checks"] if item["name"] == "telemetry_quiet_after_low")
                self.assertEqual(check["status"], "FAIL")
                self.assertEqual(audit.quiet_bytes, len(chunk))

    def test_partial_write_and_close_error_are_not_hidden(self):
        audit = diagnostic.Audit(CONFIG, SETTINGS)
        raw = Mock()
        raw.write.return_value = 1
        raw.close.side_effect = OSError("close failed")
        port = diagnostic.ObservedPort(raw, "sensor", audit)
        with self.assertRaises(OSError):
            port.write(b"X\n")
        with self.assertRaises(OSError):
            port.__exit__()
        self.assertEqual(len(audit.errors), 2)
        self.assertEqual(audit.report(True)["checks"][-1]["status"], "FAIL")

    def test_cleanup_time_cannot_complete_an_expired_observation_window(self):
        clock = Clock()
        audit = diagnostic.Audit(CONFIG, SETTINGS, clock.now)
        audit.released = {"sensor": 1, "display": 1}
        stop = diagnostic.DeadlineStop(audit, 2)
        clock.ms = 2000
        self.assertTrue(stop.is_set())
        clock.ms = 3000
        finish_quiet_window(audit)
        self.assertTrue(audit.complete())
        self.assertTrue(stop.is_set())
        self.assertEqual(stop.reason, "deadline")

    def test_quiet_check_requires_release_and_elapsed_observation(self):
        audit = diagnostic.Audit(CONFIG, SETTINGS, lambda: 0)
        check = next(item for item in audit.report(True)["checks"] if item["name"] == "telemetry_quiet_after_low")
        self.assertEqual(check["status"], "NOT_TESTED")

    def test_scheduler_stall_cannot_substitute_for_quiet_observation(self):
        clock = Clock()
        audit = diagnostic.Audit(CONFIG, SETTINGS, clock.now)
        audit.released = {"sensor": 1, "display": 1}
        audit.begin_observation(1)
        clock.ms = 3000
        self.assertFalse(audit.complete())
        audit.input(False, 3)
        audit.poll("sensor", 3, empty=True)
        self.assertFalse(audit.complete())
        audit.poll("display", 3, empty=True)
        self.assertTrue(audit.complete())
        checks = {item["name"]: item for item in audit.report(True)["checks"]}
        self.assertEqual(checks["observation_continuity"]["status"], "FAIL")
        self.assertEqual(checks["telemetry_quiet_after_low"]["status"], "FAIL")

    def test_gpio_read_overtaken_by_low_cannot_extend_high(self):
        clock = Clock()
        audit = diagnostic.Audit(CONFIG, SETTINGS, clock.now)
        audit.input(False, 0)
        audit.input(True, 0.1)

        def read():
            audit.low_edge(0.15)
            clock.ms = 300
            return True

        self.assertFalse(audit.sample(read))
        self.assertFalse(audit.high)
        self.assertEqual(audit.short_pulses, 1)
        audit.sample(lambda: True)
        self.assertEqual(audit.high_since, 0.3)

    def test_backdated_low_cannot_count_as_short_high(self):
        audit = diagnostic.Audit(CONFIG, SETTINGS)
        audit.input(True, 0.3)
        audit.low_edge(0.2)
        self.assertEqual(audit.short_pulses, 0)

    def test_fresh_slots_cannot_accumulate_across_invalid_snapshots(self):
        audit = diagnostic.Audit(CONFIG, SETTINGS)
        audit.write("sensor", b"R,42,1500\n", 0, 0, (True, -1))
        audit.read("sensor", b"S,42,0,100,305,0,610,0,-1,0,-1,0\n", 0.1)
        audit.read("sensor", b"S,42,0,200,-1,0,-1,0,914,0,1219,0\n", 0.2)
        checks = {item["name"]: item for item in audit.report(False)["checks"]}
        self.assertEqual(checks["four_sensor_values"]["status"], "FAIL")

    def test_late_replies_after_low_cannot_satisfy_active_checks(self):
        audit = diagnostic.Audit(CONFIG, SETTINGS)
        audit.write("sensor", b"R,42,1500\n", 0, 0, (True, -1))
        audit.low_at = 0.05
        audit.read("sensor", b"S,42,0,100,305,0,610,0,914,0,1219,0\n", 0.1)
        audit.read("display", b"A,42,0\n", 0.1)
        self.assertEqual((audit.sensor_packets, audit.display_acks), (0, 0))

    def test_stale_or_wrong_distance_write_cannot_pass(self):
        for at, packet in ((2, b"D,42,305,610,914,1219\n"), (0.2, b"D,42,999,610,914,1219\n")):
            audit = diagnostic.Audit(CONFIG, SETTINGS)
            audit.write("sensor", b"R,42,1500\n", 0, 0, (True, -1))
            audit.read("sensor", b"S,42,0,100,305,0,610,0,914,0,1219,0\n", 0.1)
            audit.write("display", packet, at, at, (True, -1))
            check = next(item for item in audit.report(False)["checks"] if item["name"] == "distance_packets_written")
            self.assertEqual(check["status"], "FAIL")

    def test_delayed_ack_cannot_prompt_low_using_expired_sensor_slots(self):
        config = {**CONFIG, "distance_stale_ms": 100}
        audit = diagnostic.Audit(config, {**SETTINGS, "minimum_sensor_packets": 1, "minimum_display_acks": 1})
        audit.write("sensor", b"R,42,1500\n", 0, 0, (True, -1))
        audit.read("sensor", b"S,42,0,50,305,0,610,0,914,0,1219,0\n", 0.05)
        audit.write("display", b"D,42,305,610,914,1219\n", 0.06, 0.06, (True, -1))
        with patch("sys.stderr", new_callable=io.StringIO):
            audit.read("display", b"A,42,0\n", 0.2)
        self.assertFalse(audit.prompted_low)
        self.assertEqual(audit.fresh_sensors, set())

    def test_only_blank_distance_writes_cannot_pass(self):
        audit = diagnostic.Audit(CONFIG, SETTINGS)
        audit.write("sensor", b"R,42,1500\n", 0, 0, (True, -1))
        audit.read("sensor", b"S,42,0,100,305,0,610,0,914,0,1219,0\n", 0.1)
        audit.write("display", b"D,42,-1,-1,-1,-1\n", 0.2, 0.2, (True, -1))
        check = next(item for item in audit.report(False)["checks"] if item["name"] == "distance_packets_written")
        self.assertEqual(check["status"], "FAIL")


class SupervisionTests(unittest.TestCase):
    def setUp(self):
        self.args = SimpleNamespace(config=diagnostic.DEFAULT_CONFIG,
            reverse_config=diagnostic.DEFAULT_REVERSE_CONFIG, sensor_port="sensor", display_port="display")

    def test_timeout_kills_reaps_and_discards_partial_pass(self):
        process = Mock()
        process.communicate.side_effect = [subprocess.TimeoutExpired("worker", 1),
                                          subprocess.TimeoutExpired("worker", 1), ('{"outcome":"PASS"}', None)]
        with patch.object(diagnostic.subprocess, "Popen", return_value=process):
            report = diagnostic.supervised_hardware(self.args, CONFIG, SETTINGS)
        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        self.assertEqual(process.communicate.call_count, 3)
        self.assertEqual(report["checks"][-1]["status"], "FAIL")

    def test_unreaped_worker_is_explicit_failure(self):
        process = Mock()
        process.communicate.side_effect = subprocess.TimeoutExpired("worker", 1)
        process.wait.side_effect = subprocess.TimeoutExpired("worker", 1)
        with patch.object(diagnostic.subprocess, "Popen", return_value=process):
            report = diagnostic.supervised_hardware(self.args, CONFIG, SETTINGS)
        self.assertIn("could not be reaped", report["checks"][-1]["detail"])

    def test_repeated_interruptions_still_force_and_reap_worker(self):
        process = Mock(returncode=-9)
        process.communicate.side_effect = [subprocess.TimeoutExpired("worker", 1), KeyboardInterrupt(), KeyboardInterrupt()]
        process.wait.return_value = -9
        with patch.object(diagnostic.subprocess, "Popen", return_value=process):
            report = diagnostic.supervised_hardware(self.args, CONFIG, SETTINGS)
        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        process.wait.assert_called_once_with(timeout=SETTINGS["cleanup_timeout_seconds"])
        self.assertEqual(report["checks"][-1]["status"], "FAIL")

    def test_termination_exit_race_still_reaps_and_reports_failure(self):
        process = Mock(returncode=0)
        process.communicate.side_effect = [KeyboardInterrupt(), ("partial output", None)]
        process.terminate.side_effect = ProcessLookupError("already exited")
        with patch.object(diagnostic.subprocess, "Popen", return_value=process):
            report = diagnostic.supervised_hardware(self.args, CONFIG, SETTINGS)
        self.assertEqual(process.communicate.call_count, 2)
        self.assertEqual(report["checks"][-1]["status"], "FAIL")

    def test_parent_sigterm_uses_cleanup_and_restores_handlers(self):
        original = {signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)}
        process = Mock(returncode=0)

        def interrupted(**_kwargs):
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)

        process.communicate.side_effect = [KeyboardInterrupt(), ("", None)]
        with patch.object(diagnostic.subprocess, "Popen", return_value=process):
            with diagnostic.termination_signals(diagnostic.interrupt_supervisor):
                with self.assertRaises(KeyboardInterrupt):
                    interrupted()
            diagnostic.supervised_hardware(self.args, CONFIG, SETTINGS)
        process.terminate.assert_called_once()
        self.assertEqual({signum: signal.getsignal(signum) for signum in original}, original)

    def test_actual_host_child_is_terminated_and_reaped(self):
        # This child has no device access; termination is host process evidence only.
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], stdout=subprocess.PIPE)
        try:
            self.assertTrue(diagnostic.stop_worker(child, 1))
            self.assertIsNotNone(child.poll())
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=3)
            child.stdout.close()

    def test_sigterm_during_spawn_is_deferred_until_worker_can_be_reaped(self):
        process = Mock(returncode=0)
        process.communicate.return_value = ("ignored", None)

        def spawn(*_args, **_kwargs):
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
            return process

        with patch.object(diagnostic.subprocess, "Popen", side_effect=spawn):
            report = diagnostic.supervised_hardware(self.args, CONFIG, SETTINGS)
        process.terminate.assert_called_once()
        process.communicate.assert_called_once_with(timeout=SETTINGS["cleanup_timeout_seconds"])
        self.assertEqual(report["checks"][-1]["status"], "FAIL")

    def test_malformed_or_incomplete_worker_results_never_pass(self):
        for output in ("not JSON", "{}", "[]", "null", "42", '{"checks":[]}'):
            process = Mock(returncode=0)
            process.communicate.return_value = (output, None)
            with patch.object(diagnostic.subprocess, "Popen", return_value=process):
                report = diagnostic.supervised_hardware(self.args, CONFIG, SETTINGS)
            self.assertEqual(report["checks"][-1]["status"], "FAIL")

    def test_bad_configuration_is_rejected(self):
        for key, value in (("hardware_timeout_seconds", 0), ("quiet_settle_ms", True), ("typo", 1)):
            with patch.object(Path, "read_text", return_value=json.dumps({**SETTINGS, key: value})):
                with self.assertRaises(ValueError):
                    diagnostic.load_settings("unused")

    def test_worker_entry_preserves_production_arguments_and_config(self):
        def worker(args, config, settings):
            self.assertEqual(args.sensor_order, (1, 2, 3, 4))
            return diagnostic.Audit(config, settings).report(False)

        with patch.object(diagnostic, "hardware_worker", side_effect=worker), \
                patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(diagnostic.main(["--worker", "--hardware", "--sensor-port", "sensor",
                                              "--display-port", "display"]), 0)
        self.assertEqual(json.loads(output.getvalue())["effective_config"],
                         {"reverse": CONFIG, "diagnostic": SETTINGS})

    def test_hardware_worker_runs_real_session_with_simulated_gpio_and_usb(self):
        clock = Clock()
        audit = diagnostic.Audit(CONFIG, SETTINGS, clock.now)
        sensor, display = Port(clock, True), Port(clock, False)
        sensor.close = lambda: setattr(sensor, "closed", True)
        display.close = lambda: setattr(display, "closed", True)

        class Input:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                pass

            @property
            def is_active(self):
                return 4050 <= clock.ms < 4100 or 4200 <= clock.ms < 5000

        def wait(stop, seconds):
            clock.wait(seconds)
            return stop.is_set()

        real_pump = reverse.pump

        def pump(*args):
            return real_pump(*args, clock=clock.now, new_token=lambda: 42)

        modules = {
            "serial": SimpleNamespace(Serial=lambda path, **_options: sensor if path == "sensor" else display),
            "gpiozero": SimpleNamespace(DigitalInputDevice=lambda *_args, **_kwargs: Input()),
            "gpiozero.pins.lgpio": SimpleNamespace(LGPIOFactory=Mock),
        }
        args = SimpleNamespace(**vars(self.args), sensor_order=(1, 2, 3, 4))
        with patch.dict("sys.modules", modules), patch.object(diagnostic, "Audit", return_value=audit), \
                patch.object(diagnostic.time, "monotonic", side_effect=clock.now), \
                patch.object(diagnostic.signal, "signal"), patch.object(diagnostic.DeadlineStop, "wait", wait), \
                patch.object(reverse, "pump", side_effect=pump), patch("sys.stderr", new_callable=io.StringIO):
            report = diagnostic.hardware_worker(args, {**CONFIG, "reverse_gpio_pin": 17}, SETTINGS)
        self.assertTrue(all(item["status"] == "PASS" for item in report["checks"]), report)
        self.assertTrue(sensor.closed and display.closed)

    def test_worker_config_drift_is_not_accepted(self):
        report = diagnostic.Audit(CONFIG, SETTINGS).report(False)
        report["effective_config"] = {"reverse": {**CONFIG, "reverse_high_qualify_ms": 0}, "diagnostic": SETTINGS}
        process = Mock(returncode=0)
        process.communicate.return_value = (json.dumps(report), None)
        with patch.object(diagnostic.subprocess, "Popen", return_value=process):
            received = diagnostic.supervised_hardware(self.args, CONFIG, SETTINGS)
        self.assertIn("Invalid worker report", received["checks"][-1]["detail"])

    def test_default_run_reports_hardware_as_not_tested(self):
        writes = {}

        def save(path, contents, **_options):
            writes[path.suffix] = contents

        with patch.object(Path, "mkdir"), patch.object(Path, "write_text", autospec=True, side_effect=save), \
                patch.object(diagnostic, "supervised_hardware") as hardware, \
                patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(diagnostic.main([]), 0)
        hardware.assert_not_called()
        report = json.loads(writes[".json"])
        self.assertEqual(report["mode"], "software-only")
        self.assertTrue(all(item["status"] == "NOT_TESTED" for item in report["hardware"]["checks"]))
        self.assertTrue(all(item["status"] == "NOT_TESTED" for item in report["physical_checks"]))
        self.assertIn("Software checks use synthetic inputs", writes[".md"])


if __name__ == "__main__":
    unittest.main()
