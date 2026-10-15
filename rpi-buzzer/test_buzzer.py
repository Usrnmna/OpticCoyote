"""Software-only pattern, cancellation, configuration, and driver ownership tests."""
import copy
import io
import json
from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import buzzer


DEFAULT = buzzer.load_config()


def enabled(kind="passive"):
    return {**copy.deepcopy(DEFAULT), "enabled": True, "hardware_type": kind, "gpio_pin": 18}


class Output:
    def __init__(self, _config):
        self.events = []
        self.applied = threading.Event()
        self.closed = False

    def off(self):
        self.events.append("off")

    def apply(self, step):
        self.events.append(copy.deepcopy(step))
        self.applied.set()

    def close(self):
        self.closed = True


class ConfigurationTests(unittest.TestCase):
    def test_shipped_module_defaults_are_disabled_and_device_free(self):
        self.assertFalse(DEFAULT["enabled"])
        self.assertEqual(DEFAULT["hardware_type"], "passive")
        self.assertFalse(DEFAULT["active_high"])
        self.assertIsNone(DEFAULT["gpio_pin"])
        factory = Mock(side_effect=AssertionError("GPIO must not open"))
        with buzzer.Buzzer(DEFAULT, factory) as player:
            with self.assertRaisesRegex(RuntimeError, "disabled"):
                player.play("single_beep")
            self.assertTrue(player.wait(0))
        factory.assert_not_called()

    def test_invalid_top_level_and_unconfigured_enabled_rejected(self):
        for changes in ({"enabled": 1}, {"active_high": 0}, {"hardware_type": "piezo"},
                        {"gpio_pin": True}, {"gpio_pin": 28}, {"gpio_pin": 1},
                        {"enabled": True}, {"max_sequence_ms": 0}, {"max_sequence_ms": 60001},
                        {"sequences": {}}, {"typo": 1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                buzzer.validate({**DEFAULT, **changes})
        with self.assertRaises(ValueError):
            buzzer.validate([])
        with self.assertRaises(ValueError):
            buzzer.validate({**enabled(), "hardware_type": None})
        buzzer.validate({**DEFAULT, "hardware_type": None})

    def test_sequence_limits_and_strict_step_schema(self):
        for step in ({"duration_ms": 0, "sound": False},
                     {"duration_ms": True, "sound": False},
                     {"duration_ms": 20, "sound": 1},
                     {"duration_ms": 20, "sound": False, "frequency_hz": 100},
                     {"duration_ms": 20, "sound": True}):
            config = enabled()
            config["sequences"] = {"test": {"repeat": 1, "steps": [step]}}
            with self.subTest(step=step), self.assertRaises(ValueError):
                buzzer.validate(config)
        for field, values in (("duty_cycle", (0, -1, 0.6, True, float("nan"), float("inf"))),
                              ("frequency_hz", (0, 10001, True, 100.5))):
            for value in values:
                config = enabled()
                config["sequences"]["single_beep"]["steps"][0][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    buzzer.validate(config)

    def test_duration_includes_pauses_and_repeats(self):
        config = enabled()
        config["max_sequence_ms"] = 360
        buzzer.validate(config)
        config["sequences"]["double_beep"]["repeat"] = 2
        with self.assertRaisesRegex(ValueError, "exceeds"):
            buzzer.validate(config)
        for repeat in (0, 101, True):
            config["sequences"]["double_beep"]["repeat"] = repeat
            with self.assertRaises(ValueError):
                buzzer.validate(config)

    def test_names_counts_and_duplicate_keys(self):
        for sequences in ({"BAD": DEFAULT["sequences"]["single_beep"]},
                          {"a": {"repeat": 1, "steps": []}},
                          {"a": {"repeat": 1, "steps": [{"sound": False, "duration_ms": 1}] * 129}},
                          {f"a{index}": DEFAULT["sequences"]["single_beep"] for index in range(65)}):
            with self.assertRaises(ValueError):
                buzzer.validate({**DEFAULT, "sequences": sequences})
        with patch.object(Path, "read_text", return_value='{"enabled":true,"enabled":false}'):
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                buzzer.load_config("unused")

    def test_cli_inspection_and_disabled_playback_need_no_gpio(self):
        with patch("builtins.__import__", wraps=__import__) as imports, patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(buzzer.main(["--check-config"]), 0)
            self.assertEqual(buzzer.main(["--list"]), 0)
            self.assertEqual(buzzer.main(["--play", "single_beep"]), 2)
        self.assertFalse(any(call.args[0].startswith("gpiozero") for call in imports.call_args_list))

    def test_cli_playback_fault_returns_nonzero_and_restores_signal_handlers(self):
        player = Mock()
        player.__enter__ = Mock(return_value=player)
        player.__exit__ = Mock(return_value=False)
        player.wait.side_effect = RuntimeError("backend fault")
        with patch.object(buzzer, "load_config", return_value=enabled()), \
                patch.object(buzzer, "Buzzer", return_value=player), \
                patch.object(buzzer.signal, "signal", return_value="prior") as signals, \
                patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(buzzer.main(["--play", "single_beep"]), 2)
        player.__exit__.assert_called_once()
        self.assertEqual([call.args[1] for call in signals.call_args_list[-2:]], ["prior", "prior"])

    def test_cli_signal_cancels_and_does_not_claim_completion(self):
        handlers = {}
        player = Mock()
        player.__enter__ = Mock(return_value=player)
        player.__exit__ = Mock(return_value=False)

        def install(number, handler):
            handlers[number] = handler
            return "prior"

        def wait(_timeout):
            handlers[buzzer.signal.SIGTERM](None, None)
            return False

        player.wait.side_effect = wait
        with patch.object(buzzer, "load_config", return_value=enabled()), \
                patch.object(buzzer, "Buzzer", return_value=player), \
                patch.object(buzzer.signal, "signal", side_effect=install), \
                patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(buzzer.main(["--play", "single_beep"]), 130)
        player.stop.assert_called_once()
        player.__exit__.assert_called_once()
        self.assertNotIn("completed", output.getvalue())


class PlaybackTests(unittest.TestCase):
    def make_player(self, config=None, output=None):
        config = config or enabled()
        output = output or Output(config)
        player = buzzer.Buzzer(config, lambda _: output)
        self.addCleanup(lambda: self.cleanup(player))
        return player, output

    @staticmethod
    def cleanup(player):
        try:
            player.close()
        except RuntimeError:
            pass

    def test_finite_pattern_completes_and_silences(self):
        config = enabled()
        config["sequences"] = {"pattern": {"repeat": 2, "steps": [
            {"sound": True, "duration_ms": 1, "frequency_hz": 1000, "duty_cycle": 0.4},
            {"sound": False, "duration_ms": 1}]}}
        player, output = self.make_player(config)
        player.play("pattern")
        self.assertTrue(player.wait(2))
        self.assertEqual([item["sound"] for item in output.events if isinstance(item, dict)], [True, False] * 2)
        self.assertEqual(output.events[-1], "off")
        self.assertIsNone(player.status()["sequence"])

    def test_stop_cancels_long_wait_and_no_old_step_reasserts(self):
        config = enabled()
        config["sequences"]["double_beep"]["steps"][0]["duration_ms"] = 5000
        player, output = self.make_player(config)
        player.play("double_beep")
        self.assertTrue(output.applied.wait(2))
        self.assertFalse(player.wait(0))
        player.stop()
        self.assertTrue(player.wait(0))
        player.close()
        self.assertFalse(player._worker.is_alive())
        self.assertEqual(len([event for event in output.events if isinstance(event, dict)]), 1)
        self.assertEqual(output.events[-1], "off")
        self.assertTrue(output.closed)

    def test_replacement_cannot_be_silenced_by_old_generation(self):
        config = enabled()
        config["sequences"]["single_beep"]["steps"][0]["duration_ms"] = 5000
        config["sequences"]["replacement"] = {"repeat": 1, "steps": [
            {"sound": True, "duration_ms": 5000, "frequency_hz": 3000, "duty_cycle": 0.5}]}
        player, output = self.make_player(config)
        first = player.play("single_beep")
        self.assertTrue(output.applied.wait(2))
        output.applied.clear()
        second = player.play("replacement")
        self.assertTrue(output.applied.wait(2))
        self.assertGreater(second, first)
        self.assertEqual(player.status()["sequence"], "replacement")
        # Worker has released its condition for the new step's wait.
        with player._condition:
            self.assertEqual(output.events[-1]["frequency_hz"], 3000)
        player.stop()

    def test_stop_waits_for_inflight_output_then_prevents_later_assertion(self):
        entered, release, stopped, stopping = (threading.Event() for _ in range(4))
        config = enabled()
        output = Output(config)
        original = output.apply

        def blocked(step):
            entered.set()
            if not release.wait(2):
                raise RuntimeError("test barrier expired")
            original(step)

        output.apply = blocked
        player, _ = self.make_player(config, output)
        player.play("double_beep")
        self.assertTrue(entered.wait(2))

        def cancel():
            stopping.set()
            player.stop()
            stopped.set()

        thread = threading.Thread(target=cancel)
        thread.start()
        try:
            self.assertTrue(stopping.wait(2))
            self.assertFalse(stopped.is_set())
        finally:
            release.set()
            thread.join(2)
        self.assertTrue(stopped.is_set())
        player.close()
        self.assertEqual(output.events[-1], "off")
        self.assertEqual(len([event for event in output.events if isinstance(event, dict)]), 1)

    def test_output_failure_is_latched_and_cannot_report_success(self):
        output = Output(enabled())
        output.apply = Mock(side_effect=OSError("disconnected"))
        player, _ = self.make_player(output=output)
        player.play("single_beep")
        with self.assertRaisesRegex(RuntimeError, "disconnected"):
            player.wait(2)
        with self.assertRaises(RuntimeError):
            player.play("single_beep")
        with self.assertRaises(RuntimeError):
            player.close()
        self.assertTrue(output.closed)
        self.assertFalse(player._worker.is_alive())

    def test_close_during_output_call_cancels_remaining_steps_and_rejects_play(self):
        entered, release, closing, closed = (threading.Event() for _ in range(4))
        output = Output(enabled())
        original = output.apply
        errors = []

        def blocked(step):
            entered.set()
            if not release.wait(2):
                raise RuntimeError("test barrier expired")
            original(step)

        output.apply = blocked
        player, _ = self.make_player(output=output)
        player.play("double_beep")
        self.assertTrue(entered.wait(2))

        def close():
            closing.set()
            try:
                player.close()
            except Exception as error:
                errors.append(error)
            finally:
                closed.set()

        thread = threading.Thread(target=close)
        thread.start()
        try:
            self.assertTrue(closing.wait(2))
            self.assertFalse(closed.is_set())
        finally:
            release.set()
            thread.join(2)
        self.assertTrue(closed.is_set())
        self.assertEqual(errors, [])
        self.assertFalse(player._worker.is_alive())
        self.assertTrue(output.closed)
        self.assertEqual(len([event for event in output.events if isinstance(event, dict)]), 1)
        self.assertEqual(output.events[-1], "off")
        with self.assertRaisesRegex(RuntimeError, "closed"):
            player.play("single_beep")

    def test_completion_silence_failure_cannot_report_success(self):
        output = Output(enabled())
        original = output.apply

        def apply(step):
            original(step)
            output.off = Mock(side_effect=OSError("completion off failed"))

        output.apply = apply
        player, _ = self.make_player(output=output)
        player.play("single_beep")
        with self.assertRaisesRegex(RuntimeError, "completion off failed"):
            player.wait(2)
        self.assertIsNone(player.status()["sequence"])
        with self.assertRaises(RuntimeError):
            player.close()
        self.assertTrue(output.closed)

    def test_failed_silence_invalidates_old_job_and_latches_fault(self):
        player, output = self.make_player()
        player.play("double_beep")
        self.assertTrue(output.applied.wait(2))
        output.off = Mock(side_effect=OSError("write failure"))
        with self.assertRaisesRegex(RuntimeError, "Silence failed"):
            player.stop()
        self.assertIsNone(player.status()["sequence"])
        with self.assertRaises(RuntimeError):
            player.close()
        self.assertTrue(output.closed)

    def test_configuration_is_snapshotted_and_unknown_name_preserves_playback(self):
        config = enabled()
        player, output = self.make_player(config)
        config["sequences"].clear()
        player.play("double_beep")
        with self.assertRaises(ValueError):
            player.play("unknown")
        self.assertEqual(player.status()["sequence"], "double_beep")
        for timeout in (-1, float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                player.wait(timeout)
        player.close()
        player.close()
        with self.assertRaisesRegex(RuntimeError, "closed"):
            player.play("single_beep")

    def test_start_failure_closes_output(self):
        output = Output(enabled())
        with patch.object(threading.Thread, "start", side_effect=RuntimeError("thread failed")):
            with self.assertRaisesRegex(RuntimeError, "thread failed"):
                buzzer.Buzzer(enabled(), lambda _: output)
        self.assertTrue(output.closed)

    def test_backend_specific_initialization_error_is_normalized(self):
        class PinError(Exception):
            pass
        with self.assertRaisesRegex(RuntimeError, "pin busy"):
            buzzer.Buzzer(enabled(), Mock(side_effect=PinError("pin busy")))
        output = Output(enabled())
        output.off = Mock(side_effect=PinError("initial off failed"))
        output.close = Mock(side_effect=PinError("close failed"))
        with self.assertRaisesRegex(RuntimeError, "initial off failed.*close failed"):
            buzzer.Buzzer(enabled(), lambda _: output)
        output.close.assert_called_once()


class GPIOTests(unittest.TestCase):
    def modules(self, device, factory):
        return {"gpiozero": SimpleNamespace(DigitalOutputDevice=Mock(return_value=device),
                                           PWMOutputDevice=Mock(return_value=device)),
                "gpiozero.pins.lgpio": SimpleNamespace(LGPIOFactory=Mock(return_value=factory))}

    def test_active_uses_steady_output_and_passive_uses_pwm(self):
        step = DEFAULT["sequences"]["single_beep"]["steps"][0]
        for kind in ("active", "passive"):
            with self.subTest(kind=kind):
                device, factory = Mock(), Mock()
                modules = self.modules(device, factory)
                with patch.dict("sys.modules", modules):
                    output = buzzer.GPIOOutput({**enabled(kind), "active_high": False})
                    constructor = getattr(modules["gpiozero"], "PWMOutputDevice" if kind == "passive" else "DigitalOutputDevice")
                    self.assertEqual(constructor.call_args.kwargs["initial_value"], 0)
                    self.assertFalse(constructor.call_args.kwargs["active_high"])
                    output.apply(step)
                    if kind == "active":
                        device.on.assert_called_once()
                        self.assertNotIn("frequency", device.__dict__)
                    else:
                        self.assertIsNone(constructor.call_args.kwargs["frequency"])
                        self.assertEqual(device.frequency, 2000)
                        self.assertEqual(device.value, 0.5)
                        device.on.assert_not_called()
                    output.apply({"sound": False, "duration_ms": 1})
                    output.close()
                device.close.assert_called_once()
                factory.close.assert_called_once()

    def test_claim_failure_closes_factory(self):
        factory = Mock()
        modules = self.modules(Mock(), factory)
        modules["gpiozero"].PWMOutputDevice.side_effect = OSError("pin busy")
        with patch.dict("sys.modules", modules), self.assertRaises(OSError):
            buzzer.GPIOOutput(enabled())
        factory.close.assert_called_once()

    def test_passive_idle_stops_waveform_before_static_inactive_level(self):
        class QueuedPWM:
            """Model a duty update that takes effect only at a later PWM cycle."""
            def __init__(self, _pin, *, active_high, initial_value, frequency, pin_factory):
                self.active_high = active_high
                self.running = False
                self.events = []
                self.frequency = frequency
                self.value = initial_value

            @property
            def frequency(self):
                return self._frequency

            @frequency.setter
            def frequency(self, value):
                self._frequency = value
                self.running = value is not None
                self.events.append(("pwm", self.running))

            @property
            def value(self):
                return self.level

            @value.setter
            def value(self, value):
                physical = value if self.active_high else 1 - value
                if self.running:
                    self.events.append(("queued_duty", physical))
                else:
                    self.level = physical
                    self.events.append(("static", physical))

            def off(self):
                self.value = 0

            def close(self):
                self.frequency = None

        for polarity in (False, True):
            with self.subTest(active_high=polarity):
                modules = self.modules(None, Mock())
                modules["gpiozero"].PWMOutputDevice.side_effect = QueuedPWM
                with patch.dict("sys.modules", modules):
                    output = buzzer.GPIOOutput({**enabled(), "active_high": polarity})
                    device = output.device
                    inactive = 0 if polarity else 1
                    self.assertFalse(device.running)
                    self.assertEqual(device.level, inactive)
                    output.apply(DEFAULT["sequences"]["single_beep"]["steps"][0])
                    self.assertTrue(device.running)
                    output.off()
                    self.assertFalse(device.running)
                    self.assertEqual(device.events[-2:], [("pwm", False), ("static", inactive)])
                    output.apply({"sound": False, "duration_ms": 1})
                    self.assertFalse(device.running)
                    output.close()
                    self.assertEqual(device.level, inactive)

    def test_pwm_stop_failure_attempts_off_and_releases_resources(self):
        class StopFailure:
            off = Mock()
            close = Mock()

            @property
            def frequency(self):
                return 2000

            @frequency.setter
            def frequency(self, _value):
                raise OSError("PWM stop failed")

        device, factory = StopFailure(), Mock()
        with patch.dict("sys.modules", self.modules(device, factory)):
            output = buzzer.GPIOOutput(enabled())
            with self.assertRaisesRegex(RuntimeError, "PWM stop failed"):
                output.close()
        device.off.assert_called_once()
        device.close.assert_called_once()
        factory.close.assert_called_once()

    def test_off_failure_still_releases_device_and_factory(self):
        device, factory = Mock(), Mock()
        device.off.side_effect = OSError("output failed")
        with patch.dict("sys.modules", self.modules(device, factory)):
            output = buzzer.GPIOOutput(enabled())
            with self.assertRaisesRegex(RuntimeError, "output failed"):
                output.close()
        device.close.assert_called_once()
        factory.close.assert_called_once()

    def test_pwm_stop_and_inactive_write_failures_are_both_reported(self):
        class BrokenPWM:
            @property
            def frequency(self):
                return 2000

            @frequency.setter
            def frequency(self, _value):
                raise OSError("waveform stop rejected")

            def off(self):
                raise OSError("HIGH write rejected")

        with patch.dict("sys.modules", self.modules(BrokenPWM(), Mock())):
            output = buzzer.GPIOOutput(enabled())
            with self.assertRaisesRegex(RuntimeError, "waveform stop rejected.*HIGH write rejected"):
                output.off()

    def test_cleanup_reports_first_fault_and_attempts_every_release(self):
        device, factory = Mock(), Mock()
        device.off.side_effect = OSError("inactive write failed")
        device.close.side_effect = OSError("device release failed")
        factory.close.side_effect = OSError("factory release failed")
        with patch.dict("sys.modules", self.modules(device, factory)):
            output = buzzer.GPIOOutput(enabled())
            with self.assertRaisesRegex(RuntimeError, "inactive write failed.*device release failed.*factory release failed"):
                output.close()
        device.close.assert_called_once()
        factory.close.assert_called_once()

    def test_interrupted_silence_still_releases_device_and_factory(self):
        device, factory = Mock(), Mock()
        device.off.side_effect = KeyboardInterrupt()
        with patch.dict("sys.modules", self.modules(device, factory)):
            output = buzzer.GPIOOutput(enabled())
            with self.assertRaises(KeyboardInterrupt):
                output.close()
        device.close.assert_called_once()
        factory.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
