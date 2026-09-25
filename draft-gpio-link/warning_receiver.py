#!/usr/bin/env python3
"""Draft local GPIO listener: print camera 1..4, 0 for clear, -1 for conflict.

Start once on the Pi, then leave running to react to Arduino GPIO levels.
Use --selector-json to feed the existing camera selector through a pipe.
Reading order: defaults -> decoding/debounce -> reporting -> GPIO loop -> CLI.
"""

import argparse
from contextlib import ExitStack
import json
import math
import signal
import sys
import threading
import time


# INSTALLATION SETTINGS: BCM numbering, ordered camera 1, 2, 3, 4.
# Physical header pins are 11, 13, 15, 16. NPN stages make LOW active.
DEFAULT_PINS = (17, 27, 22, 23)
DEFAULT_SAMPLE_SECONDS = 0.01
DEFAULT_DEBOUNCE_SECONDS = 0.03
CAMERA_COUNT = 4
CONFLICT = -1  # Two or more active wires; never select a camera from this.


def decode_camera(active_inputs):
    """Read four normalized booleans; return 0, camera 1..4, or CONFLICT.

    gpiozero normalizes LOW to active for the default pull-up input. This
    function takes logical activity, not raw voltage, and has no side effects.
    """
    if len(active_inputs) != CAMERA_COUNT:
        raise ValueError("exactly four camera inputs are required")
    active_cameras = [i + 1 for i, active in enumerate(active_inputs) if active]
    if len(active_cameras) > 1:
        return CONFLICT
    return active_cameras[0] if active_cameras else 0


class StableCamera:
    """Accept a camera state only after it stays unchanged for the hold time."""

    def __init__(self, hold_seconds):
        """Initialize with no candidate and no published state (monotonic time)."""
        self.hold_seconds = hold_seconds
        self.candidate = None
        self.since = 0.0
        self.published = None

    def update(self, camera, now):
        """Return a newly stable number, or None; repeated held states stay quiet."""
        if camera != self.candidate:
            self.candidate = camera
            self.since = now
        if camera != self.published and now - self.since >= self.hold_seconds:
            self.published = camera
            return camera
        return None


def report_camera(camera, selector_json=False):
    """Print one changed state, flushing immediately; diagnostics go to stderr.

    Normal mode prints numbers including 0/-1. Selector mode emits only camera
    1..4 JSON commands; clear/conflict leaves the existing camera displayed.
    """
    if camera == CONFLICT:
        print("GPIO conflict: multiple camera lines active; no camera command sent",
              file=sys.stderr, flush=True)
    if selector_json:
        if 1 <= camera <= CAMERA_COUNT:
            print(json.dumps({"camera": camera}), flush=True)
    else:
        print(camera, flush=True)


def monitor(inputs, stop, sample_seconds, debounce_seconds, selector_json):
    """Poll opened inputs until stop; debounce, report changes, and remain idle.

    Called with gpiozero inputs whose value is already normalized for polarity.
    No child process, camera pipeline, file recording, or network is started.
    """
    stable = StableCamera(debounce_seconds)
    while not stop.is_set():
        camera = decode_camera([bool(pin.value) for pin in inputs])
        changed = stable.update(camera, time.monotonic())
        if changed is not None:
            report_camera(changed, selector_json)
        stop.wait(sample_seconds)


def listen(args, stop):
    """Open local GPIO with lgpio, run the listener, and close all resources.

    Imports are delayed so --help, --simulate and software tests need no Pi.
    ExitStack also cleans up if opening a later pin fails.
    """
    from gpiozero import DigitalInputDevice
    from gpiozero.pins.lgpio import LGPIOFactory

    with ExitStack() as resources:
        factory = LGPIOFactory()
        resources.callback(factory.close)
        inputs = []
        for pin in args.pins:
            device = DigitalInputDevice(pin, pull_up=not args.active_high,
                                        pin_factory=factory)
            resources.callback(device.close)
            inputs.append(device)
        print(f"Listening: cameras 1..4 on BCM {args.pins}; Ctrl+C stops",
              file=sys.stderr, flush=True)
        monitor(inputs, stop, args.sample_seconds, args.debounce_seconds,
                args.selector_json)


def parse_args(argv=None):
    """Read and validate editable pin/timing/output options before touching GPIO."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pins", type=int, nargs=4, default=DEFAULT_PINS,
                        metavar="BCM", help="camera 1..4 pins (default: 17 27 22 23)")
    parser.add_argument("--sample-seconds", type=float, default=DEFAULT_SAMPLE_SECONDS)
    parser.add_argument("--debounce-seconds", type=float, default=DEFAULT_DEBOUNCE_SECONDS)
    parser.add_argument("--active-high", action="store_true",
                        help="use HIGH-active inputs/pull-downs; requires different wiring")
    parser.add_argument("--selector-json", action="store_true",
                        help="emit existing selector commands; omit clear/conflict")
    parser.add_argument("--simulate", type=int, nargs="+", choices=range(-1, 5),
                        help="report supplied states immediately without GPIO or debounce")
    args = parser.parse_args(argv)
    if len(set(args.pins)) != CAMERA_COUNT or any(p < 0 or p > 27 for p in args.pins):
        parser.error("use four distinct BCM pins in 0..27; check availability on your board")
    if not math.isfinite(args.sample_seconds) or not 0.001 <= args.sample_seconds <= 1:
        parser.error("sample-seconds must be finite and between 0.001 and 1")
    if not math.isfinite(args.debounce_seconds) or not 0 <= args.debounce_seconds <= 5:
        parser.error("debounce-seconds must be finite and between 0 and 5")
    return args


def main(argv=None):
    """Run simulated reports or the live listener; return a shell exit status."""
    args = parse_args(argv)
    if args.simulate is not None:
        for camera in args.simulate:
            report_camera(camera, args.selector_json)
        return 0
    stop = threading.Event()
    previous_handlers = {}
    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.signal(signum, lambda *_: stop.set())
        listen(args, stop)
    except BrokenPipeError:
        # Closing the camera program should also release this listener's pins.
        return 1
    except Exception as exc:
        print(f"Receiver stopped: {exc}. Check GPIO wiring, permissions, and "
              "python3-gpiozero/python3-lgpio installation.", file=sys.stderr)
        return 1
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
    return 0


if __name__ == "__main__":
    sys.exit(main())
