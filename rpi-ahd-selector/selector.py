#!/usr/bin/env python3
"""Four-source camera selector for Raspberry Pi OS Lite (64-bit).

Reading order: configuration/command building -> shared State -> video worker ->
JSON framing/control workers -> main (startup and cleanup). Edit config.json for
camera device paths, output format and timing; use --check-config before running.

Only the player thread owns the GStreamer process. GPIO, serial and stdin submit
selections through State's lock; the last accepted input wins. A stable GPIO
combination submits once, so an unchanged held button does not undo a later
serial/stdin command. No input selected keeps the current camera.
"""
import argparse
import json
import logging
import math
import os
import shlex
import shutil
import signal
import subprocess
import threading
import time
import select
import sys
from pathlib import Path

LOG = logging.getLogger("selector")

# Optional settings keep older configuration files working. The supplied JSON
# lists these values explicitly so normal adjustments need no Python edits.
DEFAULTS = {
    "sink": "kmssink driver-name=vc4 force-modesetting=true sync=false",
    "output_width": 1280,
    "output_height": 720,
    "output_fps": 60,
    "watchdog_timeout_ms": 5000,
    "retry_delay_seconds": 2,
    "gpio_pins": [],
    "gpio_active_low": True,
    "gpio_sample_seconds": 0.01,
    "gpio_debounce_seconds": 0.03,
    "serial_port": None,
    "serial_baud": 115200,
    "serial_read_timeout_seconds": 0.1,
    "serial_write_timeout_seconds": 0.5,
}

# Accepted hand-editing ranges: (minimum, maximum, integers_only). These are
# software bounds, not a guarantee that a capture device/display supports a mode.
NUMERIC_LIMITS = {
    "output_width": (1, 8192, True),
    "output_height": (1, 8192, True),
    "output_fps": (1, 240, True),
    "watchdog_timeout_ms": (1, 600000, True),
    "retry_delay_seconds": (0.05, 300, False),
    "gpio_sample_seconds": (0.001, 1, False),
    "gpio_debounce_seconds": (0, 5, False),
    "serial_baud": (1, 4000000, True),
    "serial_read_timeout_seconds": (0.001, 10, False),
    "serial_write_timeout_seconds": (0.001, 10, False),
}

# Fixed protocol and internal scheduling limits; these are not hardware settings.
CAMERA_COUNT = 4
MAX_COMMAND_BYTES = 1024
SERIAL_READ_BYTES = 256
STDIN_READ_BYTES = 4096
PLAYER_POLL_SECONDS = 0.05
STDIN_POLL_SECONDS = 0.1
PROCESS_STOP_TIMEOUT_SECONDS = 2


def camera_number(value):
    """Return a valid 1-based camera number; reject booleans and other types."""
    if type(value) is not int or value not in range(1, CAMERA_COUNT + 1):
        raise ValueError("camera must be an integer from 1 to 4")
    return value


def resolve_inputs(values, current):
    """Choose the lowest asserted input (1..4), or hold current if all are off."""
    if (not isinstance(values, list) or len(values) != CAMERA_COUNT
            or any(type(v) not in (bool, int) or v not in (0, 1) for v in values)):
        raise ValueError("inputs must contain exactly four booleans or 0/1 values")
    return next((i + 1 for i, v in enumerate(values) if v), current)


def validate(config):
    """Return effective settings after checking types, ranges and pipeline quotes.

    Unknown keys are errors to catch spelling mistakes. This checks local syntax;
    only running on the Pi can establish device/plugin/mode compatibility.
    """
    if not isinstance(config, dict):
        raise ValueError("configuration must be a JSON object")
    unknown = set(config) - (set(DEFAULTS) | {"initial_camera", "sources"})
    if unknown:
        raise ValueError("unknown configuration setting(s): " + ", ".join(sorted(unknown)))
    config = {**DEFAULTS, **config}
    try:
        camera_number(config.get("initial_camera"))
    except ValueError as exc:
        raise ValueError(f"initial_camera: {exc}") from exc
    sources = config.get("sources")
    if not isinstance(sources, list) or len(sources) != CAMERA_COUNT:
        raise ValueError("configure exactly four source pipelines")
    if any(not isinstance(s, str) or not s.strip() for s in sources):
        raise ValueError("each source must be a nonempty GStreamer pipeline")
    pins = config["gpio_pins"]
    if not isinstance(pins, list) or (pins and (
            len(pins) != CAMERA_COUNT or any(type(p) is not int or not 0 <= p <= 27 for p in pins)
            or len(set(pins)) != CAMERA_COUNT)):
        raise ValueError("gpio_pins must be empty or four distinct BCM pin numbers 0..27")
    if type(config["gpio_active_low"]) is not bool:
        raise ValueError("gpio_active_low must be boolean")
    port = config.get("serial_port")
    if port is not None and (not isinstance(port, str) or not port.strip() or "\0" in port):
        raise ValueError("serial_port must be null or a device path")
    for name, (minimum, maximum, integer_only) in NUMERIC_LIMITS.items():
        value = config[name]
        valid_type = type(value) is int if integer_only else type(value) in (int, float)
        if (not valid_type or not minimum <= value <= maximum
                or (type(value) is float and not math.isfinite(value))):
            kind = "an integer" if integer_only else "a finite number"
            raise ValueError(f"{name} must be {kind} from {minimum} to {maximum} (inclusive)")
    if not isinstance(config["sink"], str) or not config["sink"].strip():
        raise ValueError("sink must be a nonempty pipeline")
    fragments = [(f"sources[{i}]", source) for i, source in enumerate(sources)]
    fragments.append(("sink", config["sink"]))
    for name, fragment in fragments:
        try:
            if "\0" in fragment:
                raise ValueError("pipeline cannot contain a NUL character")
            if not shlex.split(fragment):
                raise ValueError("pipeline has no tokens")
        except ValueError as exc:
            raise ValueError(f"{name}: {exc}") from exc
    return config


def command(config, camera, demo=False, headless=False):
    """Build shell-free GStreamer arguments for one camera, without starting it.

    A two-frame leaky queue limits backlog; scaling preserves aspect ratio with
    borders. videorate matches the requested output rate (it may repeat frames).
    The watchdog exits a stalled pipeline so player can retry it.
    """
    camera_number(camera)
    source = (f"videotestsrc is-live=true pattern={camera - 1}" if demo
              else config["sources"][camera - 1])
    sink = "fakesink sync=true" if headless else config.get("sink", DEFAULTS["sink"])
    width = config.get("output_width", DEFAULTS["output_width"])
    height = config.get("output_height", DEFAULTS["output_height"])
    fps = config.get("output_fps", DEFAULTS["output_fps"])
    watchdog_ms = config.get("watchdog_timeout_ms", DEFAULTS["watchdog_timeout_ms"])
    pipeline = (source + " ! queue max-size-buffers=2 max-size-bytes=0 "
                "max-size-time=0 leaky=downstream ! videoconvert ! videoscale "
                f"add-borders=true ! videorate ! video/x-raw,width={width},height={height},"
                f"pixel-aspect-ratio=1/1,framerate={fps}/1 ! watchdog timeout={watchdog_ms} ! " + sink)
    # Execute a local pipeline without a shell.
    return ["gst-launch-1.0", "-q"] + shlex.split(pipeline)


class State:
    """Protect requested camera and worker status shared across all input threads.

    pipeline_camera means a process was started, not proof of a healthy frame.
    Use these methods rather than writing attributes from control workers.
    """
    def __init__(self, initial):
        """Start with a requested camera and no active video process."""
        self.lock = threading.Lock()
        self.selected = camera_number(initial)
        self.running = None
        self.error = None

    def select(self, camera):
        """Atomically accept an explicit camera request."""
        with self.lock:
            self.selected = camera_number(camera)

    def inputs(self, values):
        """Atomically resolve a four-input request against the current selection."""
        with self.lock:
            self.selected = resolve_inputs(values, self.selected)

    def snapshot(self):
        """Return a consistent JSON-ready copy of selection and playback status."""
        with self.lock:
            return {"selected_camera": self.selected, "pipeline_camera": self.running,
                    "last_error": self.error}

    def playback(self, camera, error=None):
        """Record process status; only the player worker calls this in normal use."""
        with self.lock:
            self.running, self.error = camera, error


def stop_process(process):
    """Terminate the active capture, then force-stop after a bounded grace period."""
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=PROCESS_STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def player(state, config, stop, demo=False, headless=False):
    """Own one video process; switch immediately and retry failures until stopped.

    A switch clears the retry delay and stops the old capture before opening the
    new one. The finally block releases the active capture on shutdown.
    """
    process = None
    active = None
    retry_at = 0
    retry_delay = config.get("retry_delay_seconds", DEFAULTS["retry_delay_seconds"])
    try:
        while not stop.is_set():
            requested = state.snapshot()["selected_camera"]
            if requested != active:
                stop_process(process)
                process, active, retry_at = None, requested, 0
                state.playback(None)
            if process is not None and process.poll() is not None:
                error = f"Camera {active} pipeline exited ({process.returncode}); retrying"
                LOG.error(error)
                state.playback(None, error)
                process, retry_at = None, time.monotonic() + retry_delay
            if process is None and time.monotonic() >= retry_at:
                try:
                    process = subprocess.Popen(command(config, active, demo, headless))
                    state.playback(active)
                    LOG.info("Starting camera %s", active)
                except OSError as exc:
                    state.playback(None, str(exc))
                    LOG.error("Cannot launch video: %s", exc)
                    retry_at = time.monotonic() + retry_delay
            stop.wait(PLAYER_POLL_SECONDS)
    finally:
        stop_process(process)
        state.playback(None)


def apply_message(state, line):
    """Apply one JSON command and return acceptance/status or a recoverable error."""
    try:
        body = json.loads(line)
        if not isinstance(body, dict) or len(body) != 1:
            raise ValueError("send exactly one of camera, inputs, or status")
        if "camera" in body:
            state.select(body["camera"])
        elif "inputs" in body:
            state.inputs(body["inputs"])
        elif "status" not in body or body["status"] is not True:
            raise ValueError("send camera, inputs, or status=true")
        return {"ok": True, **state.snapshot()}
    except (ValueError, UnicodeError, RecursionError) as exc:
        return {"ok": False, "error": str(exc)}


class Lines:
    """Bound memory and discard an entire oversized line, including its suffix."""
    def __init__(self):
        """Start a separate line buffer for each stdin or serial connection."""
        self.buffer = bytearray()
        self.discard = False

    def feed(self, data):
        """Return complete nonblank byte lines; None represents an oversized line."""
        result = []
        for byte in data:
            if byte == 10:
                if self.discard:
                    result.append(None)
                elif self.buffer.strip():
                    result.append(bytes(self.buffer))
                self.buffer.clear()
                self.discard = False
            elif not self.discard:
                self.buffer.append(byte)
                if len(self.buffer) > MAX_COMMAND_BYTES:
                    self.buffer.clear()
                    self.discard = True
        return result


def responses(state, lines, data):
    """Frame incoming bytes and yield one newline-terminated JSON reply per command."""
    for line in lines.feed(data):
        reply = ({"ok": False, "error": f"command exceeds {MAX_COMMAND_BYTES} bytes"} if line is None
                 else apply_message(state, line))
        yield (json.dumps(reply) + "\n").encode()


def serial_control(state, config, stop):
    """Serve local USB/UART commands, reopening the port after a disconnect."""
    import serial
    retry_delay = config.get("retry_delay_seconds", DEFAULTS["retry_delay_seconds"])
    baud = config.get("serial_baud", DEFAULTS["serial_baud"])
    read_timeout = config.get("serial_read_timeout_seconds", DEFAULTS["serial_read_timeout_seconds"])
    write_timeout = config.get("serial_write_timeout_seconds", DEFAULTS["serial_write_timeout_seconds"])
    while not stop.is_set():
        try:
            with serial.Serial(config["serial_port"], baud,
                               timeout=read_timeout, write_timeout=write_timeout) as port:
                LOG.info("Serial control ready on %s", config["serial_port"])
                lines = Lines()
                while not stop.is_set():
                    for reply in responses(state, lines, port.read(SERIAL_READ_BYTES)):
                        port.write(reply)
        except (OSError, serial.SerialException) as exc:
            LOG.error("Serial control unavailable: %s; retrying", exc)
            stop.wait(retry_delay)


def poll_gpio(state, buttons, stop, config=None):
    """Submit only changed input combinations stable for the debounce interval.

    Releasing all inputs holds the selection. Debounce applies to the complete
    four-button combination; buttons are already normalized for active polarity.
    """
    config = config or {}
    sample_seconds = config.get("gpio_sample_seconds", DEFAULTS["gpio_sample_seconds"])
    debounce_seconds = config.get("gpio_debounce_seconds", DEFAULTS["gpio_debounce_seconds"])
    previous = None
    candidate = None
    since = time.monotonic()
    while not stop.wait(sample_seconds):
        values = [int(button.is_pressed) for button in buttons]
        if values != candidate:
            candidate, since = values, time.monotonic()
        elif values != previous and time.monotonic() - since >= debounce_seconds:
            state.inputs(values)
            previous = values


def main(argv=None):
    """Validate settings, start local workers, handle stdin and release resources.

    --check-config returns before dependency checks, imports or device access.
    Normal operation keeps playing if stdin closes (as it does under systemd).
    SIGINT/SIGTERM or a broken output pipe asks all workers to shut down.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.json"))
    parser.add_argument("--demo", action="store_true", help="use four test patterns")
    parser.add_argument("--headless", action="store_true", help="discard video for testing")
    parser.add_argument("--check-config", action="store_true",
                        help="validate settings and print effective config/pipelines without hardware access")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        config = validate(json.loads(args.config.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if args.check_config:
        print(json.dumps({"config": config,
                          "pipelines": [command(config, camera, args.demo, args.headless)
                                        for camera in range(1, CAMERA_COUNT + 1)]}, indent=2))
        return
    if not shutil.which("gst-launch-1.0"):
        parser.error("GStreamer is missing; install the packages listed in README.md")
    if config.get("serial_port"):
        try:
            import serial
        except ImportError:
            parser.error("serial control needs python3-serial")
    try:
        for camera in range(1, CAMERA_COUNT + 1):
            command(config, camera, args.demo, args.headless)
    except ValueError as exc:
        parser.error(f"Invalid pipeline: {exc}")
    state, stop, buttons, workers = State(config["initial_camera"]), threading.Event(), [], []
    factory = None
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())
    try:
        for pin in config.get("gpio_pins", []):
            from gpiozero import Button
            from gpiozero.pins.lgpio import LGPIOFactory
            if not buttons:
                factory = LGPIOFactory()
            buttons.append(Button(pin, pull_up=config.get("gpio_active_low", True),
                                  pin_factory=factory))
        workers.append(threading.Thread(target=player,
                       args=(state, config, stop, args.demo, args.headless)))
        if buttons:
            workers.append(threading.Thread(target=poll_gpio, args=(state, buttons, stop, config)))
        if config.get("serial_port"):
            workers.append(threading.Thread(target=serial_control, args=(state, config, stop)))
        for worker in workers:
            worker.start()
        LOG.info("Ready for local JSON commands on stdin; no network interfaces are opened")
        lines = Lines()
        stdin_open = True
        while not stop.is_set():
            if not stdin_open:
                stop.wait(STDIN_POLL_SECONDS)
                continue
            ready, _, _ = select.select([sys.stdin], [], [], STDIN_POLL_SECONDS)
            if ready:
                data = os.read(sys.stdin.fileno(), STDIN_READ_BYTES)
                if not data:
                    stdin_open = False
                for reply in responses(state, lines, data):
                    try:
                        sys.stdout.buffer.write(reply)
                        sys.stdout.buffer.flush()
                    except BrokenPipeError:
                        stop.set()
    finally:
        stop.set()
        for worker in workers:
            if worker.ident is not None:
                worker.join()
        for button in buttons:
            button.close()
        if factory is not None:
            factory.close()


if __name__ == "__main__":
    main()
