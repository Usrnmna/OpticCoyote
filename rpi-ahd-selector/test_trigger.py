"""Blinker-mode contracts using synthetic timestamps, GPIO and video processes.

These checks establish software transitions and process ownership, not vehicle
voltage compatibility, camera latency, or successful physical display clearing.
"""
import copy
import io
import json
from pathlib import Path
import sys
import threading
import types
import unittest
from unittest.mock import Mock, patch

import selector
from test_selector import CONFIG, FakeProcess, FakeStop


def trigger_config(**changes):
    """Return a validated trigger configuration with optional test overrides."""
    return selector.validate({**copy.deepcopy(CONFIG), "trigger_enabled": True, **changes})


class TriggerTimingTests(unittest.TestCase):
    def setUp(self):
        self.trigger = selector.BlinkerTrigger(trigger_config())

    def check_trace(self, rows):
        """Compare each timestamped input pair with its required retained state."""
        for now, left, right, expected in rows:
            with self.subTest(now=now, left=left, right=right):
                self.assertEqual(self.trigger.update(left, right, now), expected)

    def test_initial_idle_and_single_side_settling(self):
        self.check_trace([(0, 0, 0, "IDLE"), (0.1, 1, 0, "IDLE"),
                          (0.14, 1, 0, "IDLE"), (0.19, 1, 0, "LEFT")])

    def test_blink_gaps_hold_and_final_low_expires(self):
        self.check_trace([(0, 0, 1, "IDLE"), (0.09, 0, 1, "RIGHT"),
                          (0.3, 0, 0, "RIGHT"), (0.4, 0, 0, "RIGHT"),
                          (0.8, 0, 1, "RIGHT"), (0.9, 0, 1, "RIGHT"),
                          (1.2, 0, 0, "RIGHT"), (2.19, 0, 0, "RIGHT"),
                          (2.21, 0, 0, "IDLE")])

    def test_hazard_skew_does_not_start_a_side_and_both_holds_through_gaps(self):
        self.check_trace([(0, 1, 0, "IDLE"), (0.04, 1, 1, "IDLE"),
                          (0.08, 1, 1, "BOTH"), (0.3, 0, 1, "BOTH"),
                          (0.32, 0, 0, "BOTH"), (0.5, 0, 0, "BOTH"),
                          (0.8, 1, 0, "BOTH"), (0.84, 1, 1, "BOTH"),
                          (0.88, 1, 1, "BOTH"), (1.0, 0, 0, "BOTH"),
                          (1.99, 0, 0, "BOTH"), (2.01, 0, 0, "IDLE")])

    def test_both_overrides_left_without_single_side_settle(self):
        self.check_trace([(0, 1, 0, "IDLE"), (0.09, 1, 0, "LEFT"),
                          (0.1, 1, 1, "LEFT"), (0.14, 1, 1, "BOTH"),
                          (0.2, 0, 1, "BOTH"), (0.24, 0, 1, "BOTH"),
                          (0.29, 0, 1, "RIGHT")])

    def test_opposite_turn_does_not_create_synthetic_both(self):
        self.check_trace([(0, 1, 0, "IDLE"), (0.09, 1, 0, "LEFT"),
                          (0.2, 0, 0, "LEFT"), (0.24, 0, 0, "LEFT"),
                          (0.3, 0, 1, "LEFT"), (0.39, 0, 1, "RIGHT")])

    def test_short_glitches_do_not_select_or_extend_off_hold(self):
        self.check_trace([(0, 1, 0, "IDLE"), (0.01, 0, 0, "IDLE"),
                          (0.2, 1, 0, "IDLE"), (0.29, 1, 0, "LEFT"),
                          (0.3, 0, 0, "LEFT"), (0.34, 0, 0, "LEFT"),
                          (1.2, 1, 1, "LEFT"), (1.21, 0, 0, "LEFT"),
                          (1.31, 0, 0, "IDLE")])

    def test_continuous_high_has_no_expiry(self):
        self.check_trace([(0, 1, 0, "IDLE"), (0.09, 1, 0, "LEFT"),
                          (300, 1, 0, "LEFT"), (301, 1, 1, "LEFT"),
                          (302, 1, 1, "BOTH"), (600, 1, 1, "BOTH")])

    def test_off_deadline_expires_despite_unqualified_chatter(self):
        for initial in ((1, 0), (0, 1), (1, 1)):
            with self.subTest(initial=initial):
                trigger = selector.BlinkerTrigger(trigger_config())
                trigger.update(*initial, 0)
                trigger.update(*initial, 0.1)
                trigger.update(False, False, 0.2)
                trigger.update(False, False, 0.24)
                trigger.update(True, False, 1.19)
                # This HIGH has not qualified; the established OFF deadline still applies.
                self.assertEqual(trigger.update(True, False, 1.21), "IDLE")
                self.assertEqual(trigger.update(False, False, 1.23), "IDLE")
                self.assertEqual(trigger.update(True, False, 1.25), "IDLE")
                self.assertEqual(trigger.update(True, False, 1.34), "LEFT")

    def test_return_after_expired_gap_must_qualify_again(self):
        self.check_trace([(0, 1, 0, "IDLE"), (0.1, 1, 0, "LEFT"),
                          (0.2, 0, 0, "LEFT"), (0.24, 0, 0, "LEFT"),
                          (1.5, 1, 0, "IDLE"), (1.54, 1, 0, "IDLE"),
                          (1.59, 1, 0, "LEFT")])

    def test_qualified_return_before_expiry_resets_off_deadline(self):
        self.check_trace([(0, 1, 0, "IDLE"), (0.1, 1, 0, "LEFT"),
                          (0.2, 0, 0, "LEFT"), (0.24, 0, 0, "LEFT"),
                          (1.0, 1, 0, "LEFT"), (1.09, 1, 0, "LEFT"),
                          (1.3, 0, 0, "LEFT"), (2.29, 0, 0, "LEFT"),
                          (2.31, 0, 0, "IDLE")])

    def test_zero_timing_and_custom_hold(self):
        self.trigger = selector.BlinkerTrigger(trigger_config(
            trigger_debounce_seconds=0, trigger_settle_seconds=0,
            trigger_off_hold_seconds=2))
        self.check_trace([(0, 1, 0, "LEFT"), (1, 0, 0, "LEFT"),
                          (2.99, 0, 0, "LEFT"), (3, 0, 0, "IDLE")])
        self.trigger = selector.BlinkerTrigger(trigger_config(
            trigger_debounce_seconds=0, trigger_settle_seconds=0,
            trigger_off_hold_seconds=0))
        self.check_trace([(0, 1, 1, "BOTH"), (1, 0, 0, "IDLE")])


class TriggerConfigTests(unittest.TestCase):
    def test_invalid_pins_mappings_booleans_and_conflicting_modes(self):
        for name, value in (("trigger_left_pin", True), ("trigger_right_pin", 28),
                            ("trigger_left_pin", 27), ("trigger_right_pin", -1),
                            ("trigger_enabled", 1), ("trigger_active_low", "false"),
                            ("trigger_left_camera", 0), ("trigger_right_camera", 5),
                            ("trigger_left_camera", True), ("trigger_left_camera", 2),
                            ("gpio_pins", [17, 27, 22, 23])):
            with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                trigger_config(**{name: value})

    def test_default_sides_select_their_capture_paths_and_hazards_capture_neither(self):
        config = trigger_config()
        state = selector.State(1, config)
        for mode, camera, device in (("LEFT", 1, "/dev/video0"),
                                     ("RIGHT", 2, "/dev/video2")):
            state.trigger(mode)
            selected = state.snapshot()["selected_camera"]
            self.assertEqual(selected, camera)
            self.assertIn(f"device={device}", selector.command(config, selected))
        for mode in ("BOTH", "IDLE"):
            state.trigger(mode)
            selected = state.snapshot()["selected_camera"]
            self.assertIsNone(selected)
            self.assertNotIn("v4l2src", selector.command(config, selected))

    def test_custom_mapping_and_startup_ignore_initial_camera(self):
        state = selector.State(1, trigger_config(trigger_left_camera=2, trigger_right_camera=1))
        self.assertIsNone(state.snapshot()["selected_camera"])
        for name, camera in (("LEFT", 2), ("RIGHT", 1), ("BOTH", None), ("IDLE", None)):
            state.trigger(name)
            self.assertEqual(state.snapshot()["selected_camera"], camera)
            self.assertEqual(state.snapshot()["trigger_state"], name)

    def test_selection_commands_rejected_in_every_trigger_state(self):
        state = selector.State(1, trigger_config())
        for name in ("IDLE", "LEFT", "RIGHT", "BOTH", "FAULT"):
            state.trigger(name)
            before = state.snapshot()
            for command in ('{"camera":2}', '{"inputs":[1,0]}'):
                reply = selector.apply_message(state, command)
                self.assertFalse(reply["ok"])
                self.assertIn("trigger mode", reply["error"])
                self.assertEqual(state.snapshot(), before)
            self.assertTrue(selector.apply_message(state, '{"status":true}')["ok"])

    def test_check_config_reports_black_pipeline_without_hardware(self):
        with patch.object(Path, "read_text", return_value=json.dumps(trigger_config())), \
             patch.object(selector.shutil, "which", side_effect=AssertionError("hardware")), \
             patch.object(sys, "stdout", new_callable=io.StringIO) as output:
            selector.main(["--check-config"])
        report = json.loads(output.getvalue())
        self.assertTrue(report["config"]["trigger_enabled"])
        self.assertIn("pattern=black", report["inactive_pipeline"])
        self.assertNotIn("v4l2src", report["inactive_pipeline"])

    def test_main_opens_configured_pair_and_polarity_only(self):
        for active_low in (False, True):
            config = trigger_config(trigger_left_pin=22, trigger_right_pin=23,
                                    trigger_active_low=active_low)
            buttons = [Mock(), Mock()]
            button = Mock(side_effect=buttons)
            factory = Mock()
            gpio = types.ModuleType("gpiozero")
            gpio.Button = button
            lgpio = types.ModuleType("gpiozero.pins.lgpio")
            lgpio.LGPIOFactory = Mock(return_value=factory)
            event = Mock()
            event.is_set.return_value = True
            worker = Mock(ident=None)
            with self.subTest(active_low=active_low), \
                 patch.object(Path, "read_text", return_value=json.dumps(config)), \
                 patch.object(selector.shutil, "which", return_value="gst-launch-1.0"), \
                 patch.object(selector.signal, "signal"), \
                 patch.object(selector.threading, "Event", return_value=event), \
                 patch.object(selector.threading, "Thread", return_value=worker) as thread, \
                 patch.dict(sys.modules, {"gpiozero": gpio, "gpiozero.pins.lgpio": lgpio}):
                selector.main([])
            self.assertEqual([call.args[0] for call in button.call_args_list], [22, 23])
            for call in button.call_args_list:
                self.assertEqual(call.kwargs["pull_up"], active_low)
            targets = [call.kwargs["target"] for call in thread.call_args_list]
            self.assertEqual(targets, [selector.player, selector.poll_triggers])
            for device in buttons:
                device.close.assert_called_once()
            factory.close.assert_called_once()


class TriggerWorkerTests(unittest.TestCase):
    def test_both_before_launch_reservation_prevents_camera_creation(self):
        config = trigger_config()
        state = selector.State(1, config)
        state.trigger("LEFT")
        build_command = selector.command
        def build(*args):
            result = build_command(*args)
            if args[1] == 1:
                state.trigger("BOTH")
            return result
        with patch.object(selector, "command", side_effect=build), \
             patch.object(selector.subprocess, "Popen", return_value=FakeProcess()) as start:
            selector.player(state, config, FakeStop(lambda _: None))
        start.assert_called_once()
        self.assertIn("pattern=black", start.call_args.args[0])

    def test_both_then_same_side_during_launch_still_cancels_first_process(self):
        config = trigger_config()
        state = selector.State(1, config)
        state.trigger("LEFT")
        first, second = FakeProcess(), FakeProcess()
        launches = []
        def start(*args, **_options):
            launches.append(stop.ticks)
            if len(launches) == 1:
                state.trigger("BOTH")
                state.trigger("LEFT")
                return first
            self.assertTrue(first.terminated)
            return second
        stop = FakeStop(lambda _: None)
        with patch.object(selector.subprocess, "Popen", side_effect=start):
            selector.player(state, config, stop)
        # Invalidation is handled before the first playback polling wait.
        self.assertEqual(launches, [0, 0])
        self.assertTrue(second.terminated)

    def test_shutdown_during_launch_stops_child_without_publishing_camera(self):
        config = trigger_config()
        state = selector.State(1, config)
        state.trigger("RIGHT")
        process = FakeProcess()
        stop = threading.Event()
        def start(*args, **_options):
            stop.set()
            return process
        with patch.object(selector.subprocess, "Popen", side_effect=start) as popen:
            selector.player(state, config, stop)
        popen.assert_called_once()
        self.assertTrue(process.terminated)
        self.assertIsNone(state.snapshot()["pipeline_camera"])
        self.assertEqual(state.snapshot()["display_mode"], "stopped")

    def test_transition_logging_runs_after_publication_without_state_lock(self):
        state = selector.State(1, trigger_config())
        observed = []
        def log(*args):
            unlocked = state.lock.acquire(blocking=False)
            observed.append((unlocked, state.trigger_state, state.selected))
            if unlocked:
                state.lock.release()
        with patch.object(selector.LOG, "info", side_effect=log):
            state.trigger("BOTH")
        self.assertEqual(observed, [(True, "BOTH", None)])

    def test_slow_launch_does_not_block_both_or_status_and_is_discarded(self):
        config = trigger_config()
        state = selector.State(1, config)
        state.trigger("LEFT")
        launch_entered = threading.Event()
        published = threading.Event()
        camera, blank = FakeProcess(), FakeProcess()
        accepted_during_launch = []
        observed = []
        def publish_both():
            if launch_entered.wait(2):
                state.trigger("BOTH")
                observed.append(selector.apply_message(state, '{"status":true}'))
                published.set()
        producer = threading.Thread(target=publish_both)
        def start(*args, **_options):
            if not launch_entered.is_set():
                launch_entered.set()
                accepted_during_launch.append(published.wait(1))
                return camera
            self.assertTrue(camera.terminated)
            return blank
        producer.start()
        try:
            with patch.object(selector.subprocess, "Popen", side_effect=start) as popen:
                selector.player(state, config, FakeStop(lambda _: None))
        finally:
            launch_entered.set()
            producer.join(2)
        self.assertFalse(producer.is_alive())
        self.assertEqual(accepted_during_launch, [True])
        self.assertEqual(observed[0]["trigger_state"], "BOTH")
        self.assertIsNone(observed[0]["pipeline_camera"])
        self.assertTrue(camera.terminated)
        self.assertEqual(popen.call_count, 2)
        self.assertIn("pattern=black", popen.call_args_list[1].args[0])

    def test_fault_is_published_before_diagnostic_logging(self):
        class BrokenInput:
            @property
            def is_pressed(self):
                raise OSError("GPIO disconnected")
        config = trigger_config()
        state = selector.State(1, config)
        state.trigger("LEFT")
        observed = []
        with patch.object(selector.LOG, "exception", side_effect=lambda *args: observed.append(state.snapshot())):
            selector.poll_triggers(state, [BrokenInput(), BrokenInput()], FakeStop(lambda _: None), config)
        self.assertEqual(observed[0]["trigger_state"], "FAULT")
        self.assertIsNone(observed[0]["selected_camera"])

    def test_blink_sequence_keeps_one_capture_until_final_off_timeout(self):
        config = trigger_config()
        state = selector.State(1, config)
        trigger = selector.BlinkerTrigger(config)
        processes = [FakeProcess(), FakeProcess(), FakeProcess()]
        start_times = []
        # Each tick is 50 ms. Two 400 ms OFF gaps precede final cancellation.
        def tick(count):
            active = count < 8 or 16 <= count < 24 or 32 <= count < 40
            state.trigger(trigger.update(active, False, count * 0.05))
        stop = FakeStop(tick, limit=65)
        def start(*args, **_options):
            start_times.append(stop.ticks)
            return processes[len(start_times) - 1]
        with patch.object(selector.subprocess, "Popen", side_effect=start) as popen:
            selector.player(state, config, stop)
        self.assertEqual(popen.call_count, 3)
        self.assertIn("pattern=black", popen.call_args_list[0].args[0])
        self.assertIn("v4l2src", popen.call_args_list[1].args[0])
        self.assertIn("pattern=black", popen.call_args_list[2].args[0])
        self.assertGreaterEqual(start_times[2], 60)
        self.assertTrue(processes[1].terminated)

    def test_polling_uses_configured_interval_and_retains_state_during_gap(self):
        config = trigger_config(trigger_sample_seconds=0.02)
        state = selector.State(1, config)
        buttons = [types.SimpleNamespace(is_pressed=True), types.SimpleNamespace(is_pressed=False)]
        observations, intervals = [], []
        def tick(count):
            observations.append(state.snapshot()["trigger_state"])
            buttons[0].is_pressed = count < 10 or count >= 30
        stop = FakeStop(tick, limit=40)
        original_wait = stop.wait
        def wait(seconds):
            intervals.append(seconds)
            return original_wait(seconds)
        stop.wait = wait
        with patch.object(selector.time, "monotonic", side_effect=lambda: stop.ticks * 0.02):
            selector.poll_triggers(state, buttons, stop, config)
        self.assertEqual(state.snapshot()["selected_camera"], 1)
        self.assertTrue(all(value == "LEFT" for value in observations[6:]))
        self.assertEqual(set(intervals), {0.02})

    def test_read_failure_latches_fault_and_cannot_resume_selection(self):
        class BrokenInput:
            @property
            def is_pressed(self):
                raise OSError("GPIO disconnected")
        config = trigger_config()
        state = selector.State(1, config)
        state.trigger("LEFT")
        with self.assertLogs("selector", level="ERROR"):
            selector.poll_triggers(state, [BrokenInput(), BrokenInput()], FakeStop(lambda _: None), config)
        self.assertEqual(state.snapshot()["trigger_error"], "GPIO disconnected")
        state.trigger("RIGHT")
        self.assertEqual(state.snapshot()["trigger_state"], "FAULT")
        self.assertIsNone(state.snapshot()["selected_camera"])

    def test_startup_and_both_only_open_black_source(self):
        for name in ("IDLE", "BOTH", "FAULT"):
            config = trigger_config()
            state = selector.State(1, config)
            state.trigger(name)
            with self.subTest(name=name), \
                 patch.object(selector.subprocess, "Popen", return_value=FakeProcess()) as start:
                selector.player(state, config, FakeStop(lambda _: None))
            start.assert_called_once()
            self.assertIn("pattern=black", start.call_args.args[0])
            self.assertNotIn("v4l2src", start.call_args.args[0])

    def test_both_stops_either_camera_and_blanks_until_next_turn(self):
        for direction in ("LEFT", "RIGHT"):
            config = trigger_config()
            state = selector.State(1, config)
            state.trigger(direction)
            camera, blank, resumed = FakeProcess(), FakeProcess(), FakeProcess()
            observations = []
            def tick(count):
                observations.append(state.snapshot())
                if count == 1:
                    state.trigger("BOTH")
                if count == 3:
                    self.assertTrue(camera.terminated)
                    state.trigger("LEFT")
            with self.subTest(direction=direction), \
                 patch.object(selector.subprocess, "Popen", side_effect=[camera, blank, resumed]) as start:
                selector.player(state, config, FakeStop(tick))
            self.assertEqual(start.call_count, 3)
            self.assertIn("pattern=black", start.call_args_list[1].args[0])
            self.assertEqual(observations[1]["display_mode"], "blank")
            self.assertIsNone(observations[1]["pipeline_camera"])
            self.assertTrue(blank.terminated)
            self.assertTrue(resumed.terminated)

    def test_rapid_both_transition_cannot_lose_stop_request(self):
        config = trigger_config()
        state = selector.State(1, config)
        state.trigger("LEFT")
        first, next_process = FakeProcess(), FakeProcess()
        def tick(count):
            if count == 1:
                state.trigger("BOTH")
                state.trigger("LEFT")
        with patch.object(selector.subprocess, "Popen", side_effect=[first, next_process]) as start:
            selector.player(state, config, FakeStop(tick))
        self.assertTrue(first.terminated)
        self.assertEqual(start.call_count, 2)

    def test_both_during_slow_teardown_prevents_stale_right_launch(self):
        config = trigger_config(process_stop_timeout_seconds=0.25)
        state = selector.State(1, config)
        state.trigger("LEFT")
        camera, blank = FakeProcess(), FakeProcess()
        def wait(timeout=None):
            self.assertEqual(timeout, 0.25)
            state.trigger("BOTH")
        camera.wait = wait
        stop = FakeStop(lambda count: state.trigger("RIGHT") if count == 1 else None)
        with patch.object(selector.subprocess, "Popen", side_effect=[camera, blank]) as start:
            selector.player(state, config, stop)
        self.assertEqual(start.call_count, 2)
        self.assertIn("pattern=black", start.call_args_list[1].args[0])

    def test_both_cancels_pending_camera_retry(self):
        config = trigger_config()
        state = selector.State(1, config)
        state.trigger("LEFT")
        camera, blank = FakeProcess(), FakeProcess()
        def tick(count):
            if count == 1:
                camera.returncode = 1
            if count == 2:
                state.trigger("BOTH")
        stop = FakeStop(tick, limit=8)
        with patch.object(selector.time, "monotonic", side_effect=lambda: stop.ticks), \
             patch.object(selector.subprocess, "Popen", side_effect=[camera, blank]) as start:
            selector.player(state, config, stop)
        self.assertEqual(start.call_count, 2)
        self.assertIn("pattern=black", start.call_args_list[1].args[0])

    def test_failed_black_output_retries_without_opening_camera(self):
        config = trigger_config()
        state = selector.State(1, config)
        state.trigger("BOTH")
        first, second = FakeProcess(), FakeProcess()
        observed = []
        def tick(count):
            observed.append(state.snapshot())
            if count == 1:
                first.returncode = 1
        stop = FakeStop(tick, limit=5)
        with patch.object(selector.time, "monotonic", side_effect=lambda: stop.ticks), \
             patch.object(selector.subprocess, "Popen", side_effect=[first, second]) as start:
            selector.player(state, config, stop)
        self.assertIsNotNone(observed[1]["last_error"])
        self.assertEqual(start.call_count, 2)
        for call in start.call_args_list:
            self.assertIn("pattern=black", call.args[0])
            self.assertNotIn("v4l2src", call.args[0])


if __name__ == "__main__":
    unittest.main()
