#!/usr/bin/env python3
"""Forward the ultrasonic Nano's cached CSV through a Pi to the OLED Nano.

Both Nanos attach to the Pi as USB serial devices. Only this process should own
these ports. Values remain millimetres on USB; the display formats decimal feet.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import logging
import math
import os
import re
import signal
import threading
import time


# INSTALLATION DEFAULTS: command-line options expose the adjustable settings.
BAUD_RATE = 115200
BOOT_SECONDS = 2.0
STALE_SECONDS = 2.0
RECONNECT_SECONDS = 2.0
START_INTERVAL_SECONDS = 2.0
DISPLAY_INTERVAL_SECONDS = 0.1  # At most 10 short packets/second to the Nano.
READ_TIMEOUT_SECONDS = 0.05
WRITE_TIMEOUT_SECONDS = 0.5
MAX_LINE_BYTES = 192
MAX_DISTANCE_MM = 30000  # Match display_protocol.h; 98.4 feet fits on the OLED.
UNAVAILABLE = (-1, -1, -1, -1)
DEFAULT_SENSOR_ORDER = (1, 2, 3, 4)
LOGGER = logging.getLogger("oled_bridge")


class LineFramer:
    """Keep partial USB reads bounded and discard a damaged line in full."""

    def __init__(self):
        self.pending = bytearray()
        self.discard = False

    def feed(self, data: bytes) -> list[bytes]:
        """Return complete LF/CRLF lines; retain only a bounded unfinished line."""
        lines = []
        for byte in data:
            if byte == 10:
                if not self.discard and self.pending:
                    lines.append(bytes(self.pending).removesuffix(b"\r"))
                self.pending.clear()
                self.discard = False
            elif not self.discard:
                if len(self.pending) >= MAX_LINE_BYTES:
                    self.pending.clear()
                    self.discard = True
                else:
                    self.pending.append(byte)
        return lines


def is_sensor_header(line: bytes) -> bool:
    """Recognize the eight-column schema, including user-edited zone labels."""
    fields = line.split(b",")
    return (len(fields) == 8 and fields[0] == b"time_ms"
            and all(re.fullmatch(rb"[ -~]{1,23}_mm", field)
                    for field in fields[1:5])
            and fields[5:] == [b"nearest_zone", b"nearest_mm", b"state"])


def parse_sensor_row(line: bytes) -> tuple[int, ...] | None:
    """Accept the existing eight-column CSV and retain its four distance slots.

    No float, exponent, whitespace, or missing field is silently coerced. A bad
    row does not refresh stream freshness. Nearest/alarm fields are validated
    structurally but do not determine the displayed unfiltered cached values.
    """
    fields = line.split(b",")
    if len(fields) != 8 or not re.fullmatch(rb"[0-9]{1,10}", fields[0]):
        return None
    if int(fields[0]) > 0xFFFFFFFF:
        return None
    if not all(re.fullmatch(rb"(?:-1|[0-9]{1,5})", field)
               for field in (*fields[1:5], fields[6])):
        return None
    values = tuple(int(field) for field in fields[1:5])
    if any(value > MAX_DISTANCE_MM for value in (*values, int(fields[6]))):
        return None
    if not re.fullmatch(rb"[ -~]{1,23}", fields[5]):
        return None
    if fields[7] not in (b"CLEAR", b"WARNING", b"CRITICAL", b"NO_VALID_SENSORS"):
        return None
    return values


def display_packet(values: tuple[int, ...], order: tuple[int, ...]) -> bytes:
    """Map CSV distance positions (1-based) to display positions left to right."""
    return ("D," + ",".join(str(values[index - 1]) for index in order) + "\n").encode("ascii")


class BridgeState:
    """Latest complete snapshot and its receive time; never queue old displays."""

    def __init__(self):
        self.framer = LineFramer()
        self.values = UNAVAILABLE
        self.received_at = None

    def receive(self, chunk: bytes, now: float) -> None:
        """Replace cached values on valid rows and clear them on a new header."""
        for line in self.framer.feed(chunk):
            if is_sensor_header(line):
                # A new stream/reset must not redisplay the preceding stream.
                self.values = UNAVAILABLE
                self.received_at = None
                continue
            values = parse_sensor_row(line)
            if values is not None:
                self.values = values
                self.received_at = now

    def packet(self, now: float, stale_seconds: float, order: tuple[int, ...]) -> bytes:
        """Select fresh cached values or unavailable markers without altering state."""
        fresh = self.received_at is not None and now - self.received_at < stale_seconds
        return display_packet(self.values if fresh else UNAVAILABLE, order)


def write_packet(port, packet: bytes) -> None:
    """A short or timed-out write ends the session; never append a new suffix."""
    if port.write(packet) != len(packet):
        raise OSError("USB serial write was incomplete")


def same_device(sensor_port: str, display_port: str) -> bool:
    """Reject identical paths and aliases of the same character device."""
    if os.path.realpath(sensor_port) == os.path.realpath(display_port):
        return True
    try:
        return os.path.samefile(sensor_port, display_port)
    except OSError:
        return False  # Missing devices are retried by the normal open loop.


def pump(sensor, display, args, stop, clock=time.monotonic) -> None:
    """Read bounded chunks, keep only the newest row, and refresh at 10 Hz.

    START is idempotent in the sensor sketch. Repeating it also recovers a
    sensor reset that leaves the USB device open. The display's own timeout
    handles Pi termination; invalid heartbeats handle a silent sensor stream.
    """
    state = BridgeState()
    next_start = next_display = 0.0
    while not stop.is_set():
        now = clock()
        if now >= next_start:
            write_packet(sensor, b"\nSTART\n")
            next_start = now + START_INTERVAL_SECONDS
        chunk = sensor.read(min(max(sensor.in_waiting, 1), 4096))
        now = clock()
        state.receive(chunk, now)
        if now >= next_display:
            write_packet(display, state.packet(now, args.stale_seconds, args.sensor_order))
            next_display = now + DISPLAY_INTERVAL_SECONDS


def run_session(serial_module, args, stop) -> None:
    """Own both ports together and close both if either fails or shutdown starts."""
    if same_device(args.sensor_port, args.display_port):
        raise ValueError("Sensor and display ports resolve to the same device")
    sensor = display = None
    with ExitStack() as resources:
        try:
            options = dict(baudrate=BAUD_RATE, timeout=READ_TIMEOUT_SECONDS,
                           write_timeout=WRITE_TIMEOUT_SECONDS, exclusive=True)
            display = resources.enter_context(serial_module.Serial(args.display_port, **options))
            sensor = resources.enter_context(serial_module.Serial(args.sensor_port, **options))
            LOGGER.info("USB ports open; waiting %.1f seconds for Nano bootloaders", args.boot_seconds)
            if stop.wait(args.boot_seconds):
                return
            sensor.reset_input_buffer()
            display.reset_input_buffer()
            # Leading newline completes/discards a partial frame from a prior
            # interrupted write, even on USB bridges that do not reset the MCU.
            write_packet(display, b"\n" + display_packet(UNAVAILABLE, DEFAULT_SENSOR_ORDER))
            LOGGER.info("Forwarding sensor slots %s left to right", args.sensor_order)
            pump(sensor, display, args, stop)
        finally:
            for port, packet in ((sensor, b"\nSTOP\n"),
                                 (display, b"\n" + display_packet(UNAVAILABLE, DEFAULT_SENSOR_ORDER))):
                if port is not None:
                    try:
                        write_packet(port, packet)
                    except (OSError, serial_module.SerialException):
                        pass  # Closing/unplugged ports cannot be cleared reliably.


def finite_positive(text: str) -> float:
    value = float(text)
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("must be a finite positive number")
    return value


def parse_args(argv=None):
    """Validate role paths, timing, and a one-to-one screen mapping before opening USB."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sensor-port", help="Sensor Nano path, preferably /dev/serial/by-path/...")
    parser.add_argument("--display-port", help="Display Nano path, preferably /dev/serial/by-path/...")
    parser.add_argument("--sensor-order", type=int, nargs=4, default=DEFAULT_SENSOR_ORDER,
                        metavar="N", help="CSV distance slots in screen order (default: 1 2 3 4)")
    parser.add_argument("--boot-seconds", type=finite_positive, default=BOOT_SECONDS)
    parser.add_argument("--stale-seconds", type=finite_positive, default=STALE_SECONDS,
                        help="Blank all values after this many seconds without a valid sensor row")
    parser.add_argument("--list-ports", action="store_true", help="List serial ports and exit")
    args = parser.parse_args(argv)
    args.sensor_order = tuple(args.sensor_order)
    if sorted(args.sensor_order) != [1, 2, 3, 4]:
        parser.error("--sensor-order must contain each of 1, 2, 3, 4 exactly once")
    if not args.list_ports:
        if not args.sensor_port or not args.display_port:
            parser.error("provide both --sensor-port and --display-port")
        if same_device(args.sensor_port, args.display_port):
            parser.error("sensor and display ports must be different devices")
    return args


def main(argv=None) -> int:
    """List devices or supervise the bridge until Ctrl+C/SIGTERM requests cleanup."""
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    try:
        import serial
        from serial.tools import list_ports
    except ImportError:
        LOGGER.error("Install pySerial on the Pi: sudo apt install python3-serial")
        return 1
    if args.list_ports:
        for port in list_ports.comports():
            print(f"{port.device}\t{port.description}\t{port.hwid}")
        return 0

    stop = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda _signum, _frame: stop.set())
    while not stop.is_set():
        try:
            run_session(serial, args, stop)
        except ValueError as error:
            LOGGER.error("%s", error)
            return 2
        except (OSError, serial.SerialException) as error:
            LOGGER.warning("USB link unavailable: %s; retrying in %.1f seconds", error, RECONNECT_SECONDS)
            stop.wait(RECONNECT_SECONDS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
