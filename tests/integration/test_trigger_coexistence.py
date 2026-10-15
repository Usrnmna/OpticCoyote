"""Cross-mode contract tests with synthetic clocks, GPIO, USB, and video processes."""
import io
import json
from pathlib import Path
import sys
import subprocess
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / folder) for folder in ("tools", "rpi-ahd-selector", "rpi-oled-bridge", "rpi-buzzer")]
import check_trigger_setup as setup
import buzzer
import control
import selector
import reverse_control as reverse
from test_reverse_control import Clock, Port, CONFIG as REVERSE, ARGS, SimulatedDeviceIdentities
from test_selector import FakeProcess, FakeStop


CAMERA = selector.validate({**json.loads((ROOT / "rpi-ahd-selector/config.json").read_text()),
                            "trigger_enabled": True})


class AssignmentTests(unittest.TestCase):
    def check(self, camera=None, reverse_pin=22, sensor="sensor", display="display"):
        return setup.check_assignments(camera or CAMERA, {**REVERSE, "reverse_gpio_pin": reverse_pin}, sensor, display)

    def test_distinct_assignments_report_only_configuration_evidence(self):
        report = self.check()
        self.assertEqual(report["gpio_bcm"], {"reverse": 22, "blinker_left": 17, "blinker_right": 27})
        self.assertEqual(report["sources_requiring_manual_inspection"], [])
        self.assertIn("timing are not verified", report["limits"])
        self.assertEqual(report["result"], "INCOMPLETE")

    def test_gpio_overlap_and_unassigned_reverse_are_rejected(self):
        for pin in (17, 27, None):
            with self.subTest(pin=pin), self.assertRaises(ValueError):
                self.check(reverse_pin=pin)
        with self.assertRaises(ValueError):
            self.check(camera={**CAMERA, "trigger_enabled": False})

    def test_serial_role_duplicates_and_aliases_are_rejected(self):
        for port in ("sensor", "display"):
            with self.subTest(port=port), self.assertRaisesRegex(ValueError, "Device conflict"):
                self.check(camera={**CAMERA, "serial_port": port})
        with self.assertRaisesRegex(ValueError, "Device conflict"):
            self.check(sensor="sensor", display="./sensor")
        original = setup.os.path.realpath
        with patch.object(setup.os.path, "realpath", side_effect=lambda path: "/dev/ttyUSB0" if path in ("sensor-alias", "control-alias") else original(path)):
            with self.assertRaisesRegex(ValueError, "Device conflict"):
                self.check(camera={**CAMERA, "serial_port": "control-alias"}, sensor="sensor-alias")

    def test_capture_duplicates_and_serial_capture_overlap_are_rejected(self):
        for sources in ((CAMERA["sources"][0],) * 4,
                        ("v4l2src device=sensor ! decodebin", *CAMERA["sources"][1:])):
            with self.assertRaisesRegex(ValueError, "Device conflict"):
                self.check(camera={**CAMERA, "sources": sources})

    def test_custom_sources_are_explicitly_uninspected(self):
        report = self.check(camera={**CAMERA, "sources": ["videotestsrc"] * 4})
        self.assertEqual(report["sources_requiring_manual_inspection"], [1, 2, 3, 4])

    def test_check_cli_is_device_free_and_uses_component_validators(self):
        configs = {"camera": json.dumps(CAMERA), "reverse": json.dumps({**REVERSE, "reverse_gpio_pin": 22})}
        with patch.object(Path, "read_text", autospec=True, side_effect=lambda path, **_: configs[str(path)]), \
                patch("sys.stdout", new_callable=io.StringIO) as output:
            code = setup.main(["--selector-config", "camera", "--reverse-config", "reverse",
                               "--sensor-port", "sensor", "--display-port", "display"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())["gpio_bcm"]["reverse"], 22)


class CombinedStateTests(unittest.TestCase):
    def test_both_does_not_stop_reverse_and_reverse_low_preserves_blinker_hold(self):
        clock = Clock(1700)
        state = selector.State(1, CAMERA)
        blinker = selector.BlinkerTrigger(CAMERA)
        sensor, display = Port(clock, True), Port(clock, False)
        gate = reverse.ReverseGate(0.1)
        observations = {}
        normal_wait = clock.wait

        def update():
            # LEFT, BOTH, RIGHT, then an OFF gap; reverse stays HIGH until 1200 ms.
            left, right = ((True, False) if clock.ms < 400 else
                           (True, True) if clock.ms < 800 else
                           (False, True) if clock.ms < 1100 else (False, False))
            state.trigger(blinker.update(left, right, clock.now()))
            observations[clock.ms] = state.snapshot()

        def wait(seconds):
            done = normal_wait(seconds)
            update()
            return done

        clock.wait = wait
        update()
        reverse.pump(sensor, display, ARGS, REVERSE, clock, gate, lambda: clock.ms < 1200,
                     clock.now, new_token=lambda: 42)
        self.assertEqual(observations[600]["trigger_state"], "BOTH")
        self.assertIsNone(observations[600]["selected_camera"])
        self.assertTrue(any(450 <= at <= 750 and data.startswith(b"K,") for at, data in sensor.writes))
        self.assertTrue(any(450 <= at <= 750 and data.startswith(b"D,") for at, data in display.writes))
        self.assertEqual(observations[1300]["selected_camera"], CAMERA["trigger_right_camera"])
        for port in (sensor, display):
            self.assertIn((1200, b"\nX\n"), port.writes)
            self.assertFalse(any(at >= 1200 and data.strip().startswith((b"R,", b"K,", b"D,")) for at, data in port.writes))

    def test_blocked_camera_launch_does_not_delay_reverse_low_release(self):
        state = selector.State(1, CAMERA)
        state.trigger("LEFT")
        launching, finish_launch = threading.Event(), threading.Event()
        processes = []
        errors = []

        def launch(_args, **_options):
            process = FakeProcess()
            processes.append(process)
            if len(processes) == 1:
                launching.set()
                if not finish_launch.wait(3):
                    raise RuntimeError("test launch barrier expired")
            return process

        def playback():
            try:
                selector.player(state, CAMERA, FakeStop(lambda _: None, limit=1))
            except BaseException as error:
                errors.append(error)

        with patch.object(selector.subprocess, "Popen", side_effect=launch):
            thread = threading.Thread(target=playback)
            thread.start()
            try:
                self.assertTrue(launching.wait(3))
                clock = Clock(500)
                sensor, display = Port(clock, True), Port(clock, False)
                gate = reverse.ReverseGate(0.1)

                def read_gpio():
                    if clock.ms >= 200:
                        state.trigger("BOTH")
                        return False
                    return True

                reverse.pump(sensor, display, ARGS, REVERSE, clock, gate, read_gpio, clock.now,
                             new_token=lambda: 42)
                for port in (sensor, display):
                    self.assertIn((200, b"\nX\n"), port.writes)
                self.assertTrue(thread.is_alive())
            finally:
                finish_launch.set()
                thread.join(timeout=3)
            self.assertFalse(thread.is_alive())
        self.assertFalse(errors, errors)
        self.assertTrue(processes[0].terminated)
        self.assertIsNone(state.snapshot()["selected_camera"])


class ResourceFailureTests(SimulatedDeviceIdentities, unittest.TestCase):
    def test_retargeted_oled_path_is_rechecked_without_stopping_other_work(self):
        clock = Clock(900)
        sensor, display = Port(clock, True), Port(clock)
        display.on_write = lambda packet: (_ for _ in ()).throw(OSError("OLED unplugged")) if packet.startswith(b"K,") else None
        display_opens = []

        def open_port(path, **_options):
            if path == "sensor":
                return sensor
            display_opens.append(clock.ms)
            return display if len(display_opens) == 1 else sensor

        serial = SimpleNamespace(Serial=open_port)
        original_pump = reverse.pump
        config = {**REVERSE, "boot_ms": 0, "reconnect_ms": 100}

        def simulated_pump(*args):
            return original_pump(*args, clock=clock.now, new_token=lambda: 42)

        state = selector.State(1, CAMERA)
        state.trigger("LEFT")
        processes = [FakeProcess(), FakeProcess()]
        output = Mock()
        buzzer_config = {**buzzer.load_config(), "enabled": True, "gpio_pin": 18}
        with buzzer.Buzzer(buzzer_config, output_factory=lambda _: output) as speaker:
            def video_tick(count):
                if count == 1:
                    with patch.object(reverse, "pump", side_effect=simulated_pump), \
                            patch.object(reverse, "path_device_identity",
                                         side_effect=lambda _: 101 if clock.ms >= 350 else 102):
                        reverse.run_session(serial, ARGS, config, clock, reverse.ReverseGate(0.1),
                                            lambda: clock.ms < 800)
                    speaker.play("single_beep")
                    self.assertTrue(speaker.wait(2))
                    state.trigger("RIGHT")

            with patch.object(selector.subprocess, "Popen", side_effect=processes) as launch:
                selector.player(state, CAMERA, FakeStop(video_tick, limit=3))
            self.assertEqual(launch.call_count, 2)
            self.assertIsNone(speaker.status()["fault"])
        self.assertEqual(display_opens, [0])
        self.assertTrue(any(at >= 450 and packet.startswith(b"K,") for at, packet in sensor.writes))
        self.assertFalse(any(100 < at < 800 and b"X" in packet for at, packet in sensor.writes))
        self.assertIn((800, b"\nX\n"), sensor.writes)
        self.assertTrue(output.apply.called)
        self.assertTrue(all(process.terminated for process in processes))

    def test_optional_stdin_transport_failure_does_not_request_video_shutdown(self):
        for failure in ("write", "short_write", "none_write", "flush", "read", "select"):
            with self.subTest(failure=failure):
                config = {**CAMERA, "trigger_enabled": False, "gpio_pins": []}
                stop = threading.Event()
                output = SimpleNamespace(buffer=Mock())
                if failure == "write":
                    output.buffer.write.side_effect = BrokenPipeError("controller detached")
                elif failure in ("short_write", "none_write"):
                    output.buffer.write.return_value = 1 if failure == "short_write" else None
                else:
                    output.buffer.write.side_effect = len
                if failure == "flush":
                    output.buffer.flush.side_effect = BrokenPipeError("controller detached")
                calls = []

                def finish(*_args):
                    self.assertFalse(stop.is_set(), "Optional command transport stopped video")
                    calls.append("survived")
                    stop.set()
                    return True

                def ready(*_args):
                    if calls:
                        finish()
                        return ([], [], [])
                    calls.append("attempt")
                    if failure == "select":
                        raise OSError("control input detached")
                    return ([sys.stdin], [], [])

                worker = Mock(ident=1)
                read = OSError("control input detached") if failure == "read" else b'{"status":true}\n{"camera":2}\n'
                with patch.object(Path, "read_text", return_value=json.dumps(config)), \
                        patch.object(selector.shutil, "which", return_value="gst"), \
                        patch.object(selector.threading, "Event", return_value=stop), \
                        patch.object(selector.threading, "Thread", return_value=worker), \
                        patch.object(selector.signal, "signal"), \
                        patch.object(stop, "wait", side_effect=finish), \
                        patch.object(selector.select, "select", side_effect=ready), \
                        patch.object(selector.os, "read", side_effect=[read]), \
                        patch.object(sys, "stdout", output), \
                        patch.object(selector, "apply_message", wraps=selector.apply_message) as apply:
                    selector.main([])
                self.assertIn("survived", calls)
                worker.start.assert_called_once()
                self.assertEqual(apply.call_count, 0 if failure in ("select", "read") else 1)

    def test_stdin_shutdown_during_read_or_reply_discards_remaining_batch(self):
        for cancel_at in ("read", "format", "write"):
            with self.subTest(cancel_at=cancel_at):
                config = {**CAMERA, "trigger_enabled": False, "gpio_pins": []}
                stop = threading.Event()
                output = SimpleNamespace(buffer=Mock())
                state = selector.State(1, config)

                def read(*_args):
                    if cancel_at == "read":
                        stop.set()
                    return b'{"camera":2}\n{"camera":3}\n'

                def write(reply):
                    stop.set()
                    return len(reply)

                original_dumps = json.dumps
                def dumps(value):
                    result = original_dumps(value)
                    if cancel_at == "format":
                        stop.set()
                    return result

                output.buffer.write.side_effect = write
                with patch.object(Path, "read_text", return_value=json.dumps(config)), \
                        patch.object(selector.shutil, "which", return_value="gst"), \
                        patch.object(selector.threading, "Event", return_value=stop), \
                        patch.object(selector.threading, "Thread", return_value=Mock(ident=1)), \
                        patch.object(selector.signal, "signal"), \
                        patch.object(selector.select, "select", return_value=([sys.stdin], [], [])), \
                        patch.object(selector.os, "read", side_effect=read), \
                        patch.object(selector, "State", return_value=state), \
                        patch.object(sys, "stdout", output), \
                        patch.object(selector.json, "dumps", side_effect=dumps):
                    selector.main([])
                self.assertEqual(state.selected, 1 if cancel_at == "read" else 2)
                self.assertEqual(output.buffer.write.call_count, 1 if cancel_at == "write" else 0)

    def test_optional_buzzer_fault_boundary_preserves_reverse_and_video_work(self):
        state = selector.State(1, CAMERA)
        state.trigger("LEFT")
        config = {**buzzer.load_config(), "enabled": True, "hardware_type": "passive", "gpio_pin": 18}
        output = Mock()
        output.apply.side_effect = OSError("buzzer GPIO backend disconnected")
        optional = buzzer.Buzzer(config, output_factory=lambda _config: output)
        clock = Clock(400)
        sensor, display = Port(clock, True), Port(clock, False)
        observed, faults = [], []
        processes = [FakeProcess(), FakeProcess()]

        def video_tick(count):
            observed.append(state.snapshot()["pipeline_camera"])
            if count == 1:
                # Optional callers contain playback and cleanup exceptions locally.
                try:
                    optional.play("single_beep")
                    optional.wait(1)
                except (RuntimeError, OSError) as error:
                    faults.append(str(error))
                finally:
                    try:
                        optional.close()
                    except (RuntimeError, OSError) as error:
                        faults.append(str(error))
                reverse.pump(sensor, display, ARGS, REVERSE, clock, reverse.ReverseGate(0.1),
                             lambda: clock.ms < 300, clock.now, new_token=lambda: 42)
                state.trigger("RIGHT")

        try:
            with patch.object(selector.subprocess, "Popen", side_effect=processes):
                selector.player(state, CAMERA, FakeStop(video_tick, limit=3))
        finally:
            try:
                optional.close()
            except (RuntimeError, OSError):
                pass
        self.assertEqual(len(faults), 2)
        self.assertIn("backend disconnected", optional.status()["fault"])
        self.assertEqual(observed, [1, 2, 2])
        self.assertTrue(any(packet.startswith(b"D,") for _, packet in display.writes))
        for port in (sensor, display):
            self.assertIn((300, b"\nX\n"), port.writes)
        output.close.assert_called_once()
        self.assertTrue(all(process.terminated for process in processes))

    def test_failed_camera_does_not_stop_reverse_or_prevent_switching_sides(self):
        for failure in ("launch", "capture"):
            with self.subTest(failure=failure):
                state = selector.State(1, CAMERA)
                state.trigger("LEFT")
                clock = Clock(500)
                sensor, display = Port(clock, True), Port(clock, False)
                failed, healthy = FakeProcess(), FakeProcess()
                failed.returncode = 1
                observations = []
                reverse_ran = False

                def tick(_count):
                    nonlocal reverse_ran
                    observations.append(state.snapshot())
                    if state.snapshot()["last_error"] and not reverse_ran:
                        reverse_ran = True
                        # Reverse work continues while camera failure is in its retry interval.
                        reverse.pump(sensor, display, ARGS, REVERSE, clock,
                                     reverse.ReverseGate(0.1), lambda: clock.ms < 350,
                                     clock.now, new_token=lambda: 42)
                        state.trigger("RIGHT")

                first = OSError("camera absent") if failure == "launch" else failed
                with patch.object(selector.subprocess, "Popen", side_effect=[first, healthy]) as launch:
                    selector.player(state, {**CAMERA, "retry_delay_seconds": 100}, FakeStop(tick, limit=4))
                self.assertTrue(reverse_ran)
                self.assertEqual(launch.call_count, 2)
                self.assertIn("device=/dev/video2", launch.call_args_list[1].args[0])
                self.assertTrue(any(item["pipeline_camera"] == 2 for item in observations))
                self.assertTrue(any(packet.startswith(b"D,") for _, packet in display.writes))
                for port in (sensor, display):
                    self.assertIn((350, b"\nX\n"), port.writes)
                self.assertTrue(healthy.terminated)

    def test_reverse_missing_usb_ports_do_not_prevent_blinker_playback(self):
        for missing_role in ("sensor", "display"):
            with self.subTest(missing_role=missing_role):
                state = selector.State(1, CAMERA)
                state.trigger("LEFT")
                clock = Clock(800)
                sensor = Port(clock, True)
                factory, device = Mock(), Mock()
                device.is_active = True
                device.__enter__ = Mock(return_value=device)
                device.__exit__ = Mock(return_value=False)
                modules = {"gpiozero": SimpleNamespace(DigitalInputDevice=lambda *_args, **_kwargs: device),
                           "gpiozero.pins.lgpio": SimpleNamespace(LGPIOFactory=lambda: factory)}
                processes = [FakeProcess(), FakeProcess()]
                observed = []

                def open_port(path, **_options):
                    if path == missing_role:
                        with patch.object(selector.subprocess, "Popen", side_effect=processes):
                            selector.player(state, CAMERA, FakeStop(video_tick, limit=3))
                        raise OSError(f"{path} Nano disconnected")
                    return sensor

                def video_tick(count):
                    observed.append(state.snapshot()["pipeline_camera"])
                    if count == 1:
                        state.trigger("RIGHT")

                serial = SimpleNamespace(Serial=Mock(side_effect=open_port), SerialException=OSError)
                original_pump = reverse.pump
                def simulated_pump(*args):
                    return original_pump(*args, clock=clock.now, new_token=lambda: 42)
                with patch.dict("sys.modules", modules), \
                        patch.object(reverse, "load_config", return_value={**REVERSE, "reverse_gpio_pin": 22, "boot_ms": 0}), \
                        patch.object(reverse, "pump", side_effect=simulated_pump):
                    reverse.run(serial, SimpleNamespace(**vars(ARGS), reverse_config="unused"),
                                clock)
                self.assertIn(missing_role, [call.args[0] for call in serial.Serial.call_args_list])
                self.assertIn(1, observed)
                self.assertIn(2, observed)
                self.assertTrue(all(process.terminated for process in processes))
                self.assertEqual(state.snapshot()["trigger_state"], "RIGHT")
                factory.close.assert_called_once()
                if missing_role == "display":
                    self.assertTrue(sensor.closed)
                    self.assertTrue(any(packet.startswith(b"K,") for _, packet in sensor.writes))

    def test_missing_optional_selector_serial_does_not_stop_its_playback_worker(self):
        state = selector.State(1, CAMERA)
        state.trigger("LEFT")
        stopped = threading.Event()
        missing, left_launched, right_launched = (threading.Event() for _ in range(3))
        processes, commands, failures = [], [], []

        def open_missing(*_args, **_kwargs):
            missing.set()
            raise OSError("optional JSON controller disconnected")

        def launch(command, **_options):
            commands.append(command)
            process = FakeProcess()
            processes.append(process)
            (left_launched if "device=/dev/video0" in command else right_launched).set()
            return process

        def run(target, *args):
            try:
                target(*args)
            except BaseException as error:
                failures.append(error)

        config = {**CAMERA, "serial_port": "missing-controller", "retry_delay_seconds": 100}
        serial = SimpleNamespace(Serial=open_missing, SerialException=OSError)
        threads = [threading.Thread(target=run, args=(selector.serial_control, state, config, stopped)),
                   threading.Thread(target=run, args=(selector.player, state, config, stopped))]
        with patch.dict("sys.modules", {"serial": serial}), \
                patch.object(selector.subprocess, "Popen", side_effect=launch):
            try:
                for thread in threads:
                    thread.start()
                self.assertTrue(missing.wait(3))
                self.assertTrue(left_launched.wait(3))
                self.assertFalse(stopped.is_set())
                state.trigger("RIGHT")
                self.assertTrue(right_launched.wait(3))
                self.assertFalse(stopped.is_set())
                self.assertTrue(all(thread.is_alive() for thread in threads))
            finally:
                stopped.set()
                for thread in threads:
                    thread.join(timeout=3)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertFalse(failures, failures)
        self.assertEqual(len(commands), 2)
        self.assertTrue(all(process.terminated for process in processes))

    def test_selector_and_sender_refuse_an_exclusively_owned_nano(self):
        opened = []

        def open_port(path, *_args, **options):
            opened.append((path, options))
            if options.get("exclusive"):
                raise OSError("port already owned by reverse bridge")
            self.fail("Serial open omitted cooperative exclusivity")

        module = SimpleNamespace(Serial=open_port, SerialException=OSError)
        stop = SimpleNamespace(is_set=Mock(side_effect=[False, True]), wait=Mock())
        with patch.dict("sys.modules", {"serial": module}):
            selector.serial_control(selector.State(1, CAMERA), {**CAMERA, "serial_port": "sensor"}, stop)
            with self.assertRaises(OSError):
                control.send_serial_command('{"status":true}\n', "sensor", 115200, 1)
        self.assertEqual(len(opened), 2)
        stop.wait.assert_called_once()

    def test_gpio_claim_failure_releases_factory_before_any_usb_work(self):
        factory = Mock()
        serial = SimpleNamespace(Serial=Mock(), SerialException=OSError)
        modules = {"gpiozero": SimpleNamespace(DigitalInputDevice=Mock(side_effect=OSError("GPIO busy"))),
                   "gpiozero.pins.lgpio": SimpleNamespace(LGPIOFactory=Mock(return_value=factory))}
        with patch.dict("sys.modules", modules), \
                patch.object(reverse, "load_config", return_value={**REVERSE, "reverse_gpio_pin": 17}):
            with self.assertRaises(OSError):
                reverse.run(serial, SimpleNamespace(reverse_config="unused"), threading.Event())
        serial.Serial.assert_not_called()
        factory.close.assert_called_once()

    def test_reverse_display_contention_keeps_sensor_acquisition_until_low(self):
        clock = Clock(800)
        sensor = Port(clock, True)
        attempted = []

        def open_port(path, **options):
            self.assertTrue(options["exclusive"])
            attempted.append(path)
            if path == "display":
                raise OSError("display already owned by another process")
            return sensor

        original_pump = reverse.pump
        def simulated_pump(*args):
            return original_pump(*args, clock=clock.now, new_token=lambda: 42)
        with patch.object(reverse, "pump", side_effect=simulated_pump):
            reverse.run_session(SimpleNamespace(Serial=open_port), ARGS, {**REVERSE, "boot_ms": 0}, clock,
                                reverse.ReverseGate(0.1), lambda: clock.ms < 700)
        self.assertIn("display", attempted)
        self.assertTrue(sensor.closed)
        self.assertTrue(any(packet.startswith(b"K,") for _, packet in sensor.writes))
        self.assertIn((700, b"\nX\n"), sensor.writes)

    def test_selector_pin_claim_failure_releases_only_acquired_resources(self):
        button, factory, thread = Mock(), Mock(), Mock()
        gpio = SimpleNamespace(Button=Mock(side_effect=[button, OSError("GPIO already claimed")]))
        modules = {"gpiozero": gpio, "gpiozero.pins.lgpio": SimpleNamespace(LGPIOFactory=lambda: factory)}
        with patch.dict("sys.modules", modules), \
                patch.object(Path, "read_text", return_value=json.dumps(CAMERA)), \
                patch.object(selector.shutil, "which", return_value="gst-launch-1.0"), \
                patch.object(selector.signal, "signal"), patch.object(selector.threading, "Thread", thread):
            with self.assertRaises(OSError):
                selector.main([])
        button.close.assert_called_once()
        factory.close.assert_called_once()
        thread.assert_not_called()

    def test_failed_camera_teardown_does_not_open_another_capture(self):
        config = {**CAMERA, "process_stop_timeout_seconds": 0.1}
        state = selector.State(1, config)
        state.trigger("LEFT")
        stopped = threading.Event()
        process = FakeProcess()
        process.wait = Mock(side_effect=subprocess.TimeoutExpired("gst", 0.1))

        class Stop:
            def is_set(self):
                return stopped.is_set()

            def set(self):
                stopped.set()

            def wait(self, _seconds):
                state.trigger("RIGHT")
                return False

        with patch.object(selector.subprocess, "Popen", return_value=process) as launch:
            selector.player(state, config, Stop())
        launch.assert_called_once()
        self.assertTrue(stopped.is_set())
        self.assertIn("release unverified", state.snapshot()["last_error"])
        for call in process.wait.call_args_list:
            self.assertEqual(call.kwargs["timeout"], 0.1)

    def test_short_selector_reply_closes_port_instead_of_appending_another_reply(self):
        port = Mock()
        port.read.return_value = b'{"status":true}\n{"status":true}\n'
        port.write.return_value = 1
        session = Mock(__enter__=Mock(return_value=port), __exit__=Mock(return_value=False))
        stopped = threading.Event()
        stop = SimpleNamespace(is_set=stopped.is_set, wait=lambda _seconds: stopped.set())
        module = SimpleNamespace(Serial=Mock(return_value=session), SerialException=OSError)
        with patch.dict("sys.modules", {"serial": module}):
            selector.serial_control(selector.State(1, CAMERA), {**CAMERA, "serial_port": "control"}, stop)
        port.write.assert_called_once()
        session.__exit__.assert_called_once()


if __name__ == "__main__":
    unittest.main()
