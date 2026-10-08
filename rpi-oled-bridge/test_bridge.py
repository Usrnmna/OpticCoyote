"""USB protocol/lifecycle checks with fake ports; no attached devices needed."""

import contextlib
import io
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import bridge


HEADER = b"time_ms,front_left_mm,front_right_mm,rear_left_mm,rear_right_mm,nearest_zone,nearest_mm,state"
ROW = b"100,305,610,914,1219,front_left,305,WARNING"


class FakeStop:
    def __init__(self):
        self.stopped = False

    def is_set(self):
        return self.stopped

    def wait(self, _seconds):
        return self.stopped


class FakePort:
    def __init__(self, stop=None, reads=(), fail_write=False):
        self.stop = stop
        self.reads = list(reads)
        self.writes = []
        self.closed = False
        self.reset = False
        self.fail_write = fail_write

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True

    @property
    def in_waiting(self):
        return len(self.reads[0]) if self.reads else 0

    def read(self, count):
        assert 1 <= count <= 4096
        if self.reads:
            return self.reads.pop(0)
        self.stop.stopped = True
        return b""

    def write(self, data):
        if self.fail_write:
            raise OSError("unplugged")
        self.writes.append(data)
        return len(data)

    def reset_input_buffer(self):
        self.reset = True


class BridgeTests(unittest.TestCase):
    def test_existing_csv_and_sensor_order(self):
        values = bridge.parse_sensor_row(ROW)
        self.assertEqual(values, (305, 610, 914, 1219))
        self.assertEqual(bridge.display_packet(values, (1, 2, 3, 4)), b"D,305,610,914,1219\n")
        self.assertEqual(bridge.display_packet(values, (4, 3, 2, 1)), b"D,1219,914,610,305\n")

    def test_missing_zero_maximum_and_rollover(self):
        self.assertEqual(bridge.parse_sensor_row(b"4294967295,-1,0,30000,5000,none,-1,NO_VALID_SENSORS"),
                         (-1, 0, 30000, 5000))
        self.assertIsNotNone(bridge.parse_sensor_row(ROW.replace(b"100,", b"0,", 1)))

    def test_edited_zone_names_keep_column_mapping(self):
        self.assertTrue(bridge.is_sensor_header(HEADER.replace(b"front_left", b"rear-left sensor")))
        self.assertEqual(bridge.parse_sensor_row(ROW.replace(b"front_left", b"rear-left sensor")),
                         (305, 610, 914, 1219))

    def test_malformed_rows_do_not_become_distances(self):
        bad_rows = [HEADER, ROW + b",extra", ROW[:-1], ROW.replace(b"305", b"NaN"),
                    ROW.replace(b"305", b"-2"), ROW.replace(b"305", b"30001"),
                    ROW.replace(b"305", b"1.0"), ROW.replace(b"305", b"+1"),
                    ROW.replace(b"305", b" 1"), ROW.replace(b"305", b""),
                    ROW.replace(b"100,", b"4294967296,", 1), b"\0" + ROW,
                    ROW.replace(b"WARNING", b"BROKEN"), ROW.replace(b"front_left", b"\xff")]
        for row in bad_rows:
            with self.subTest(row=row):
                self.assertIsNone(bridge.parse_sensor_row(row))

    def test_partial_and_multiple_lines(self):
        framer = bridge.LineFramer()
        self.assertEqual(framer.feed(ROW[:10]), [])
        self.assertEqual(framer.feed(ROW[10:] + b"\r\n" + ROW + b"\n"), [ROW, ROW])

    def test_oversized_line_drops_suffix_and_recovers(self):
        framer = bridge.LineFramer()
        self.assertEqual(framer.feed(b"x" * 10000 + ROW + b"\n"), [])
        self.assertLessEqual(len(framer.pending), bridge.MAX_LINE_BYTES)
        self.assertEqual(framer.feed(ROW + b"\n"), [ROW])

    def test_stale_data_and_invalid_traffic(self):
        state = bridge.BridgeState()
        invalid = b"D,-1,-1,-1,-1\n"
        self.assertEqual(state.packet(0, 2, (1, 2, 3, 4)), invalid)
        state.receive(ROW + b"\n", 10)
        self.assertEqual(state.packet(11.99, 2, (1, 2, 3, 4)), b"D,305,610,914,1219\n")
        state.receive(b"noise\n" + ROW[:-1] + b"\n", 11.9)
        self.assertEqual(state.packet(12, 2, (1, 2, 3, 4)), invalid)
        state.receive(ROW + b"\n", 13)
        self.assertNotEqual(state.packet(13, 2, (1, 2, 3, 4)), invalid)

    def test_new_stream_header_clears_previous_values(self):
        state = bridge.BridgeState()
        state.receive(ROW + b"\n", 10)
        state.receive(HEADER + b"\r\n", 11)
        self.assertEqual(state.packet(11, 2, (1, 2, 3, 4)), b"D,-1,-1,-1,-1\n")

    def test_latest_row_wins_without_pending_display_queue(self):
        state = bridge.BridgeState()
        state.receive(ROW + b"\n" + ROW.replace(b"610", b"2000") + b"\n", 1)
        self.assertEqual(state.packet(1, 2, (1, 2, 3, 4)), b"D,305,2000,914,1219\n")

    def test_short_write_ends_session(self):
        with self.assertRaises(OSError):
            bridge.write_packet(SimpleNamespace(write=lambda _data: 2), b"D,1,2,3,4\n")

    def test_same_device_alias_and_argument_validation(self):
        self.assertTrue(bridge.same_device("nano", "./nano"))
        with patch.object(bridge.os.path, "samefile", return_value=True):
            self.assertTrue(bridge.same_device("sensor-link", "display-link"))
        for options in (["--sensor-order", "1", "1", "3", "4"],
                        ["--stale-seconds", "nan"], ["--boot-seconds", "0"],
                        ["--stale-seconds", "inf"]):
            with self.subTest(options=options), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    bridge.parse_args(["--list-ports", *options])

    def test_pump_partial_input_periodic_start_and_stale_output(self):
        stop = FakeStop()
        sensor = FakePort(stop, [ROW[:10], ROW[10:] + b"\n", b"", b""])
        display = FakePort()
        times = iter([0, 0, 0.05, 0.1, 2.2, 2.2, 4.3, 4.3, 4.4, 4.4])
        args = SimpleNamespace(stale_seconds=2, sensor_order=(1, 2, 3, 4))
        bridge.pump(sensor, display, args, stop, clock=lambda: next(times))
        self.assertEqual(sensor.writes, [b"\nSTART\n"] * 3)
        self.assertEqual(display.writes[:3], [b"D,-1,-1,-1,-1\n", b"D,305,610,914,1219\n",
                                             b"D,-1,-1,-1,-1\n"])

    def test_session_cleanup_and_new_session_do_not_replay_old_values(self):
        args = SimpleNamespace(sensor_port="sensor", display_port="display",
                               boot_seconds=2, stale_seconds=2, sensor_order=(1, 2, 3, 4))
        for incoming in ([ROW + b"\n"], []):
            stop = FakeStop()
            display = FakePort()
            sensor = FakePort(stop, incoming)
            module = SimpleNamespace(SerialException=OSError,
                                     Serial=lambda path, **_kw: sensor if path == "sensor" else display)
            bridge.run_session(module, args, stop)
            self.assertTrue(sensor.closed and display.closed)
            self.assertTrue(sensor.reset and display.reset)
            self.assertEqual(sensor.writes[-1], b"\nSTOP\n")
            self.assertEqual(display.writes[0], b"\nD,-1,-1,-1,-1\n")
            self.assertEqual(display.writes[-1], b"\nD,-1,-1,-1,-1\n")
            if not incoming:
                self.assertNotIn(b"D,305,610,914,1219\n", display.writes)

    def test_failure_closes_already_opened_port(self):
        display = FakePort()
        args = SimpleNamespace(sensor_port="sensor", display_port="display")

        def open_port(path, **_options):
            if path == "sensor":
                raise OSError("sensor unplugged")
            return display

        module = SimpleNamespace(SerialException=OSError, Serial=open_port)
        with self.assertRaises(OSError):
            bridge.run_session(module, args, FakeStop())
        self.assertTrue(display.closed)


if __name__ == "__main__":
    unittest.main()
