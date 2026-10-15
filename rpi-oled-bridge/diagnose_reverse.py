#!/usr/bin/env python3
"""Offline reverse-control checks and opt-in Pi GPIO/USB bench diagnostics.

Hardware mode runs the production pump in a bounded child process. GPIO is only
read; a protected external source supplies the test sequence. Reports separate
synthetic checks, observed transport behavior, and unmeasured physical behavior.
"""
import argparse
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import signal
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import uuid

from bridge import LineFramer, same_device
import reverse_control as reverse


DIRECTORY = Path(__file__).resolve().parent
DEFAULT_CONFIG = DIRECTORY / "reverse-diagnostic.json"
DEFAULT_REVERSE_CONFIG = DIRECTORY / "reverse.json"
LIMITS = {
    "hardware_timeout_seconds": (5, 600), "cleanup_timeout_seconds": (1, 30),
    "low_release_limit_ms": (1, 10000), "quiet_settle_ms": (100, 10000),
    "quiet_observation_ms": (200, 30000), "minimum_sensor_packets": (1, 1000),
    "minimum_display_acks": (1, 1000),
    "max_observation_gap_ms": (1, 1000),
}
HARDWARE_CHECKS = (
    "initial_low", "short_high_rejected", "qualified_high", "sensor_usb",
    "display_controller_usb", "four_sensor_values", "distance_packets_written",
    "low_release_writes", "observation_continuity", "telemetry_quiet_after_low", "session_completion",
)
PHYSICAL_LIMITS = (
    "Visible OLED feet values, stale markers, and return to idle content",
    "Actual acoustic ranging cessation and sensor distance accuracy",
    "Vehicle input voltage protection and physical pulse-width accuracy",
    "Real sensor disconnection/staleness, USB reconnection, and board-reset recovery",
    "Camera capture, unique exposure rate, decoding, HDMI output, and switching",
)


def result(name, status, detail):
    return {"name": name, "status": status, "detail": detail}


def load_settings(path):
    """Reject mistyped or unsafe diagnostic limits before opening hardware."""
    settings = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(settings, dict) or set(settings) != set(LIMITS):
        raise ValueError("Diagnostic configuration must contain exactly the supplied keys")
    for key, (minimum, maximum) in LIMITS.items():
        if type(settings[key]) is not int or not minimum <= settings[key] <= maximum:
            raise ValueError(f"{key} must be an integer in {minimum}..{maximum}")
    if settings["quiet_settle_ms"] + settings["quiet_observation_ms"] >= settings["hardware_timeout_seconds"] * 1000:
        raise ValueError("The hardware deadline must exceed the complete quiet observation window")
    return settings


def software_checks(config):
    """Exercise production decision/parser code with synthetic time and packets.

    Explicit checks remain active under python -O. These results never imply
    GPIO, USB, firmware, OLED, or acoustic hardware was exercised.
    """
    checks = []

    def check(name, operation):
        try:
            operation()
            checks.append(result(name, "PASS", "Production Python code; synthetic inputs only."))
        except Exception as error:
            checks.append(result(name, "FAIL", f"{type(error).__name__}: {error}"))

    def require(condition, message):
        if not condition:
            raise RuntimeError(message)

    def qualification():
        duration = config["reverse_high_qualify_ms"] / 1000
        gate = reverse.ReverseGate(duration)
        gate.sample(lambda: True, lambda: 0)
        if duration:
            require(not gate.snapshot(duration / 2)[0], "HIGH qualified too early")
        require(gate.snapshot(duration)[0], "HIGH failed at the qualification deadline")
        gate.cancel()
        require(not gate.snapshot(duration)[0], "LOW did not cancel qualification")
        gate.requalify()
        require(not gate.snapshot(duration + 10)[0], "Reconnect retained qualification")

    def cancellation():
        gate = reverse.ReverseGate(0)
        gate.sample(lambda: True, lambda: 0)

        def overtaken_read():
            gate.cancel()
            return True

        require(not gate.sample(overtaken_read, lambda: 1)[0], "Old HIGH overwrote LOW")
        writes = []

        def broken_write(_packet):
            raise OSError("simulated disconnected sensor")

        def display_write(packet):
            writes.append(packet)
            return len(packet)

        try:
            reverse.release(SimpleNamespace(write=broken_write), SimpleNamespace(write=display_write))
        except OSError:
            pass
        require(writes == [b"\nX\n"], "Sensor failure prevented display release")

    def stale_data():
        session = reverse.SensorSession(42, 0)
        row = b"S,42,0,100,305,0,610,0,914,0,1219,0"
        require(session.receive(row, 0.1, 1), "Fresh sensor row rejected")
        require(session.packet(0.1, 1, (1, 2, 3, 4)) == b"D,42,305,610,914,1219\n", "Fresh values were not preserved")
        require(not session.receive(row, 0.2, 1), "Duplicate row refreshed liveness")
        require(not session.receive(row.replace(b"42", b"41"), 0.2, 1), "Wrong session accepted")
        require(session.packet(2, 1, (1, 2, 3, 4)) == b"D,42,-1,-1,-1,-1\n", "Expired values survived")
        require(session.receive_ack(b"A,42,0", 0.1, 1), "Fresh display ACK rejected")
        require(not session.receive_ack(b"A,42,0", 0.2, 1), "Duplicate ACK refreshed liveness")
        session.renewal(0.25, 1)
        aged_row = b"S,42,1,2000,305,1500,610,0,914,0,1219,0"
        require(session.receive(aged_row, 0.3, 1), "Mixed-age snapshot rejected")
        require(session.packet(0.3, 1, (1, 2, 3, 4)) == b"D,42,-1,610,914,1219\n", "One stale sensor was refreshed by other slots")
        require(not session.receive(aged_row.replace(b"2000", b"2100"), 1.25, 1), "Expired sensor request accepted")
        require(not session.receive_ack(b"A,42,1", 1.25, 1), "Expired ACK accepted")

    check("high_qualification_and_requalification", qualification)
    check("low_race_and_independent_release", cancellation)
    check("stale_data_and_ack_rejection", stale_data)
    return checks


class Audit:
    """Collect bounded counts/timestamps from actual GPIO reads and USB calls."""
    def __init__(self, config, settings, clock=time.monotonic):
        self.config, self.settings, self.clock = config, settings, clock
        self.lock = threading.RLock()
        self.initial_low = None
        self.high = False
        self.high_since = None
        self.last_low = None
        self.short_pulses = 0
        self.early_starts = 0
        self.starts = []
        self.low_at = None
        self.released = {}
        self.session = None
        self.display_session = None
        self.sensor_packets = self.display_acks = self.distance_packets = 0
        self.fresh_sensors = set()
        self.four_sensor_snapshot = False
        self.invalid_distance_packets = 0
        self.fresh_distance_packets = 0
        self.quiet_bytes = 0
        self.input_generation = 0
        self.monitoring = False
        self.last_poll = {}
        self.empty_at = {}
        self.poll_counts = {role: 0 for role in ("gpio", "sensor", "display")}
        self.max_poll_gap = 0
        self.observation_gaps = 0
        self.post_low_commands = 0
        self.invalid_packets = 0
        self.errors = []
        self.prompted_low = False
        self.framers = {role: LineFramer() for role in ("sensor", "display")}

    def begin_observation(self, now):
        """Exclude boot settling; begin GPIO and both serial poll-gap accounting."""
        with self.lock:
            self.monitoring = True
            self.last_poll = {role: now for role in self.poll_counts}

    def display_fault(self, error):
        """Retain internal protocol failures even when a later idle reopen succeeds."""
        with self.lock:
            self.errors.append(f"display session fault: {error}")
            self.display_session = None
            self.framers["display"] = LineFramer()

    def poll(self, role, now, empty=False):
        """Record completed polls, including empty reads needed to finish quiet time."""
        with self.lock:
            if not self.monitoring:
                return
            gap = now - self.last_poll[role]
            self.max_poll_gap = max(self.max_poll_gap, gap)
            if gap < 0 or gap > self.settings["max_observation_gap_ms"] / 1000:
                self.observation_gaps += 1
            self.last_poll[role] = now
            self.poll_counts[role] += 1
            if empty:
                self.empty_at[role] = now

    def low_edge(self, now):
        """Invalidate in-flight samples before applying a normalized LOW callback."""
        with self.lock:
            self.input_generation += 1
            self._input(False, now, initial=False)

    def sample(self, read_gpio):
        """Do not allow a delayed HIGH read to overwrite an intervening LOW edge."""
        with self.lock:
            generation = self.input_generation
        high = bool(read_gpio())
        now = self.clock()
        with self.lock:
            self.poll("gpio", now)
            if generation != self.input_generation:
                return False
            self._input(high, now)
            return high

    def input(self, high, now):
        """Record normalized observations; an initial HIGH cannot arm the test."""
        with self.lock:
            self.poll("gpio", now)
            self._input(high, now)

    def _input(self, high, now, initial=True):
        """Apply observations under the audit lock; never count negative pulses."""
        if initial and self.initial_low is None:
            self.initial_low = not high
        if self.high and not high:
            self.last_low = now
            duration = now - self.high_since
            if 0 <= duration < self.config["reverse_high_qualify_ms"] / 1000:
                self.short_pulses += 1
            if self.starts and self.low_at is None:
                self.low_at = now
        if high and not self.high:
            self.high_since = now
        self.high = high

    def write(self, role, packet, started, ended, input_state):
        """Record completed host writes; completion is not device execution proof."""
        fields = packet.strip().split(b",")
        with self.lock:
            if fields[0] in (b"R", b"K", b"D") and self.low_at is not None and started >= self.low_at:
                self.post_low_commands += 1
            if fields[0] == b"R":
                if len(self.starts) >= 2:
                    raise OSError("Only one activation is permitted per diagnostic run")
                was_high, high_since = input_state
                elapsed = None if high_since is None else started - high_since
                if not was_high or elapsed is None or elapsed < self.config["reverse_high_qualify_ms"] / 1000:
                    self.early_starts += 1
                self.starts.append({"role": role, "observed_high_ms": None if elapsed is None else elapsed * 1000})
                # LOW can arrive while the first acquisition write is in flight.
                if self.low_at is None and self.last_low is not None and self.last_low >= started:
                    self.low_at = self.last_low
                if role == "sensor":
                    self.session = reverse.SensorSession(int(fields[1]), started)
                else:
                    self.display_session = reverse.SensorSession(int(fields[1]), started)
            elif fields[0] == b"K":
                session = self.session if role == "sensor" else self.display_session
                if session is None:
                    return
                session.requests = {key: value for key, value in session.requests.items()
                                         if started - value < self.config["ack_timeout_ms"] / 1000}
                session.requests[int(fields[2])] = started
            elif fields[0] == b"D" and role == "display":
                self.distance_packets += 1
                expected = None if self.session is None or self.display_session is None else self.session.packet(
                    started, self.config["distance_stale_ms"] / 1000, (1, 2, 3, 4),
                    token=self.display_session.token).strip().split(b",")
                # Earlier production timestamps may conservatively age a value sooner.
                if (expected is None or len(fields) != 6 or fields[:2] != expected[:2] or
                        any(value != b"-1" and value != fresh for value, fresh in zip(fields[2:], expected[2:]))):
                    self.invalid_distance_packets += 1
                elif b"-1" not in fields[2:]:
                    self.fresh_distance_packets += 1
            elif fields[0] == b"X" and self.low_at is not None:
                self.released.setdefault(role, ended)

    def read(self, role, chunk, now):
        """Validate live replies with the production parser and count fresh slots."""
        with self.lock:
            if role == "sensor" and len(self.released) == 2:
                settled = max(self.released.values()) + self.settings["quiet_settle_ms"] / 1000
                if now >= settled:
                    self.quiet_bytes += len(chunk)
            for line in self.framers[role].feed(chunk):
                if self.session is None or self.low_at is not None:
                    continue
                timeout = self.config["ack_timeout_ms"] / 1000
                if role == "sensor" and self.session.receive(line, now, timeout):
                    self.sensor_packets += 1
                    values = self.session.packet(now, self.config["distance_stale_ms"] / 1000, (1, 2, 3, 4)).strip().split(b",")[2:]
                    self.fresh_sensors = {index + 1 for index, value in enumerate(values) if value != b"-1"}
                    self.four_sensor_snapshot |= len(self.fresh_sensors) == 4
                elif role == "display" and self.display_session is not None and self.display_session.receive_ack(line, now, timeout):
                    self.display_acks += 1
                else:
                    self.invalid_packets += 1
            if self.session is not None and self.low_at is None:
                values = self.session.packet(now, self.config["distance_stale_ms"] / 1000, (1, 2, 3, 4)).strip().split(b",")[2:]
                self.fresh_sensors = {index + 1 for index, value in enumerate(values) if value != b"-1"}
            if (not self.prompted_low and self.sensor_packets >= self.settings["minimum_sensor_packets"]
                    and self.display_acks >= self.settings["minimum_display_acks"] and len(self.fresh_sensors) == 4
                    and self.fresh_distance_packets and not self.invalid_distance_packets):
                print("Live replies observed. Return the protected input to LOW and keep it LOW.", file=sys.stderr, flush=True)
                self.prompted_low = True

    def complete(self):
        with self.lock:
            if len(self.released) != 2 or self.high or not self.monitoring:
                return False
            end = max(self.released.values()) + (self.settings["quiet_settle_ms"] +
                                                 self.settings["quiet_observation_ms"]) / 1000
            return (self.last_poll["gpio"] >= end and
                    all(self.empty_at.get(role, -1) >= end for role in ("sensor", "display")))

    def report(self, completed, error=None):
        """Missing observations remain NOT_TESTED; absence alone is never PASS."""
        checks = {name: result(name, "NOT_TESTED", "Required observation was not completed.") for name in HARDWARE_CHECKS}

        def set_check(name, passed, detail):
            checks[name] = result(name, "PASS" if passed else "FAIL", detail)

        if self.initial_low is not None:
            set_check("initial_low", self.initial_low, "Initial normalized GPIO read was LOW." if self.initial_low else "Input was initially HIGH; test aborted.")
        if self.config["reverse_high_qualify_ms"] == 0:
            checks["short_high_rejected"] = result("short_high_rejected", "SKIP", "Qualification disabled by configuration.")
        elif self.short_pulses:
            set_check("short_high_rejected", not self.early_starts, f"Observed {self.short_pulses} short pulse(s); GPIO timestamps are host observations.")
        if self.starts:
            set_check("qualified_high", {start["role"] for start in self.starts} == {"sensor", "display"}
                      and not self.early_starts, json.dumps(self.starts))
        if self.sensor_packets:
            set_check("sensor_usb", self.sensor_packets >= self.settings["minimum_sensor_packets"], f"{self.sensor_packets} valid tagged sensor snapshots.")
        if self.display_acks:
            set_check("display_controller_usb", self.display_acks >= self.settings["minimum_display_acks"], f"{self.display_acks} fresh controller ACKs; OLED pixels not measured.")
        if self.sensor_packets:
            set_check("four_sensor_values", self.four_sensor_snapshot, f"Four fresh slots in one snapshot: {self.four_sensor_snapshot}; last observed fresh slots: {sorted(self.fresh_sensors)}; distance accuracy not measured.")
        if self.distance_packets:
            set_check("distance_packets_written", self.fresh_distance_packets > 0 and not self.invalid_distance_packets,
                      f"{self.distance_packets} D writes, {self.fresh_distance_packets} with four fresh values; {self.invalid_distance_packets} mismatches at write start; rendering not measured.")
        if self.low_at is not None and len(self.released) == 2:
            delays = {role: (when - self.low_at) * 1000 for role, when in self.released.items()}
            set_check("low_release_writes", all(0 <= delay <= self.settings["low_release_limit_ms"] for delay in delays.values()) and not self.post_low_commands,
                      f"LOW to completed X writes in ms: {delays}; {self.post_low_commands} new R/K/D writes after LOW; device execution not acknowledged.")
        if self.monitoring:
            set_check("observation_continuity", all(self.poll_counts.values()) and not self.observation_gaps,
                      f"Poll counts: {self.poll_counts}; maximum gap {self.max_poll_gap * 1000:.3f} ms; {self.observation_gaps} gaps outside the configured limit.")
        if completed and self.complete():
            set_check("telemetry_quiet_after_low", self.quiet_bytes == 0 and not self.observation_gaps,
                      f"{self.quiet_bytes} raw sensor bytes after settling; final GPIO and empty-port polls completed; observed USB silence only.")
        set_check("session_completion", completed and not error and not self.errors, error or ("Observation window completed." if completed else "Timed out or interrupted before completion."))
        return {"checks": list(checks.values()), "errors": self.errors,
                "rejected_or_unrelated_frames": self.invalid_packets}


class ObservedPort:
    """Transparent serial wrapper; errors remain visible to production cleanup."""
    def __init__(self, port, role, audit):
        self.port, self.role, self.audit = port, role, audit

    def __getattr__(self, name):
        return getattr(self.port, name)

    @property
    def in_waiting(self):
        try:
            waiting = self.port.in_waiting
        except Exception as error:
            self.audit.errors.append(f"{self.role} poll: {error}")
            raise
        self.audit.poll(self.role, self.audit.clock(), empty=waiting == 0)
        return waiting

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def close(self):
        """Audit both normal cleanup and direct closure of rejected OLED candidates."""
        try:
            self.port.close()
        except Exception as error:
            self.audit.errors.append(f"{self.role} close: {error}")
            raise

    def write(self, packet):
        with self.audit.lock:
            started = self.audit.clock()
            input_state = (self.audit.high, self.audit.high_since)
        try:
            written = self.port.write(packet)
            if written != len(packet):
                raise OSError("Incomplete diagnostic USB write")
            self.audit.write(self.role, packet, started, self.audit.clock(), input_state)
            return written
        except Exception as error:
            self.audit.errors.append(f"{self.role} write: {error}")
            raise

    def read(self, count):
        try:
            chunk = self.port.read(count)
        except Exception as error:
            self.audit.errors.append(f"{self.role} read: {error}")
            raise
        self.audit.read(self.role, chunk, self.audit.clock())
        return chunk

    def reset_input_buffer(self):
        try:
            self.port.reset_input_buffer()
        except Exception as error:
            self.audit.errors.append(f"{self.role} input reset: {error}")
            raise
        # The diagnostic parser must discard partial frames together with the
        # production serial parser across acquisition and USB reconnection.
        with self.audit.lock:
            self.audit.framers[self.role] = LineFramer()


class DeadlineStop:
    """Bound the observation loop while allowing normal production X cleanup."""
    def __init__(self, audit, deadline):
        self.audit, self.deadline = audit, deadline
        self.event = threading.Event()
        self.reason = None

    def set(self):
        self.event.set()

    def is_set(self):
        # Preserve the stop cause before cleanup advances time or writes X.
        if self.reason is None:
            if self.event.is_set():
                self.reason = "interrupted"
            elif self.audit.clock() >= self.deadline:
                self.reason = "deadline"
            elif self.audit.complete():
                self.reason = "complete"
        return self.reason is not None

    def wait(self, seconds):
        self.event.wait(max(0, min(seconds, self.deadline - self.audit.clock())))
        return self.is_set()


def hardware_worker(args, config, settings):
    """Observe one full cycle; independent OLED retries cannot hide diagnostic faults."""
    audit = Audit(config, settings)
    error = None
    completed = False
    try:
        import serial
        from gpiozero import DigitalInputDevice
        from gpiozero.pins.lgpio import LGPIOFactory
        if config["reverse_gpio_pin"] is None:
            raise ValueError("Assign reverse_gpio_pin before hardware diagnostics")
        if same_device(args.sensor_port, args.display_port):
            raise ValueError("Sensor and display paths identify the same device")
        stop = DeadlineStop(audit, time.monotonic() + settings["hardware_timeout_seconds"])
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, lambda *_: stop.set())
        with ExitStack() as resources:
            factory = LGPIOFactory()
            resources.callback(factory.close)
            device = resources.enter_context(DigitalInputDevice(config["reverse_gpio_pin"],
                pull_up=not config["reverse_active_high"], bounce_time=None, pin_factory=factory))
            gate = reverse.ReverseGate(config["reverse_high_qualify_ms"] / 1000)
            ready = False
            opened_at = {}

            def low_edge():
                now = time.monotonic()
                gate.cancel()
                audit.low_edge(now)

            device.when_deactivated = low_edge

            def read_gpio():
                nonlocal ready
                start_observation = (ready and "display" in opened_at and
                                     time.monotonic() >= opened_at["display"] + config["boot_ms"] / 1000)
                if start_observation:
                    audit.begin_observation(time.monotonic())
                high = audit.sample(lambda: device.is_active)
                if not audit.initial_low:
                    raise ValueError("Begin hardware testing with the reverse input LOW")
                if ready and not start_observation and high:
                    raise ValueError("Keep the reverse input LOW until both USB links have settled and READY is printed")
                if audit.low_at is not None and high:
                    raise ValueError("Keep the input LOW during the final quiet window")
                if start_observation:
                    print("READY: apply one short HIGH pulse, then sustained HIGH. Wait for the LOW instruction.", file=sys.stderr, flush=True)
                    ready = False
                return high

            read_gpio()
            ready = True

            def open_port(path, **options):
                role = "sensor" if path == args.sensor_port else "display"
                try:
                    port = serial.Serial(path, **options)
                except Exception as error:
                    audit.errors.append(f"{role} open: {error}")
                    raise
                opened_at[role] = time.monotonic()
                return ObservedPort(port, role, audit)

            print("Keep input LOW during USB boot; wait for READY.", file=sys.stderr, flush=True)
            reverse.run_session(SimpleNamespace(Serial=open_port), args, config, stop, gate, read_gpio,
                                on_display_fault=audit.display_fault)
            completed = stop.reason == "complete" and not stop.event.is_set()
    except Exception as caught:
        error = f"{type(caught).__name__}: {caught}"
    return audit.report(completed, error)


@contextmanager
def termination_signals(handler):
    """Restore parent signal handlers after normal execution or bounded cleanup."""
    previous = {}
    try:
        if threading.current_thread() is threading.main_thread():
            for signum in (signal.SIGINT, signal.SIGTERM):
                previous[signum] = signal.signal(signum, handler)
        yield
    finally:
        for signum, original in previous.items():
            signal.signal(signum, original)


def interrupt_supervisor(*_args):
    """Route parent SIGINT/SIGTERM through the same worker cleanup path."""
    raise KeyboardInterrupt


def stop_worker(process, timeout):
    """Attempt graceful exit, force termination, and reap despite repeated signals.

    Real signals are deferred during bounded cleanup. Explicit interruption or
    process-exit races still advance to the next stage; they never accept output.
    """
    with termination_signals(signal.SIG_IGN):
        for action in (process.terminate, process.kill):
            try:
                action()
            except (OSError, KeyboardInterrupt):
                pass
            try:
                process.communicate(timeout=timeout)
                return True
            except (subprocess.TimeoutExpired, OSError, KeyboardInterrupt):
                pass
        # A final wait also reaps a process that exited during an interrupted drain.
        try:
            process.wait(timeout=timeout)
            return True
        except (subprocess.TimeoutExpired, OSError, KeyboardInterrupt):
            return False


def supervised_hardware(args, config, settings):
    """Kill/reap a stuck worker after a grace period and never promote partial output."""
    command = [sys.executable, str(Path(__file__).resolve()), "--worker", "--hardware",
               "--config", str(Path(args.config).resolve()), "--reverse-config", str(Path(args.reverse_config).resolve()),
               "--sensor-port", args.sensor_port, "--display-port", args.display_port]
    timeout = settings["hardware_timeout_seconds"] + settings["cleanup_timeout_seconds"]
    process = None
    interrupted = False

    def request_stop(*_args):
        nonlocal interrupted
        # Defer launch-time signals until a worker handle is available for cleanup.
        interrupted = True
        if process is not None:
            interrupt_supervisor()

    with termination_signals(request_stop):
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=None, text=True)
            if interrupted:
                raise KeyboardInterrupt
            output, _ = process.communicate(timeout=timeout)
        except (subprocess.TimeoutExpired, OSError, KeyboardInterrupt):
            if process is None:
                raise
            if not stop_worker(process, settings["cleanup_timeout_seconds"]):
                return Audit(config, settings).report(False, "Worker could not be reaped; cleanup unverified. Firmware leases remain the fallback.")
            return Audit(config, settings).report(False, "Worker deadline/interruption or pipe error; partial results discarded. Cleanup not confirmed; firmware leases remain the fallback.")
    if process.returncode != 0:
        return Audit(config, settings).report(False, f"Worker exited {process.returncode}; hardware results unavailable.")
    try:
        report = json.loads(output)
        if not isinstance(report, dict):
            raise ValueError("Invalid worker report type")
        if report.pop("effective_config") != {"reverse": config, "diagnostic": settings}:
            raise ValueError("Configuration changed between supervisor and worker")
        checks = report["checks"]
        if (not isinstance(checks, list) or len(checks) != len(HARDWARE_CHECKS)
                or {item["name"] for item in checks} != set(HARDWARE_CHECKS)
                or not isinstance(report["errors"], list)
                or any(not isinstance(error, str) for error in report["errors"])):
            raise ValueError("Invalid worker check set")
        for item in checks:
            if item["status"] not in ("PASS", "FAIL", "NOT_TESTED", "SKIP") or not isinstance(item["detail"], str):
                raise ValueError("Invalid worker result")
            if item["status"] == "SKIP" and (item["name"] != "short_high_rejected" or config["reverse_high_qualify_ms"] != 0):
                raise ValueError("Unexpected skipped check")
            if report["errors"] and item["name"] == "session_completion" and item["status"] != "FAIL":
                raise ValueError("Worker reported success despite transport errors")
        return report
    except (ValueError, KeyError, TypeError):
        return Audit(config, settings).report(False, "Invalid worker report; hardware results unavailable.")


def render_report(report):
    """Produce readable evidence categories without an overall hardware PASS claim."""
    lines = ["# Reverse-trigger diagnostic report", "", f"UTC: {report['utc']}",
             f"Mode: {report['mode']} | Requested checks: {report['outcome']}", "",
             "Software checks use synthetic inputs. Hardware checks describe observed GPIO/USB behavior only.", ""]
    for title, checks in (("Software checks", report["software_checks"]),
                          ("Hardware observations", report["hardware"]["checks"]),
                          ("Physical behavior requiring separate bench verification", report["physical_checks"])):
        lines += [f"## {title}", ""]
        lines += [f"- **{item['status']}** — {item['name']}: {item['detail']}" for item in checks]
        lines.append("")
    lines += ["## Configuration and provenance", "", "```json",
              json.dumps(report["provenance"], indent=2), "```", ""]
    if report["hardware"]["errors"]:
        lines += ["## Transport/cleanup errors", "", *report["hardware"]["errors"], ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.set_defaults(sensor_order=(1, 2, 3, 4))
    parser.add_argument("--reverse-config", type=Path, default=DEFAULT_REVERSE_CONFIG)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--hardware", action="store_true", help="Operate GPIO and both USB ports; stop the bridge first")
    parser.add_argument("--sensor-port")
    parser.add_argument("--display-port")
    parser.add_argument("--report-dir", type=Path, default=DIRECTORY / "diagnostic-reports")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.hardware and (not args.sensor_port or not args.display_port):
        parser.error("--hardware requires both USB role paths")
    if args.worker and not args.hardware:
        parser.error("--worker requires --hardware")
    try:
        config, settings = reverse.load_config(args.reverse_config), load_settings(args.config)
        if args.worker:
            worker_report = hardware_worker(args, config, settings)
            worker_report["effective_config"] = {"reverse": config, "diagnostic": settings}
            print(json.dumps(worker_report))
            return 0
        software = software_checks(config)
        hardware = Audit(config, settings).report(False)
        for item in hardware["checks"]:
            item.update(status="NOT_TESTED", detail="Hardware mode was not run.")
        software_passed = all(item["status"] == "PASS" for item in software)
        if args.hardware and software_passed:
            hardware = supervised_hardware(args, config, settings)
        elif args.hardware:
            for item in hardware["checks"]:
                item["detail"] = "Hardware mode skipped because software checks failed."
        passed = software_passed and (not args.hardware or all(item["status"] in ("PASS", "SKIP") for item in hardware["checks"]))
        hashes = {name: hashlib.sha256((DIRECTORY / name).read_bytes()).hexdigest()
                  for name in ("diagnose_reverse.py", "reverse_control.py", "bridge.py")}
        report = {"utc": datetime.now(timezone.utc).isoformat(), "mode": "hardware" if args.hardware else "software-only",
                  "outcome": "PASS" if passed else "INCOMPLETE_OR_FAILED", "software_checks": software,
                  "hardware": hardware, "physical_checks": [result(name, "NOT_TESTED", "No physical measurement or operator attestation collected.") for name in PHYSICAL_LIMITS],
                  "provenance": {"host": platform.platform(), "python": platform.python_version(), "project_target": "Raspberry Pi 5 4GB (not detected by this report)",
                    "reverse_config": config, "diagnostic_config": settings, "source_sha256": hashes,
                    "sensor_port": args.sensor_port, "display_port": args.display_port}}
        args.report_dir.mkdir(parents=True, exist_ok=True)
        stem = datetime.now(timezone.utc).strftime("reverse-%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
        json_path, text_path = (args.report_dir / (stem + suffix) for suffix in (".json", ".md"))
        json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        text_path.write_text(render_report(report), encoding="utf-8")
        print(render_report(report))
        print(f"Saved: {json_path}\nSaved: {text_path}")
        return 0 if passed else 1
    except (OSError, ValueError) as error:
        print(f"Diagnostic error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
