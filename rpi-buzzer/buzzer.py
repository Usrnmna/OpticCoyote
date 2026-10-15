#!/usr/bin/env python3
"""Explicitly invoked, cancellable Pi buzzer patterns; no trigger bindings."""
import argparse
import copy
import json
import math
from pathlib import Path
import re
import signal
import threading
import time


DEFAULT_CONFIG = Path(__file__).with_name("buzzer.json")
# Software resource bounds, not verified electrical or acoustic ratings.
MAX_SEQUENCE_MS = 60000
MAX_STEPS = 128
MAX_SEQUENCES = 64
MIN_FREQUENCY_HZ = 20
MAX_FREQUENCY_HZ = 10000
CLI_SIGNAL_POLL_SECONDS = 0.05


def exact_keys(value, keys, label):
    """Reject omissions and misspellings rather than silently applying defaults."""
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(f"{label} must contain exactly: {', '.join(keys)}")


def integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label} must be an integer in {low}..{high}")


def validate(config):
    """Validate a complete configuration without importing GPIO packages."""
    exact_keys(config, ("enabled", "hardware_type", "gpio_pin", "active_high",
                        "max_sequence_ms", "sequences"), "configuration")
    for name in ("enabled", "active_high"):
        if type(config[name]) is not bool:
            raise ValueError(f"{name} must be boolean")
    if config["hardware_type"] not in (None, "active", "passive"):
        raise ValueError("hardware_type must be null, active, or passive")
    if config["gpio_pin"] is not None:
        integer(config["gpio_pin"], 2, 27, "gpio_pin (BCM)")
    if config["enabled"] and (config["gpio_pin"] is None or config["hardware_type"] is None):
        raise ValueError("Enabled playback requires hardware_type and gpio_pin")
    integer(config["max_sequence_ms"], 1, MAX_SEQUENCE_MS, "max_sequence_ms")
    sequences = config["sequences"]
    if not isinstance(sequences, dict) or not 1 <= len(sequences) <= MAX_SEQUENCES:
        raise ValueError(f"sequences must contain 1..{MAX_SEQUENCES} named patterns")
    for name, sequence in sequences.items():
        if not isinstance(name, str) or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name) is None:
            raise ValueError("Sequence names require lowercase letters, digits, or underscores")
        exact_keys(sequence, ("repeat", "steps"), f"sequence {name}")
        integer(sequence["repeat"], 1, 100, f"{name}.repeat")
        steps = sequence["steps"]
        if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
            raise ValueError(f"{name}.steps requires 1..{MAX_STEPS} steps")
        duration = 0
        for step in steps:
            if not isinstance(step, dict) or type(step.get("sound")) is not bool:
                raise ValueError(f"{name} step sound must be boolean")
            keys = ("duration_ms", "sound", "frequency_hz", "duty_cycle") if step["sound"] else ("duration_ms", "sound")
            exact_keys(step, keys, f"{name} step")
            integer(step["duration_ms"], 1, MAX_SEQUENCE_MS, f"{name}.duration_ms")
            duration += step["duration_ms"]
            if step["sound"]:
                integer(step["frequency_hz"], MIN_FREQUENCY_HZ, MAX_FREQUENCY_HZ, "frequency_hz")
                duty = step["duty_cycle"]
                if type(duty) not in (int, float) or not math.isfinite(duty) or not 0 < duty <= 0.5:
                    raise ValueError("duty_cycle must be finite and greater than 0, at most 0.5")
        if duration * sequence["repeat"] > config["max_sequence_ms"]:
            raise ValueError(f"{name} exceeds max_sequence_ms including repeats and pauses")
    return copy.deepcopy(config)


def unique_object(pairs):
    """Reject duplicate JSON keys so an audited setting cannot be overwritten."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def load_config(path=DEFAULT_CONFIG):
    return validate(json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique_object))


class GPIOOutput:
    """Own a gpiozero output and lgpio factory; logical zero requests inactive."""
    def __init__(self, config):
        from gpiozero import DigitalOutputDevice, PWMOutputDevice
        from gpiozero.pins.lgpio import LGPIOFactory
        self.device = None
        self.factory = LGPIOFactory()
        self.passive = config["hardware_type"] == "passive"
        try:
            output_type = PWMOutputDevice if self.passive else DigitalOutputDevice
            # Idle is a static inactive level, without a background PWM train.
            options = {"frequency": None} if self.passive else {}
            self.device = output_type(config["gpio_pin"], active_high=config["active_high"],
                                      initial_value=0, pin_factory=self.factory, **options)
        except BaseException:
            self.factory.close()
            raise

    def apply(self, step):
        """Silence before changing PWM frequency; active hardware uses steady ON."""
        self.off()
        if step["sound"]:
            if self.passive:
                self.device.frequency = step["frequency_hz"]
                self.device.value = step["duty_cycle"]
            else:
                self.device.on()

    def off(self):
        """Stop PWM before driving inactive; retain both errors if either fails."""
        if self.passive:
            stop_error = None
            try:
                try:
                    self.device.frequency = None
                except Exception as error:
                    stop_error = error
                    raise
            finally:
                try:
                    self.device.off()
                except Exception as error:
                    if stop_error is not None:
                        raise RuntimeError(f"PWM stop failed: {stop_error}; inactive-level write failed: {error}") from stop_error
                    raise
        else:
            self.device.off()

    def close(self):
        """Attempt every release operation without masking an earlier OFF failure."""
        failures = []
        for label, operation in (("silence", self.off), ("device close", self.device.close),
                                 ("factory close", self.factory.close)):
            try:
                operation()
            except BaseException as error:
                # Complete the other release attempts before propagating an interrupt.
                failures.append((label, error))
        if failures:
            for _, error in failures:
                if not isinstance(error, Exception):
                    raise error
            detail = "; ".join(f"{label}: {error}" for label, error in failures)
            raise RuntimeError(f"Buzzer GPIO cleanup failed: {detail}") from failures[0][1]


class Buzzer:
    """One output owner with replacement playback and serialized cancellation.

    GPIO operations share the condition lock with play/stop/close. A cancelled
    worker cannot reassert output after stop returns. Calls can wait for an
    in-progress backend operation; this is not a real-time deadline guarantee.
    """
    def __init__(self, config, output_factory=GPIOOutput):
        self._config = validate(config)
        self._condition = threading.Condition()
        self._generation = 0
        self._job = None
        self._fault = None
        self._closed = False
        self._output = None
        self._worker = None
        if self._config["enabled"]:
            try:
                self._output = output_factory(self._config)
                self._output.off()
                self._worker = threading.Thread(target=self._run, name="pi-buzzer", daemon=True)
                self._worker.start()
            except BaseException as error:
                cleanup_error = None
                if self._output is not None:
                    try:
                        self._output.close()
                    except Exception as cleanup:
                        cleanup_error = cleanup
                if isinstance(error, Exception):
                    detail = f"; cleanup also failed: {cleanup_error}" if cleanup_error else ""
                    raise RuntimeError(f"Buzzer initialization failed: {error}{detail}") from error
                raise

    def _silence(self):
        """Latch output failures; attempt silence without masking the first fault."""
        if self._output is not None:
            try:
                self._output.off()
            except Exception as error:
                self._fault = self._fault or f"Silence failed: {error}"

    def _raise_fault(self):
        if self._fault:
            raise RuntimeError(self._fault)

    def play(self, name):
        """Replace playback with a named finite pattern and return its generation."""
        with self._condition:
            if self._closed:
                raise RuntimeError("Buzzer is closed")
            self._raise_fault()
            if not self._config["enabled"]:
                raise RuntimeError("Buzzer is disabled")
            if name not in self._config["sequences"]:
                raise ValueError(f"Unknown sequence: {name}")
            self._generation += 1
            self._job = None
            self._silence()
            self._condition.notify_all()
            self._raise_fault()
            self._job = name
            self._condition.notify_all()
            return self._generation

    def stop(self):
        """Cancel the current generation, request silence, and report failures."""
        with self._condition:
            self._generation += 1
            self._job = None
            if not self._closed:
                self._silence()
            self._condition.notify_all()
            self._raise_fault()

    def status(self):
        with self._condition:
            return {"enabled": self._config["enabled"], "closed": self._closed,
                    "sequence": self._job, "generation": self._generation, "fault": self._fault}

    def wait(self, timeout=None):
        """Wait for idle, cancellation, or fault; return False only on timeout."""
        if timeout is not None and (type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout < 0):
            raise ValueError("timeout must be finite and nonnegative")
        with self._condition:
            done = self._condition.wait_for(lambda: self._job is None or self._fault is not None, timeout)
            self._raise_fault()
            return done

    def _run(self):
        """Advance one pattern using interruptible monotonic waits under the lock."""
        with self._condition:
            while not self._closed:
                self._condition.wait_for(lambda: self._closed or self._job is not None)
                if self._closed:
                    return
                generation = self._generation
                sequence = self._config["sequences"][self._job]
                try:
                    for step in sequence["steps"] * sequence["repeat"]:
                        if self._closed or generation != self._generation:
                            break
                        self._output.apply(step)
                        deadline = time.monotonic() + step["duration_ms"] / 1000
                        self._condition.wait_for(
                            lambda: self._closed or generation != self._generation,
                            max(0, deadline - time.monotonic()))
                    if generation == self._generation:
                        self._silence()
                        self._job = None
                except Exception as error:
                    self._fault = f"Playback failed: {error}"
                    self._job = None
                    self._silence()
                self._condition.notify_all()

    def close(self):
        """Cancel, release resources, join the worker, and retain any failure."""
        with self._condition:
            if not self._closed:
                self._closed = True
                self._generation += 1
                self._job = None
                self._silence()
                self._condition.notify_all()
                # Serialize backend release with all public methods. The worker
                # sees closed before it can access the released output again.
                if self._output is not None:
                    try:
                        self._output.close()
                    except Exception as error:
                        self._fault = self._fault or f"Close failed: {error}"
        if self._worker is not None:
            self._worker.join()
        self._raise_fault()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check-config", action="store_true")
    action.add_argument("--list", action="store_true")
    action.add_argument("--play", metavar="NAME")
    args = parser.parse_args(argv)
    previous_handlers = {}
    try:
        config = load_config(args.config)
        if args.check_config:
            print(json.dumps(config, indent=2))
            print("Configuration valid; no GPIO opened or hardware tested.")
        elif args.list:
            print("\n".join(config["sequences"]))
        else:
            if args.play not in config["sequences"]:
                raise ValueError(f"Unknown sequence: {args.play}")
            cancelled = threading.Event()
            for number in (signal.SIGINT, signal.SIGTERM):
                previous_handlers[number] = signal.signal(number, lambda *_: cancelled.set())
            with Buzzer(config) as player:
                if cancelled.is_set():
                    return 130
                player.play(args.play)
                while not player.wait(CLI_SIGNAL_POLL_SECONDS):
                    if cancelled.is_set():
                        player.stop()
                        return 130
                if cancelled.is_set():
                    return 130
            print("Sequence completed; audible output was not verified.")
        return 0
    except (OSError, ValueError, RuntimeError, ImportError) as error:
        print(f"Buzzer error: {error}")
        return 2
    finally:
        for number, handler in previous_handlers.items():
            signal.signal(number, handler)


if __name__ == "__main__":
    raise SystemExit(main())
