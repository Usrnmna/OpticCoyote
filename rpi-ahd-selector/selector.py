#!/usr/bin/env python3
"""Four-source camera selector for Raspberry Pi OS Lite (64-bit)."""
import argparse
import json
import logging
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


def camera_number(value):
    if type(value) is not int or value not in range(1, 5):
        raise ValueError("camera must be an integer from 1 to 4")
    return value


def resolve_inputs(values, current):
    if (not isinstance(values, list) or len(values) != 4
            or any(type(v) not in (bool, int) or v not in (0, 1) for v in values)):
        raise ValueError("inputs must contain exactly four booleans or 0/1 values")
    return next((i + 1 for i, v in enumerate(values) if v), current)


def validate(config):
    if not isinstance(config, dict):
        raise ValueError("configuration must be a JSON object")
    camera_number(config.get("initial_camera"))
    sources = config.get("sources")
    if not isinstance(sources, list) or len(sources) != 4:
        raise ValueError("configure exactly four source pipelines")
    if any(not isinstance(s, str) or not s.strip() for s in sources):
        raise ValueError("each source must be a nonempty GStreamer pipeline")
    pins = config.get("gpio_pins", [])
    if not isinstance(pins, list) or (pins and (
            len(pins) != 4 or any(type(p) is not int or not 0 <= p <= 27 for p in pins)
            or len(set(pins)) != 4)):
        raise ValueError("gpio_pins must be empty or four distinct BCM pin numbers 0..27")
    if type(config.get("gpio_active_low", True)) is not bool:
        raise ValueError("gpio_active_low must be boolean")
    port = config.get("serial_port")
    if port is not None and (not isinstance(port, str) or not port.strip()):
        raise ValueError("serial_port must be null or a device path")
    baud = config.get("serial_baud", 115200)
    if type(baud) is not int or baud <= 0:
        raise ValueError("serial_baud must be a positive integer")
    if not isinstance(config.get("sink", "kmssink"), str) or not config.get("sink", "kmssink").strip():
        raise ValueError("sink must be a nonempty pipeline")
    return config


def command(config, camera, demo=False, headless=False):
    source = (f"videotestsrc is-live=true pattern={camera - 1}" if demo
              else config["sources"][camera - 1])
    sink = "fakesink sync=true" if headless else config.get(
        "sink", "kmssink driver-name=vc4 force-modesetting=true sync=false")
    pipeline = (source + " ! queue max-size-buffers=2 max-size-bytes=0 "
                "max-size-time=0 leaky=downstream ! videoconvert ! videoscale "
                "add-borders=true ! videorate ! video/x-raw,width=1280,height=720,"
                "pixel-aspect-ratio=1/1,framerate=60/1 ! watchdog timeout=5000 ! " + sink)
    # Execute a local pipeline without a shell.
    return ["gst-launch-1.0", "-q"] + shlex.split(pipeline)


class State:
    def __init__(self, initial):
        self.lock = threading.Lock()
        self.selected = initial
        self.running = None
        self.error = None

    def select(self, camera):
        with self.lock:
            self.selected = camera_number(camera)

    def inputs(self, values):
        with self.lock:
            self.selected = resolve_inputs(values, self.selected)

    def snapshot(self):
        with self.lock:
            return {"selected_camera": self.selected, "pipeline_camera": self.running,
                    "last_error": self.error}

    def playback(self, camera, error=None):
        with self.lock:
            self.running, self.error = camera, error


def stop_process(process):
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def player(state, config, stop, demo=False, headless=False):
    process = None
    active = None
    retry_at = 0
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
                process, retry_at = None, time.monotonic() + 2
            if process is None and time.monotonic() >= retry_at:
                try:
                    process = subprocess.Popen(command(config, active, demo, headless))
                    state.playback(active)
                    LOG.info("Starting camera %s", active)
                except OSError as exc:
                    state.playback(None, str(exc))
                    LOG.error("Cannot launch video: %s", exc)
                    retry_at = time.monotonic() + 2
            stop.wait(0.05)
    finally:
        stop_process(process)
        state.playback(None)


def apply_message(state, line):
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
        self.buffer = bytearray()
        self.discard = False

    def feed(self, data):
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
                if len(self.buffer) > 1024:
                    self.buffer.clear()
                    self.discard = True
        return result


def responses(state, lines, data):
    for line in lines.feed(data):
        reply = ({"ok": False, "error": "command exceeds 1024 bytes"} if line is None
                 else apply_message(state, line))
        yield (json.dumps(reply) + "\n").encode()


def serial_control(state, config, stop):
    import serial
    while not stop.is_set():
        try:
            with serial.Serial(config["serial_port"], config.get("serial_baud", 115200),
                               timeout=0.1, write_timeout=0.5) as port:
                LOG.info("Serial control ready on %s", config["serial_port"])
                lines = Lines()
                while not stop.is_set():
                    for reply in responses(state, lines, port.read(256)):
                        port.write(reply)
        except (OSError, serial.SerialException) as exc:
            LOG.error("Serial control unavailable: %s; retrying", exc)
            stop.wait(2)


def poll_gpio(state, buttons, stop):
    previous = None
    candidate = None
    since = time.monotonic()
    while not stop.wait(0.01):
        values = [int(button.is_pressed) for button in buttons]
        if values != candidate:
            candidate, since = values, time.monotonic()
        elif values != previous and time.monotonic() - since >= 0.03:
            state.inputs(values)
            previous = values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.json"))
    parser.add_argument("--demo", action="store_true", help="use four test patterns")
    parser.add_argument("--headless", action="store_true", help="discard video for testing")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        config = validate(json.loads(args.config.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if not shutil.which("gst-launch-1.0"):
        parser.error("GStreamer is missing; install the packages listed in README.md")
    if config.get("serial_port"):
        try:
            import serial
        except ImportError:
            parser.error("serial control needs python3-serial")
    try:
        for camera in range(1, 5):
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
            workers.append(threading.Thread(target=poll_gpio, args=(state, buttons, stop)))
        if config.get("serial_port"):
            workers.append(threading.Thread(target=serial_control, args=(state, config, stop)))
        for worker in workers:
            worker.start()
        LOG.info("Ready for local JSON commands on stdin; no network interfaces are opened")
        lines = Lines()
        stdin_open = True
        while not stop.is_set():
            if not stdin_open:
                stop.wait(0.1)
                continue
            ready, _, _ = select.select([sys.stdin], [], [], 0.1)
            if ready:
                data = os.read(sys.stdin.fileno(), 4096)
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
