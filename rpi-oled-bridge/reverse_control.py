"""Reverse-only acquisition and temporary OLED ownership over the existing USB links.

GPIO callbacks update a small locked state; only the main worker writes USB.
Every activation uses a fresh token. LOW invalidates pending work immediately;
already issued USB writes and physical sensor conversions cannot be recalled.
"""
from contextlib import ExitStack
import json
import logging
import os
from pathlib import Path
import re
import secrets
import stat
import threading
import time

from bridge import BAUD_RATE, LineFramer, write_packet


LOGGER = logging.getLogger("reverse_bridge")
UINT32_MAX = 0xFFFFFFFF
LIMITS = {
    "reverse_high_qualify_ms": (0, 5000), "reverse_low_qualify_ms": (0, 0),
    "reverse_sample_ms": (1, 20), "sensor_keepalive_ms": (50, 2000),
    "sensor_lease_ms": (200, 10000), "ack_timeout_ms": (100, 9000),
    "distance_stale_ms": (100, 10000), "display_refresh_ms": (100, 1000),
    "usb_write_timeout_ms": (1, 500), "boot_ms": (0, 10000),
    "reconnect_ms": (100, 30000),
}


def load_config(path):
    """Load auditable settings; allow an unassigned pin only for offline inspection."""
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate reverse configuration key: {key}")
            result[key] = value
        return result

    config = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique_keys)
    keys = set(LIMITS) | {"reverse_gpio_pin", "reverse_active_high", "idle_display_mode"}
    if not isinstance(config, dict) or set(config) != keys:
        raise ValueError("Reverse configuration must contain exactly the keys in reverse.json")
    for key, (minimum, maximum) in LIMITS.items():
        value = config[key]
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(f"{key} must be an integer in {minimum}..{maximum}")
    pin = config["reverse_gpio_pin"]
    if pin is not None and (type(pin) is not int or not 2 <= pin <= 27):
        raise ValueError("reverse_gpio_pin must be null or an available BCM pin 2..27")
    if type(config["reverse_active_high"]) is not bool or config["idle_display_mode"] != "blank":
        raise ValueError("Polarity must be boolean; only the blank idle renderer is currently defined")
    margin = 2 * config["usb_write_timeout_ms"] + config["reverse_sample_ms"]
    if not (2 * config["sensor_keepalive_ms"] + margin < config["ack_timeout_ms"]
            < config["sensor_lease_ms"] - margin):
        raise ValueError("Keepalive, acknowledgement, and lease intervals need room for USB writes and polling")
    return config


class ReverseGate:
    """Qualify observed continuous HIGH and invalidate work on every LOW edge."""
    def __init__(self, qualify_seconds):
        self.qualify_seconds = qualify_seconds
        self.lock = threading.Lock()
        self.high = False
        self.since = None
        self.generation = 0

    def observe(self, high, now):
        with self.lock:
            self._observe_locked(high, now)

    def _observe_locked(self, high, now):
        """Apply a completed observation while the input-state lock is held."""
        high = bool(high)
        if high != self.high:
            self.generation += 1
            self.high = high
            self.since = now if high else None
        elif high and self.since is None:
            self.since = now

    def cancel(self):
        """Latch every LOW callback, including a pulse missed by polling."""
        with self.lock:
            self.high = False
            self.since = None
            self.generation += 1

    def sample(self, read_gpio, clock):
        """Read outside the lock; discard a sample overtaken by cancellation.

        Qualification starts at read completion, never at a timestamp preceding
        a delayed read. Only polling starts HIGH qualification; callbacks can
        cancel it but cannot backdate it or restore an obsolete HIGH state.
        """
        with self.lock:
            generation = self.generation
        high = read_gpio()
        now = clock()
        with self.lock:
            if generation != self.generation:
                return False, self.generation
            self._observe_locked(high, now)
            return self._snapshot_locked(now)

    def requalify(self):
        """Require a new qualification interval after sensor opening/reconnection."""
        with self.lock:
            self.since = None
            self.generation += 1

    def snapshot(self, now):
        with self.lock:
            return self._snapshot_locked(now)

    def _snapshot_locked(self, now):
        active = self.high and self.since is not None and now - self.since >= self.qualify_seconds
        return active, self.generation


class SensorSession:
    """Reject old sessions, duplicate timestamps, and delayed per-sensor readings.

    Each snapshot echoes the latest acquisition/renewal request identifier.
    The local request time precedes snapshot generation, so subtracting the
    reported sample age provides a conservative measurement-time lower bound.
    Pi and Nano clocks need not stay synchronized over a long reverse session.
    Unsigned elapsed deltas reject duplicate/backwards reports across rollover.
    """
    def __init__(self, token, started):
        self.token = token
        self.started = started
        self.last_tick = None
        self.elapsed_ms = 0
        self.received_at = None
        self.values = (-1,) * 4
        self.measured_at = (None,) * 4
        self.request_id = 0
        self.requests = {0: started}
        self.last_ack_request_id = -1

    def renewal(self, now, max_packet_age):
        """Record a bounded request history before queuing a sensor renewal."""
        if self.request_id == UINT32_MAX:
            raise OSError("Sensor renewal sequence exhausted; a new session is required")
        self.requests = {key: sent for key, sent in self.requests.items()
                         if now - sent <= max_packet_age}
        self.request_id += 1
        self.requests[self.request_id] = now
        return f"K,{self.token},{self.request_id}\n".encode("ascii")

    def receive(self, line, now, max_packet_age):
        fields = line.split(b",")
        if len(fields) != 12 or fields[0] != b"S":
            return False
        if any(not re.fullmatch(rb"(?:-1|[0-9]{1,10})", field) for field in fields[1:]):
            return False
        numbers = list(map(int, fields[1:]))
        token, request_id, tick = numbers[:3]
        if token != self.token or not 0 <= tick <= UINT32_MAX:
            return False
        requested_at = self.requests.get(request_id)
        if requested_at is None or not 0 <= now - requested_at < max_packet_age:
            return False
        delta = tick if self.last_tick is None else (tick - self.last_tick) & UINT32_MAX
        if self.last_tick is not None and not 0 < delta < 0x80000000:
            return False
        elapsed = delta if self.last_tick is None else self.elapsed_ms + delta
        values, measured = [], []
        for index in range(3, 11, 2):
            value, age = numbers[index:index + 2]
            if not -1 <= value <= 30000 or not 0 <= age <= UINT32_MAX:
                return False
            if (value == -1 and age != 0) or age > elapsed:
                return False
            values.append(value)
            measured.append(requested_at - age / 1000 if value >= 0 else None)
        self.last_tick, self.elapsed_ms, self.received_at = tick, elapsed, now
        self.values, self.measured_at = tuple(values), tuple(measured)
        return True

    def receive_ack(self, line, now, max_packet_age):
        """Match a display ACK to a recently issued request, not arrival alone."""
        fields = line.split(b",")
        if len(fields) != 3 or fields[0] != b"A":
            return False
        if any(not re.fullmatch(rb"[0-9]{1,10}", field) for field in fields[1:]):
            return False
        token, request_id = map(int, fields[1:])
        requested_at = self.requests.get(request_id)
        if (token != self.token or requested_at is None or
                request_id <= self.last_ack_request_id or
                not 0 <= now - requested_at < max_packet_age):
            return False
        self.last_ack_request_id = request_id
        return True

    def packet(self, now, stale_seconds, order, token=None):
        """Format current ages for the independently owned display token, if supplied."""
        values = [value if measured is not None and 0 <= now - measured < stale_seconds else -1
                  for value, measured in zip(self.values, self.measured_at)]
        return (f"D,{self.token if token is None else token}," + ",".join(str(values[index - 1]) for index in order) + "\n").encode("ascii")


class ReverseCancelled(Exception):
    """A LOW edge or new qualification invalidated a pending serial operation."""


class SensorLinkFault(OSError):
    """Sensor health expired during optional display work; end the sensor session."""


def release(sensor, display):
    """Attempt both independent releases even if the first USB port has failed."""
    first_error = None
    for port in (sensor, display):
        if port is not None:
            try:
                write_packet(port, b"\nX\n")
            except OSError as error:
                first_error = first_error or error
    if first_error:
        raise first_error


class DisplayLink:
    """Retry the optional OLED link without cancelling the sensor acquisition.

    Boot settling uses a deadline rather than a sleep. Display requests and ACK
    history are independent of sensor renewal IDs. Each reacquisition uses a
    fresh token so buffered replies cannot restore a failed display session.
    Serial operations remain bounded by the configured write timeout; device
    opening and OS scheduling do not provide hard real-time guarantees.
    """
    def __init__(self, config, port=None, open_port=None, on_fault=None):
        self.config, self.port, self.open_port = config, port, open_port
        self.on_fault = on_fault
        self.clock = time.monotonic
        self.ready_at = 0
        self.initialized = port is not None
        self.next_retry = 0
        self.session = None
        self.last_token = None
        self.last_sensor_token = None
        self.ack = None
        self.lines = LineFramer()
        self.next_keepalive = self.next_display = 0

    def _close_port(self):
        port, self.port = self.port, None
        if port is not None:
            try:
                port.__exit__(None, None, None)
            except OSError as error:
                LOGGER.warning("OLED close unavailable: %s", error)

    def fault(self, error):
        """Forget display ownership, attempt release, and schedule only its retry."""
        LOGGER.warning("OLED link fault: %s; sensor acquisition continues", error)
        self.session, self.ack = None, None
        if self.port is not None:
            try:
                release(None, self.port)
            except OSError:
                LOGGER.warning("OLED release unavailable; display lease provides fallback")
        self._close_port()
        self.initialized = False
        self.next_retry = self.clock() + self.config["reconnect_ms"] / 1000
        if self.on_fault is not None:
            # Diagnostic observers cannot prevent cleanup or interrupt ranging.
            # Protocol failures still reach the observer even without an I/O error.
            try:
                self.on_fault(error)
            except Exception:
                LOGGER.exception("OLED fault observer failed; sensor acquisition continues")

    def release(self):
        """Clear local session state before an unconditional best-effort OLED X."""
        self.session, self.ack = None, None
        if self.port is not None:
            try:
                release(None, self.port)
            except OSError as error:
                self.fault(error)

    def close(self):
        self.release()
        self._close_port()

    def service(self, sensor_session, order, guarded_write):
        """Retry OLED faults; propagate cancellation and expired sensor health."""
        try:
            if self.port is None:
                if self.open_port is None or self.clock() < self.next_retry:
                    return
                self.port = self.open_port()
                self.port.__enter__()
                self.ready_at = self.clock() + self.config["boot_ms"] / 1000
                self.initialized = False
            if self.clock() < self.ready_at:
                return
            if not self.initialized:
                release(None, self.port)
                self.port.reset_input_buffer()
                self.lines = LineFramer()
                self.initialized = True
            if sensor_session is not None and self.session is None:
                token = sensor_session.token
                if token == self.last_token or token == self.last_sensor_token:
                    token = secrets.randbelow(UINT32_MAX) + 1
                    if token in (self.last_token, self.last_sensor_token):
                        raise OSError("OLED token generator repeated the retired session")
                self.last_sensor_token = sensor_session.token
                self.last_token = token
                self.port.reset_input_buffer()
                self.lines = LineFramer()
                self.session = SensorSession(token, self.clock())
                self.ack = None
                guarded_write(self.port, f"\nR,{token},{self.config['sensor_lease_ms']}\n".encode("ascii"))
                self.next_keepalive = self.clock() + self.config["sensor_keepalive_ms"] / 1000
                self.next_display = 0
            timeout = self.config["ack_timeout_ms"] / 1000

            def check_ack_health():
                if self.session is not None and self.clock() - (self.ack if self.ack is not None else self.session.started) >= timeout:
                    raise OSError("Display acknowledgement expired")

            check_ack_health()
            waiting = min(self.port.in_waiting, 4096)
            if waiting:
                for line in self.lines.feed(self.port.read(waiting)):
                    check_ack_health()
                    if self.session is not None and self.session.receive_ack(line, self.clock(), timeout):
                        self.ack = self.clock()
            check_ack_health()
            if self.session is None or sensor_session is None:
                return
            if self.clock() >= self.next_keepalive:
                guarded_write(self.port, self.session.renewal(self.clock(), timeout))
                self.next_keepalive = self.clock() + self.config["sensor_keepalive_ms"] / 1000
            if self.clock() >= self.next_display and sensor_session.received_at is not None and self.ack is not None:
                def current_packet():
                    # GPIO sampling may be delayed. Recheck both ACK health and
                    # sample ages after that check, immediately before the write.
                    check_ack_health()
                    return sensor_session.packet(self.clock(), self.config["distance_stale_ms"] / 1000,
                                                 order, token=self.session.token)
                guarded_write(self.port, current_packet)
                self.next_display = self.clock() + self.config["display_refresh_ms"] / 1000
        except SensorLinkFault:
            # A slow OLED operation can outlive the sensor deadline. Preserve
            # the sensor fault rather than treating it as a display-only retry.
            self.close()
            raise
        except OSError as error:
            self.fault(error)


def pump(sensor, display, args, config, stop, gate, read_gpio, clock=time.monotonic,
         new_token=lambda: secrets.randbelow(UINT32_MAX) + 1):
    """Service GPIO, acknowledgements, leases, and newest distances without read waits.

    Each write is bounded by the port timeout and rechecked before/after against
    the input generation. Blocking writes never hold the GPIO callback lock.
    """
    session = None
    generation = None
    last_token = None
    sensor_lines = LineFramer()
    next_keepalive = 0
    display = display if isinstance(display, DisplayLink) else DisplayLink(config, port=display)
    display.clock = clock
    gate.requalify()

    def guarded_write(port, packet):
        """Check cancellation before formatting time-sensitive distance packets."""
        if stop.is_set():
            raise ReverseCancelled()
        observed = gate.sample(read_gpio, clock)
        if stop.is_set() or observed != (True, generation):
            raise ReverseCancelled()
        check_link_health()
        if callable(packet):
            packet = packet()
        # Formatting can be overtaken by a LOW callback. Check the latched
        # generation again without another potentially blocking GPIO read.
        if stop.is_set() or gate.snapshot(clock()) != (True, generation):
            raise ReverseCancelled()
        write_packet(port, packet)
        if stop.is_set() or gate.sample(read_gpio, clock) != (True, generation):
            raise ReverseCancelled()

    def check_link_health():
        """Expired sensor telemetry cannot be revived by draining delayed replies."""
        now = clock()
        timeout = config["ack_timeout_ms"] / 1000
        if now - (session.received_at if session.received_at is not None else session.started) >= timeout:
            raise SensorLinkFault("Sensor telemetry acknowledgement expired")

    def cancel_session():
        nonlocal session
        session = None
        try:
            release(sensor, None)
        finally:
            display.release()

    while not stop.is_set():
        active, observed_generation = gate.sample(read_gpio, clock)
        if stop.is_set():
            break
        if session is not None and (not active or observed_generation != generation):
            cancel_session()
        if active and session is None:
            generation = observed_generation
            token = new_token()
            if type(token) is not int or not 1 <= token <= UINT32_MAX or token == last_token:
                raise ValueError("Session token source returned an invalid or reused token")
            last_token = token
            sensor.reset_input_buffer()
            sensor_lines = LineFramer()
            session = SensorSession(token, clock())
            command = f"\nR,{token},{config['sensor_lease_ms']}\n".encode("ascii")
            try:
                guarded_write(sensor, command)
            except ReverseCancelled:
                cancel_session()
                continue
            next_keepalive = clock() + config["sensor_keepalive_ms"] / 1000
            LOGGER.info("Reverse session %s enabled", token)

        # Drain bounded input even while idle; idle packets cannot acquire the OLED.
        waiting = min(sensor.in_waiting, 4096)
        if waiting:
            for line in sensor_lines.feed(sensor.read(waiting)):
                if session is None:
                    continue
                check_link_health()
                now = clock()
                session.receive(line, now, config["ack_timeout_ms"] / 1000)

        if session is not None:
            check_link_health()
            now = clock()
            timeout = config["ack_timeout_ms"] / 1000
            try:
                if now >= next_keepalive:
                    command = session.renewal(clock(), timeout)
                    guarded_write(sensor, command)
                    next_keepalive = clock() + config["sensor_keepalive_ms"] / 1000
            except ReverseCancelled:
                cancel_session()
        # Reads may complete after shutdown. Do not begin optional USB work.
        if stop.is_set():
            break
        try:
            display.service(session, args.sensor_order, guarded_write)
        except ReverseCancelled:
            cancel_session()
        stop.wait(config["reverse_sample_ms"] / 1000)


def character_device_identity(metadata):
    """Identify a Linux character device independently of pathname and node inode."""
    if not stat.S_ISCHR(metadata.st_mode):
        raise OSError("Serial endpoint is not a character device")
    return metadata.st_rdev


def opened_device_identity(port):
    """Use the owned descriptor; a USB alias may have changed since it was opened."""
    try:
        return character_device_identity(os.fstat(port.fileno()))
    except (AttributeError, TypeError, ValueError, NotImplementedError) as error:
        raise OSError("Cannot identify the opened serial endpoint") from error


def path_device_identity(path):
    """Resolve a candidate path before opening it; missing paths fail closed."""
    return character_device_identity(os.stat(path))


def run_session(serial_module, args, config, stop, gate, read_gpio, on_display_fault=None):
    """Own sensor acquisition and an independently reconnecting optional OLED link."""
    sensor = None
    sensor_identity = None

    def open_display():
        # Compare against the owned sensor descriptor, not its mutable pathname.
        if stop.is_set():
            raise ReverseCancelled()
        expected_identity = path_device_identity(args.display_port)
        if stop.is_set():
            raise ReverseCancelled()
        if expected_identity == sensor_identity:
            raise OSError("OLED path now aliases the sensor port; display retry deferred")
        candidate = serial_module.Serial(args.display_port, baudrate=BAUD_RATE, timeout=0,
                                        write_timeout=config["usb_write_timeout_ms"] / 1000, exclusive=True)
        try:
            if stop.is_set():
                raise ReverseCancelled()
            actual_identity = opened_device_identity(candidate)
            if stop.is_set():
                raise ReverseCancelled()
            if actual_identity == sensor_identity or actual_identity != expected_identity:
                raise OSError("OLED endpoint changed during open; display retry deferred")
        except BaseException:
            # Unverified or cancelled candidates must not receive protocol commands.
            try:
                candidate.close()
            except OSError as error:
                LOGGER.warning("Rejected OLED endpoint close unavailable: %s", error)
            raise
        return candidate

    display = DisplayLink(config, open_port=open_display, on_fault=on_display_fault)
    with ExitStack() as resources:
        try:
            candidate_sensor = resources.enter_context(serial_module.Serial(
                args.sensor_port, baudrate=BAUD_RATE, timeout=0,
                write_timeout=config["usb_write_timeout_ms"] / 1000, exclusive=True))
            sensor_identity = opened_device_identity(candidate_sensor)
            sensor = candidate_sensor
            if stop.wait(config["boot_ms"] / 1000):
                return
            release(sensor, None)
            pump(sensor, display, args, config, stop, gate, read_gpio)
        finally:
            try:
                release(sensor, None)
            except OSError:
                LOGGER.warning("Sensor release unavailable; Nano lease provides bounded fallback")
            finally:
                display.close()


def run(serial_module, args, stop):
    """Open the protected GPIO input once; requalify after sensor-link reconnect."""
    config = load_config(args.reverse_config)
    if config["reverse_gpio_pin"] is None:
        raise ValueError("Assign reverse_gpio_pin in the reverse configuration before running")
    from gpiozero import DigitalInputDevice
    from gpiozero.pins.lgpio import LGPIOFactory
    gate = ReverseGate(config["reverse_high_qualify_ms"] / 1000)
    factory = LGPIOFactory()
    try:
        with DigitalInputDevice(config["reverse_gpio_pin"],
                                pull_up=not config["reverse_active_high"],
                                bounce_time=None, pin_factory=factory) as device:
            device.when_deactivated = gate.cancel

            def read_gpio():
                try:
                    return bool(device.is_active)
                except Exception as error:
                    gate.cancel()
                    raise ValueError(f"Reverse GPIO read failed: {error}") from error

            while not stop.is_set():
                try:
                    run_session(serial_module, args, config, stop, gate, read_gpio)
                except (OSError, serial_module.SerialException) as error:
                    LOGGER.warning("Reverse sensor-link fault: %s; releasing and reconnecting", error)
                    gate.requalify()
                    stop.wait(config["reconnect_ms"] / 1000)
    finally:
        factory.close()
    return 0
