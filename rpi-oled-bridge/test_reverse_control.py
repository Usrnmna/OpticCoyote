"""Reverse GPIO/USB lifecycle tests with synthetic clocks and ports; no hardware."""
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import bridge
import reverse_control as reverse


CONFIG = reverse.load_config(Path(__file__).with_name("reverse.json"))
ARGS = SimpleNamespace(sensor_order=(1, 2, 3, 4), sensor_port="sensor", display_port="display")


class Clock:
    def __init__(self, end_ms=1000):
        self.ms = 0
        self.end_ms = end_ms

    def now(self):
        return self.ms / 1000

    def is_set(self):
        return self.ms >= self.end_ms

    def wait(self, seconds):
        self.ms += round(seconds * 1000)
        return self.is_set()


class Port:
    def __init__(self, clock, sensor=False, reply=True):
        self.clock, self.sensor, self.reply = clock, sensor, reply
        self.writes = []
        self.incoming = bytearray()
        self.token = None
        self.request_id = 0
        self.started = 0
        self.next_report = 0
        self.closed = False
        self.on_write = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True

    def reset_input_buffer(self):
        self.incoming.clear()

    def write(self, packet):
        self.writes.append((self.clock.ms, packet))
        fields = packet.strip().decode().split(",")
        if fields[0] == "R":
            self.token = int(fields[1])
            self.request_id = 0
            self.started = self.clock.ms
            self.next_report = self.clock.ms
        elif fields[0] == "K":
            self.request_id = int(fields[2])
        elif fields[0] == "X":
            self.token = None
        if not self.sensor and self.reply and fields[0] in ("R", "K"):
            self.incoming.extend(f"A,{fields[1]},{self.request_id}\n".encode())
        if self.on_write:
            self.on_write(packet)
        return len(packet)

    @property
    def in_waiting(self):
        if self.sensor and self.reply and self.token and self.clock.ms >= self.next_report:
            self.incoming.extend(f"S,{self.token},{self.request_id},{self.clock.ms-self.started},305,0,610,0,914,0,1219,0\n".encode())
            self.next_report = self.clock.ms + 100
        return len(self.incoming)

    def read(self, count):
        chunk = bytes(self.incoming[:count])
        del self.incoming[:count]
        return chunk


class GateTests(unittest.TestCase):
    def test_sample_overtaken_by_low_cannot_restore_old_high(self):
        gate = reverse.ReverseGate(0)
        gate.observe(True, 0)

        def raced_read():
            gate.cancel()
            return True  # Read began before the LOW callback invalidated it.

        self.assertFalse(gate.sample(raced_read, lambda: 1)[0])
        self.assertFalse(gate.snapshot(2)[0])

    def test_read_completion_starts_high_qualification(self):
        gate = reverse.ReverseGate(0.1)
        clock = Clock()

        def delayed_read():
            clock.ms = 95
            return True

        self.assertFalse(gate.sample(delayed_read, clock.now)[0])
        self.assertFalse(gate.sample(lambda: True, lambda: 0.194)[0])
        self.assertTrue(gate.sample(lambda: True, lambda: 0.195)[0])

    def test_99_100_101ms_and_sustained_high(self):
        gate = reverse.ReverseGate(0.1)
        gate.observe(True, 0)
        self.assertFalse(gate.snapshot(0.099)[0])
        self.assertTrue(gate.snapshot(0.100)[0])
        self.assertTrue(gate.snapshot(0.101)[0])
        self.assertTrue(gate.snapshot(10000)[0])
        gate.observe(False, 10000)
        self.assertFalse(gate.snapshot(10000)[0])

    def test_low_edges_cancel_pending_and_active_generations(self):
        gate = reverse.ReverseGate(0.1)
        gate.observe(True, 0)
        generation = gate.snapshot(0)[1]
        gate.observe(False, 0.099)
        gate.observe(True, 0.100)
        self.assertFalse(gate.snapshot(0.101)[0])
        self.assertNotEqual(generation, gate.snapshot(0.2)[1])
        gate.requalify()
        self.assertFalse(gate.snapshot(100)[0])
        gate.observe(True, 100)
        self.assertFalse(gate.snapshot(100.05)[0])


class FreshnessTests(unittest.TestCase):
    def test_ack_requires_new_recent_known_request(self):
        session = reverse.SensorSession(42, 0)
        self.assertTrue(session.receive_ack(b"A,42,0", 0.1, 1))
        self.assertFalse(session.receive_ack(b"A,42,0", 0.2, 1))
        session.renewal(0.25, 1)
        for row in (b"A,41,1", b"A,42,2", b"A,42", b"A,42,-1", b"A,42,1,0"):
            self.assertFalse(session.receive_ack(row, 0.3, 1))
        self.assertFalse(session.receive_ack(b"A,42,1", 1.25, 1))
        self.assertFalse(session.receive(b"S,42,1,300,1,0,2,0,3,0,4,0", 1.25, 1))
        session.renewal(1.25, 1)
        self.assertTrue(session.receive_ack(b"A,42,2", 1.3, 1))
        self.assertFalse(session.receive_ack(b"A,42,1", 1.3, 1))

    def test_per_sensor_age_and_order(self):
        session = reverse.SensorSession(42, 10)
        self.assertEqual(session.renewal(11, 1), b"K,42,1\n")
        self.assertTrue(session.receive(b"S,42,1,1000,305,1000,610,0,-1,0,1219,100", 11.1, 1))
        self.assertEqual(session.packet(11.6, 1.5, (1, 2, 3, 4)), b"D,42,-1,610,-1,1219\n")
        self.assertEqual(session.packet(11.6, 1.5, (4, 3, 2, 1)), b"D,42,1219,-1,610,-1\n")
        self.assertEqual(session.packet(13, 1.5, (1, 2, 3, 4)), b"D,42,-1,-1,-1,-1\n")

    def test_stale_wrong_session_duplicate_and_unsent_request_do_not_refresh(self):
        session = reverse.SensorSession(42, 0)
        row = b"S,42,0,100,305,0,610,0,914,0,1219,0"
        self.assertTrue(session.receive(row, 0.2, 1))
        for candidate, now in ((row, 0.3), (row.replace(b"42", b"41"), 0.3),
                               (row.replace(b",100,", b",200,"), 5),
                               (row.replace(b"42,0,100", b"42,1,200"), 0.3),
                               (row.replace(b",100,", b",99,"), 0.3)):
            self.assertFalse(session.receive(candidate, now, 1))
        self.assertEqual(session.received_at, 0.2)

    def test_malformed_packets_commit_nothing(self):
        session = reverse.SensorSession(42, 0)
        for row in (b"S,42,0,0,1,0,2,0,3,0,4", b"S,42,0,0,-2,0,2,0,3,0,4,0",
                    b"S,42,0,0,1,1,2,0,3,0,4,0", b"S,42,0,0,-1,1,2,0,3,0,4,0",
                    b"S,42,0,0,1.0,0,2,0,3,0,4,0", b"S,42,0,0,30001,0,2,0,3,0,4,0"):
            self.assertFalse(session.receive(row, 0, 1))
            self.assertIsNone(session.received_at)

    def test_elapsed_millis_rollover(self):
        session = reverse.SensorSession(42, 0)
        session.renewal(4294967.25, 1)
        self.assertTrue(session.receive(b"S,42,1,4294967280,1,0,2,0,3,0,4,0", 4294967.3, 1))
        self.assertTrue(session.receive(b"S,42,1,20,1,0,2,0,3,0,4,0", 4294967.4, 1))
        self.assertEqual(session.elapsed_ms, 4294967316)

    def test_long_session_does_not_require_synchronized_nano_clock(self):
        for rate in (0.99, 1.01):
            session = reverse.SensorSession(42, 0)
            for seconds in range(1, 3601):
                session.renewal(seconds, 1)
                tick = int(seconds * 1000 * rate)
                row = f"S,42,{session.request_id},{tick},305,100,610,0,-1,0,1219,0".encode()
                self.assertTrue(session.receive(row, seconds + 0.1, 1))
                self.assertLessEqual(len(session.requests), 2)
            self.assertEqual(session.packet(3600.2, 1.5, (1, 2, 3, 4)), b"D,42,305,610,-1,1219\n")

    def test_delayed_snapshot_cannot_borrow_a_later_renewal_time(self):
        session = reverse.SensorSession(42, 0)
        session.renewal(0.25, 1)
        session.renewal(1.1, 1)
        self.assertFalse(session.receive(b"S,42,0,100,305,0,610,0,914,0,1219,0", 1.1, 1))
        self.assertTrue(session.receive(b"S,42,1,300,305,0,610,0,914,0,1219,0", 1.1, 1))
        self.assertEqual(session.packet(1.3, 1, (1, 2, 3, 4)), b"D,42,-1,-1,-1,-1\n")
        session.request_id = reverse.UINT32_MAX
        with self.assertRaisesRegex(OSError, "sequence exhausted"):
            session.renewal(1.5, 1)


class LifecycleTests(unittest.TestCase):
    def test_usb_fault_reopens_both_ports_and_requalifies_current_input(self):
        for stay_high in (True, False):
            with self.subTest(stay_high=stay_high):
                clock = Clock(900)
                ports = []
                tokens = iter((42, 43))
                factory = SimpleNamespace(close=lambda: None)

                class Input:
                    when_deactivated = None

                    def __enter__(self):
                        return self

                    def __exit__(self, *_args):
                        self.closed = True

                    @property
                    def is_active(self):
                        return stay_high or clock.ms < 400

                device = Input()

                def open_port(name, **_options):
                    port = Port(clock, sensor=name == "sensor")
                    if not ports:
                        def unplug(packet):
                            if packet.startswith(b"K,"):
                                raise OSError("USB disconnected during renewal")
                        port.on_write = unplug
                    ports.append(port)
                    return port

                module = SimpleNamespace(Serial=open_port, SerialException=OSError)
                original_pump = reverse.pump

                def simulated_pump(*args):
                    return original_pump(*args, clock=clock.now, new_token=lambda: next(tokens))

                config = {**CONFIG, "reverse_gpio_pin": 22, "boot_ms": 0, "reconnect_ms": 100}
                modules = {"gpiozero": SimpleNamespace(DigitalInputDevice=lambda *_a, **_k: device),
                           "gpiozero.pins.lgpio": SimpleNamespace(LGPIOFactory=lambda: factory)}
                with patch.dict("sys.modules", modules), \
                        patch.object(reverse, "load_config", return_value=config), \
                        patch.object(reverse, "pump", side_effect=simulated_pump), \
                        patch.object(factory, "close") as close_factory:
                    self.assertEqual(reverse.run(module, SimpleNamespace(**vars(ARGS), reverse_config="test"), clock), 0)
                self.assertEqual(len(ports), 4)
                self.assertTrue(all(port.closed for port in ports))
                self.assertTrue(device.closed)
                close_factory.assert_called_once()
                for port in ports:
                    self.assertEqual(port.writes[-1][1], b"\nX\n")
                restarted = [when for when, data in ports[2].writes if data.startswith(b"\nR,43,")]
                if stay_high:
                    self.assertEqual(len(restarted), 1)
                    self.assertGreaterEqual(restarted[0], 550)
                    self.assertTrue(any(data.startswith(b"D,43,") for _, data in ports[3].writes))
                else:
                    self.assertFalse(restarted)
                    self.assertFalse(any(data.startswith(b"D,") for _, data in ports[3].writes))

    def test_expired_queued_display_ack_cannot_restore_liveness(self):
        clock = Clock(2000)

        class DelayedAckPort(Port):
            @property
            def in_waiting(self):
                if self.clock.ms >= 1100:
                    self.incoming.extend(b"A,42,0\n")
                return super().in_waiting

        sensor, display = Port(clock, True), DelayedAckPort(clock, reply=False)
        reverse.pump(sensor, display, ARGS, CONFIG, clock, reverse.ReverseGate(0.1),
                     lambda: True, clock.now, new_token=lambda: 42)
        self.assertTrue(display.closed)
        self.assertIn((1100, b"\nX\n"), display.writes)
        self.assertFalse(any(packet.startswith(b"D,") for _, packet in display.writes))
        self.assertTrue(any(at > 1100 and packet.startswith(b"K,") for at, packet in sensor.writes))

    def test_reply_at_liveness_deadline_cannot_revive_the_link(self):
        clock = Clock(2000)

        class LateAckPort(Port):
            @property
            def in_waiting(self):
                if self.clock.ms >= 1100:
                    # The ID itself is recent, but no ACK arrived before the
                    # acquisition's acknowledgement deadline expired.
                    self.incoming.extend(f"A,42,{self.request_id}\n".encode())
                return super().in_waiting

        sensor, display = Port(clock, True), LateAckPort(clock, reply=False)
        reverse.pump(sensor, display, ARGS, CONFIG, clock, reverse.ReverseGate(0.1),
                     lambda: True, clock.now, new_token=lambda: 42)
        self.assertTrue(display.closed)
        self.assertIn((1100, b"\nX\n"), display.writes)
        self.assertFalse(any(packet.startswith(b"D,") for _, packet in display.writes))
        self.assertTrue(any(at > 1100 and packet.startswith(b"K,") for at, packet in sensor.writes))

    def test_delayed_gpio_read_does_not_qualify_a_99ms_pulse(self):
        clock = Clock(300)
        sensor, display = Port(clock, True), Port(clock)

        def read_gpio():
            if clock.ms == 0:
                clock.ms = 95
            return clock.ms < 194

        reverse.pump(sensor, display, ARGS, CONFIG, clock, reverse.ReverseGate(0.1),
                     read_gpio, clock.now)
        self.assertFalse(sensor.writes or display.writes)

    def test_low_during_start_cancels_without_gpio_callback(self):
        clock = Clock(500)
        sensor, display = Port(clock, True), Port(clock)
        high = True

        def drop_input(packet):
            nonlocal high
            if b"R," in packet:
                high = False

        sensor.on_write = drop_input
        reverse.pump(sensor, display, ARGS, CONFIG, clock, reverse.ReverseGate(0.1),
                     lambda: high, clock.now, new_token=lambda: 42)
        self.assertEqual(display.writes, [(100, b"\nX\n")])
        self.assertEqual(sensor.writes[-1], (100, b"\nX\n"))

    def test_low_during_distance_write_releases_both_and_suppresses_followups(self):
        clock = Clock(500)
        sensor, display = Port(clock, True), Port(clock)
        gate = reverse.ReverseGate(0.1)
        high = True

        def drop_input(packet):
            nonlocal high
            if packet.startswith(b"D,"):
                high = False
                gate.cancel()

        display.on_write = drop_input
        reverse.pump(sensor, display, ARGS, CONFIG, clock, gate,
                     lambda: high, clock.now, new_token=lambda: 42)
        self.assertEqual(sum(data.startswith(b"D,") for _, data in display.writes), 1)
        self.assertEqual(sensor.writes[-1][1], b"\nX\n")
        self.assertEqual(display.writes[-1][1], b"\nX\n")

    def exercise(self, high_until=500, end_ms=1000, hook=None, display_reply=True, sensor_reply=True):
        clock = Clock(end_ms)
        sensor, display = Port(clock, True, sensor_reply), Port(clock, False, display_reply)
        gate = reverse.ReverseGate(0.1)
        if hook:
            sensor.on_write = lambda data: hook(data, clock, gate)
        reverse.pump(sensor, display, ARGS, CONFIG, clock, gate,
                     lambda: clock.ms < high_until, clock.now, new_token=lambda: 42)
        return sensor, display

    def test_short_high_never_starts(self):
        sensor, display = self.exercise(high_until=99)
        self.assertFalse(sensor.writes or display.writes)

    def test_low_at_qualification_deadline_takes_priority(self):
        sensor, display = self.exercise(high_until=100)
        self.assertFalse(sensor.writes or display.writes)
        sensor, display = self.exercise(high_until=101)
        self.assertEqual(sensor.writes[0], (100, b"\nR,42,1500\n"))
        self.assertEqual(display.writes[-1], (105, b"\nX\n"))

    def test_high_starts_low_releases_and_no_later_distance_packets(self):
        sensor, display = self.exercise()
        self.assertEqual(sensor.writes[0], (100, b"\nR,42,1500\n"))
        self.assertIn((500, b"\nX\n"), sensor.writes)
        self.assertEqual(display.writes[-1], (500, b"\nX\n"))
        self.assertTrue(any(data.startswith(b"D,42,305,610,914,1219") for _, data in display.writes))

    def test_sustained_high_renews_without_restarting(self):
        sensor, display = self.exercise(high_until=10000, end_ms=5000)
        for port in (sensor, display):
            self.assertEqual(sum(b"R," in data for _, data in port.writes), 1)
            self.assertGreater(sum(data.startswith(b"K,") for _, data in port.writes), 10)
            self.assertFalse(any(b"X" in data for _, data in port.writes))

    def test_reengagement_requalifies_and_rejects_previous_session_data(self):
        clock = Clock(900)
        sensor, display = Port(clock, True), Port(clock)
        tokens = iter((42, 43))

        def delayed_old_packet(packet):
            if packet.startswith(b"\nR,43,"):
                sensor.reply = False
                sensor.incoming.extend(b"S,42,0,300,305,0,610,0,914,0,1219,0\n")

        sensor.on_write = delayed_old_packet
        reverse.pump(sensor, display, ARGS, CONFIG, clock, reverse.ReverseGate(0.1),
                     lambda: clock.ms < 250 or clock.ms >= 300, clock.now,
                     new_token=lambda: next(tokens))
        starts = [(when, data) for when, data in sensor.writes if b"R," in data]
        self.assertEqual(len(starts), 2)
        self.assertGreaterEqual(starts[1][0], 400)
        self.assertIn((250, b"\nX\n"), sensor.writes)
        self.assertTrue(any(data.startswith(b"D,42,") for _, data in display.writes))
        self.assertFalse(any(data.startswith(b"D,43,") for _, data in display.writes))

    def test_low_during_start_write_prevents_display_start(self):
        def interrupt(packet, clock, gate):
            if b"R," in packet:
                gate.observe(False, clock.now())
                clock.ms = 500
        sensor, display = self.exercise(hook=interrupt)
        self.assertEqual(display.writes, [(500, b"\nX\n")])
        self.assertEqual(sensor.writes[-1][1], b"\nX\n")

    def test_low_then_high_during_write_cannot_preserve_old_generation(self):
        def interrupt(packet, clock, gate):
            if b"R," in packet:
                gate.observe(False, clock.now())
                gate.observe(True, clock.now())
                clock.ms = 500
        sensor, display = self.exercise(hook=interrupt)
        self.assertEqual(display.writes[0][1], b"\nX\n")
        self.assertFalse(any(b"R," in data for _, data in display.writes))

    def test_missing_sensor_ack_faults_but_missing_display_ack_keeps_ranging(self):
        with self.assertRaisesRegex(OSError, "acknowledgement expired"):
            self.exercise(high_until=10000, end_ms=2000, sensor_reply=False)
        sensor, display = self.exercise(high_until=10000, end_ms=2000, display_reply=False)
        self.assertTrue(display.closed)
        self.assertTrue(any(at > 1100 and packet.startswith(b"K,") for at, packet in sensor.writes))
        self.assertFalse(any(b"X" in packet for _, packet in sensor.writes))

    def test_release_attempts_both_ports_after_first_failure(self):
        sensor = SimpleNamespace(write=lambda _: (_ for _ in ()).throw(OSError("unplugged")))
        display = Port(Clock())
        with self.assertRaises(OSError):
            reverse.release(sensor, display)
        self.assertEqual(display.writes[0][1], b"\nX\n")

    def test_run_session_cleans_up_on_gpio_fault(self):
        clock = Clock()
        sensor, display = Port(clock, True), Port(clock)
        module = SimpleNamespace(Serial=lambda name, **_: sensor if name == "sensor" else display)
        with self.assertRaises(ValueError):
            reverse.run_session(module, ARGS, {**CONFIG, "boot_ms": 0}, clock,
                                reverse.ReverseGate(0.1), lambda: (_ for _ in ()).throw(ValueError("GPIO failed")))
        self.assertTrue(sensor.closed)
        self.assertFalse(display.closed)
        self.assertEqual(sensor.writes[-1][1], b"\nX\n")
        self.assertFalse(display.writes)

    def test_second_port_open_failure_keeps_sensor_session_until_low(self):
        clock = Clock(800)
        sensor = Port(clock, True)

        def open_port(name, **_options):
            if name == "display":
                raise OSError("display disconnected")
            return sensor

        original_pump = reverse.pump
        def simulated_pump(*args):
            return original_pump(*args, clock=clock.now, new_token=lambda: 42)
        with patch.object(reverse, "pump", side_effect=simulated_pump):
            reverse.run_session(SimpleNamespace(Serial=open_port), ARGS, {**CONFIG, "boot_ms": 0},
                                clock, reverse.ReverseGate(0.1), lambda: clock.ms < 650)
        self.assertTrue(sensor.closed)
        self.assertIn((100, b"\nR,42,1500\n"), sensor.writes)
        self.assertIn((650, b"\nX\n"), sensor.writes)
        self.assertTrue(any(packet.startswith(b"K,") for _, packet in sensor.writes))


class DisplayIsolationTests(unittest.TestCase):
    def test_delayed_gpio_check_recomputes_distance_ages_before_write(self):
        clock = Clock(325)
        sensor, oled = Port(clock, True), Port(clock)
        config = {**CONFIG, "distance_stale_ms": 100}
        pending_delay = False
        original_read = oled.read

        def read_ack(count):
            nonlocal pending_delay
            pending_delay = True
            return original_read(count)

        def read_gpio():
            nonlocal pending_delay
            if pending_delay:
                pending_delay = False
                clock.ms += 200
            return True

        oled.read = read_ack
        reverse.pump(sensor, oled, ARGS, config, clock, reverse.ReverseGate(0.1),
                     read_gpio, clock.now, new_token=lambda: 42)
        distances = [(at, data) for at, data in oled.writes if data.startswith(b"D,")]
        self.assertEqual(distances, [(300, b"D,42,-1,-1,-1,-1\n")])

    def test_stop_during_prewrite_gpio_read_cancels_unsent_distance(self):
        clock = Clock(1000)
        sensor, oled = Port(clock, True), Port(clock)
        cancel_on_sample = False
        original_read = oled.read

        def read_ack(count):
            nonlocal cancel_on_sample
            cancel_on_sample = True
            return original_read(count)

        def read_gpio():
            if cancel_on_sample:
                clock.end_ms = clock.ms
            return True

        oled.read = read_ack
        reverse.pump(sensor, oled, ARGS, CONFIG, clock, reverse.ReverseGate(0.1),
                     read_gpio, clock.now, new_token=lambda: 42)
        self.assertFalse(any(data.startswith(b"D,") for _, data in oled.writes))
        self.assertEqual(sensor.writes[-1][1], b"\nX\n")
        self.assertEqual(oled.writes[-1][1], b"\nX\n")

    def test_delayed_gpio_check_cannot_write_after_display_ack_expiry(self):
        clock = Clock(1500)
        sensor, oled = Port(clock, True), Port(clock)
        pending_delay = False
        original_read = oled.read

        def read_ack(count):
            nonlocal pending_delay
            pending_delay = True
            return original_read(count)

        def read_gpio():
            nonlocal pending_delay
            if pending_delay:
                pending_delay = False
                clock.ms = 1100
            return True

        oled.read = read_ack
        with self.assertRaisesRegex(OSError, "Sensor telemetry"):
            reverse.pump(sensor, oled, ARGS, CONFIG, clock, reverse.ReverseGate(0.1),
                         read_gpio, clock.now, new_token=lambda: 42)
        self.assertTrue(oled.closed)
        self.assertFalse(any(data.startswith(b"D,") for _, data in oled.writes))

    def test_fault_observer_failure_cannot_interrupt_sensor_or_display_cleanup(self):
        clock = Clock(750)
        sensor, oled = Port(clock, True), Port(clock)

        def fail_renewal(packet):
            if packet.startswith(b"K,"):
                raise OSError("OLED disconnected")

        def observer(_error):
            raise RuntimeError("observer failed")

        oled.on_write = fail_renewal
        link = reverse.DisplayLink(CONFIG, port=oled, on_fault=observer)
        with self.assertLogs(reverse.LOGGER, level="WARNING") as logs:
            reverse.pump(sensor, link, ARGS, CONFIG, clock, reverse.ReverseGate(0.1),
                         lambda: clock.ms < 700, clock.now, new_token=lambda: 42)
        self.assertTrue(any("observer failed" in item for item in logs.output))
        self.assertTrue(oled.closed)
        self.assertIsNone(link.session)
        self.assertTrue(any(at > 350 and data.startswith(b"K,") for at, data in sensor.writes))
        self.assertEqual(sensor.writes[-1], (700, b"\nX\n"))
        link.close()

    def test_sensor_release_failure_still_closes_optional_oled(self):
        clock = Clock(300)
        sensor, oled = Port(clock, True), Port(clock)
        sensor.on_write = lambda packet: (_ for _ in ()).throw(OSError("sensor release failed")) if clock.ms >= 300 and b"X" in packet else None
        serial = SimpleNamespace(Serial=lambda role, **_options: sensor if role == "sensor" else oled)
        original_pump = reverse.pump
        def simulated_pump(*args):
            return original_pump(*args, clock=clock.now, new_token=lambda: 42)
        with patch.object(reverse, "pump", side_effect=simulated_pump):
            reverse.run_session(serial, ARGS, {**CONFIG, "boot_ms": 0}, clock,
                                reverse.ReverseGate(0.1), lambda: True)
        self.assertTrue(sensor.closed and oled.closed)
        self.assertEqual(oled.writes[-1], (300, b"\nX\n"))

    def test_display_open_retry_and_boot_do_not_restart_sensor_acquisition(self):
        clock = Clock(1200)
        sensor, oled = Port(clock, True), Port(clock)
        config = {**CONFIG, "boot_ms": 200, "reconnect_ms": 300}
        opens = []

        def open_display():
            opens.append(clock.ms)
            if len(opens) == 1:
                raise OSError("OLED missing")
            return oled

        link = reverse.DisplayLink(config, open_port=open_display)
        reverse.pump(sensor, link, ARGS, config, clock, reverse.ReverseGate(0.1),
                     lambda: clock.ms < 1000, clock.now, new_token=lambda: 42)
        self.assertEqual(opens, [0, 300])
        self.assertEqual([at for at, data in sensor.writes if b"R," in data], [100])
        self.assertTrue(any(at < 500 and data.startswith(b"K,") for at, data in sensor.writes))
        self.assertEqual([at for at, data in oled.writes if b"R," in data], [500])
        self.assertTrue(any(data.startswith(b"D,") for _, data in oled.writes))
        self.assertIn((1000, b"\nX\n"), sensor.writes)
        link.close()

    def test_display_read_and_write_failures_reconnect_with_fresh_token_and_ack(self):
        for failure in ("read", "write"):
            with self.subTest(failure=failure):
                clock = Clock(900)
                sensor, first, second = Port(clock, True), Port(clock), Port(clock)
                config = {**CONFIG, "boot_ms": 0, "reconnect_ms": 100}
                if failure == "write":
                    first.on_write = lambda packet: (_ for _ in ()).throw(OSError("unplugged")) if packet.startswith(b"K,") else None
                else:
                    original_read = first.read
                    def broken_read(count):
                        if clock.ms >= 350:
                            raise OSError("OLED read failed")
                        return original_read(count)
                    first.read = broken_read
                link = reverse.DisplayLink(config, port=first, open_port=lambda: second)
                with patch.object(reverse.secrets, "randbelow", return_value=42):
                    reverse.pump(sensor, link, ARGS, config, clock, reverse.ReverseGate(0.1),
                                 lambda: clock.ms < 800, clock.now, new_token=lambda: 42)
                self.assertTrue(first.closed)
                self.assertEqual(sum(b"R," in data for _, data in sensor.writes), 1)
                self.assertTrue(any(at > 400 and data.startswith(b"K,") for at, data in sensor.writes))
                self.assertTrue(any(data.startswith(b"\nR,43,") for _, data in second.writes))
                self.assertTrue(any(data.startswith(b"D,43,") for _, data in second.writes))
                self.assertIn((800, b"\nX\n"), sensor.writes)
                link.close()

    def test_low_during_oled_reopen_boot_or_acquisition_cancels_both_links(self):
        for stage in ("open", "boot", "before_start", "after_start"):
            with self.subTest(stage=stage):
                clock = Clock(700)
                sensor, oled = Port(clock, True), Port(clock)
                gate = reverse.ReverseGate(0.1)
                high = True
                config = {**CONFIG, "boot_ms": 200 if stage == "boot" else 0, "reconnect_ms": 300}
                attempts = []

                def drop():
                    nonlocal high
                    high = False
                    gate.cancel()

                def open_display():
                    attempts.append(clock.ms)
                    if len(attempts) == 1:
                        raise OSError("OLED absent")
                    if stage == "open":
                        drop()
                    if stage == "before_start":
                        oled.reset_input_buffer = drop
                    if stage == "after_start":
                        oled.on_write = lambda packet: drop() if b"R," in packet else None
                    return oled

                def input_level():
                    if stage == "boot" and clock.ms >= 400:
                        drop()
                    return high

                link = reverse.DisplayLink(config, open_port=open_display)
                reverse.pump(sensor, link, ARGS, config, clock, gate, input_level, clock.now, new_token=lambda: 42)
                low_ms = 400 if stage == "boot" else 300
                self.assertIn((low_ms, b"\nX\n"), sensor.writes)
                self.assertFalse(any(at > low_ms and data.startswith((b"K,", b"D,")) for port in (sensor, oled) for at, data in port.writes))
                starts = [packet for _, packet in oled.writes if b"R," in packet]
                self.assertEqual(len(starts), 1 if stage == "after_start" else 0)
                link.close()

    def test_reconnected_display_does_not_revive_stale_sensor_values_or_old_acks(self):
        for acknowledge in (True, False):
            with self.subTest(acknowledge=acknowledge):
                clock = Clock(1400)

                class AgingSensor(Port):
                    @property
                    def in_waiting(self):
                        if self.token and self.clock.ms >= self.next_report:
                            age = self.clock.ms - self.started
                            self.incoming.extend(f"S,{self.token},{self.request_id},{age},305,{age},610,{age},914,{age},1219,{age}\n".encode())
                            self.next_report = self.clock.ms + 100
                        return len(self.incoming)

                sensor, first, second = AgingSensor(clock, True), Port(clock), Port(clock, reply=acknowledge)
                config = {**CONFIG, "boot_ms": 0, "reconnect_ms": 100, "distance_stale_ms": 200}
                first.on_write = lambda data: (_ for _ in ()).throw(OSError("unplugged")) if data.startswith(b"K,") else None
                second.on_write = lambda data: second.incoming.extend(b"A,42,0\n") if b"R," in data else None
                link = reverse.DisplayLink(config, port=first, open_port=lambda: second)
                with patch.object(reverse.secrets, "randbelow", return_value=42):
                    reverse.pump(sensor, link, ARGS, config, clock, reverse.ReverseGate(0.1),
                                 lambda: clock.ms < 1300, clock.now, new_token=lambda: 42)
                packets = [data for _, data in second.writes if data.startswith(b"D,")]
                if acknowledge:
                    self.assertTrue(packets)
                    self.assertTrue(all(data == b"D,43,-1,-1,-1,-1\n" for data in packets))
                else:
                    self.assertFalse(packets)
                self.assertEqual(sum(b"R," in data for _, data in sensor.writes), 1)
                link.close()

    def test_delayed_display_read_cannot_restore_expired_ack_deadline(self):
        clock = Clock(1500)
        sensor, oled = Port(clock, True), Port(clock)
        original_read = oled.read
        def delayed_read(count):
            clock.ms = 1100
            return original_read(count)
        oled.read = delayed_read
        # This artificial blocking read also expires sensor telemetry; neither
        # link may claim health after the resulting observation gap.
        with self.assertRaisesRegex(OSError, "Sensor telemetry"):
            reverse.pump(sensor, oled, ARGS, CONFIG, clock, reverse.ReverseGate(0.1),
                         lambda: True, clock.now, new_token=lambda: 42)
        self.assertTrue(oled.closed)
        self.assertFalse(any(data.startswith(b"D,") for _, data in oled.writes))


class ConfigTests(unittest.TestCase):
    def test_duplicate_settings_are_rejected_instead_of_last_value_winning(self):
        raw = json.dumps(CONFIG).replace('"reverse_gpio_pin": null', '"reverse_gpio_pin": null, "reverse_gpio_pin": 22')
        with patch.object(Path, "read_text", return_value=raw), self.assertRaisesRegex(ValueError, "Duplicate"):
            reverse.load_config("unused")

    def test_config_limits_unknown_keys_and_timing_relationships(self):
        for key, value in (("reverse_gpio_pin", True), ("reverse_gpio_pin", 28),
                           ("reverse_high_qualify_ms", -1), ("reverse_low_qualify_ms", 10),
                           ("reverse_sample_ms", 0), ("sensor_lease_ms", 300),
                           ("idle_display_mode", "distance"), ("typo", 0)):
            with patch.object(Path, "read_text", return_value=json.dumps({**CONFIG, key: value})):
                with self.assertRaises(ValueError):
                    reverse.load_config("unused")

    def test_offline_configuration_does_not_import_hardware(self):
        path = str(Path(__file__).with_name("reverse.json"))
        with patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(bridge.main(["--reverse-config", path, "--check-config"]), 0)
        self.assertEqual(json.loads(output.getvalue()), CONFIG)


if __name__ == "__main__":
    unittest.main()
