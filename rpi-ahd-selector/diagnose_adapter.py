"""Local V4L2 capability inventory and bounded MJPEG capture/decode tests.

The parent uses only the standard library. Each hardware test runs in a separate
process with GStreamer Python bindings. Cleanup is bounded and verified before
another device operation is allowed; an unreaped process is reported explicitly.
Video buffers are discarded. Reports contain metadata and measurements only.
"""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time


DIRECTORY = Path(__file__).resolve().parent
LIMITS = {
    "width": (1, 4096), "height": (1, 2160), "fps": (1, 120),
    "warmup_buffers": (0, 3600), "measurement_buffers": (60, 36000),
    "rate_tolerance_percent": (0, 10), "test_timeout_seconds": (1, 3600),
    "probe_timeout_seconds": (1, 60),
    "max_buffer_gap_seconds": (0.01, 10), "cleanup_timeout_seconds": (0.1, 30),
}
INTEGER_SETTINGS = {"width", "height", "fps", "warmup_buffers", "measurement_buffers"}
BOUNDARY = (
    "PASS applies only to this device, camera, connection, mode, duration, and "
    "configured rate tolerance. Buffer delivery is not proof of distinct camera "
    "exposures, image correctness, HDMI refresh, trigger timing, or latency. "
    "Missing evidence never counts as PASS. No video is recorded."
)


def validate(config):
    """Reject ambiguous settings before opening a device or starting a worker."""
    if not isinstance(config, dict) or set(config) != set(LIMITS) | {"device"}:
        raise ValueError("Configuration must contain exactly the keys in diagnostic.json")
    for key, (minimum, maximum) in LIMITS.items():
        value = config[key]
        if (type(value) not in (int, float) or not minimum <= value <= maximum
                or not math.isfinite(value)
                or (key in INTEGER_SETTINGS and type(value) is not int)):
            raise ValueError(f"Invalid {key}: expected {minimum}..{maximum}")
    device = config["device"]
    if device is not None and (not isinstance(device, str)
                               or not device.startswith("/dev/")
                               or any(ord(char) < 32 for char in device)):
        raise ValueError("device must be null or an absolute /dev/ path")
    expected = (config["warmup_buffers"] + config["measurement_buffers"]) / config["fps"]
    if config["test_timeout_seconds"] <= expected:
        raise ValueError("test_timeout_seconds must exceed nominal warmup plus capture duration")
    return config


def run_command(args, timeout, input_text=None, cleanup_timeout=3.0):
    """Run without a shell; bound both communication and kill/reap cleanup.

    Process creation itself is an OS operation without a Python timeout. An
    uninterruptible kernel wait can prevent reaping even after kill; callers
    must stop device operations when cleanup_complete is false.
    """
    started = time.monotonic()
    process = None
    outcome = {"command": args, "returncode": None, "stdout": "", "stderr": "",
               "timed_out": False, "cleanup_complete": True, "pid": None}

    def retain(stdout, stderr):
        for key, value in (("stdout", stdout), ("stderr", stderr)):
            outcome[key] = value.decode("utf-8", "replace") if isinstance(value, bytes) else value or ""

    def cleanup():
        # No context manager is used: Popen.__exit__ may wait without a deadline.
        try:
            process.kill()
        except OSError as error:
            outcome["cleanup_error"] = str(error)
        try:
            stdout, stderr = process.communicate(timeout=cleanup_timeout)
            retain(stdout, stderr)
        except subprocess.TimeoutExpired as error:
            retain(error.stdout, error.stderr)
            outcome["cleanup_complete"] = False
        except OSError as error:
            outcome["cleanup_error"] = str(error)
            outcome["cleanup_complete"] = process.poll() is not None

    try:
        process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                   errors="replace", env={**os.environ, "LC_ALL": "C"})
        outcome["pid"] = process.pid
        try:
            remaining = max(0, timeout - (time.monotonic() - started))
            retain(*process.communicate(input=input_text, timeout=remaining))
        except subprocess.TimeoutExpired:
            outcome["timed_out"] = True
            cleanup()
        except KeyboardInterrupt:
            cleanup()
            if not outcome["cleanup_complete"]:
                print(f"Worker PID {process.pid} could not be reaped; stop device use and inspect it.", file=sys.stderr)
            raise
        outcome["returncode"] = process.returncode
    except OSError as error:
        outcome["stderr"] = str(error)
        if process is not None:
            cleanup()
    finally:
        if process is not None and outcome["cleanup_complete"]:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
    outcome["elapsed_seconds"] = time.monotonic() - started
    return outcome


def detected_modes(output):
    """Parse discrete modes with format/size scoping; preserve other forms in raw logs.

    Rounded seconds are insufficient to distinguish 59.94 from 60 fps. Only the
    explicit fps field is used. Stepwise/continuous ranges are not inferred.
    """
    modes, fourcc, size = [], None, None
    for line in output.splitlines():
        match = re.search(r"\[\d+\]:\s+'([^']+)'", line)
        if match:
            fourcc, size = match[1], None
        if "Size:" in line:
            match = re.search(r"Size: Discrete (\d+)x(\d+)", line)
            size = (int(match[1]), int(match[2])) if match else None
        match = re.search(r"Interval: Discrete .*\(([0-9.]+) fps\)", line)
        if match and fourcc and size:
            try:
                fps = float(match[1])
            except ValueError:
                continue
            if math.isfinite(fps) and fps > 0:
                modes.append({"fourcc": fourcc, "width": size[0], "height": size[1], "fps": fps})
    return modes


class BufferMeasurements:
    """Measure buffer delivery from the warmup boundary, or first arrival without warmup."""
    def __init__(self, warmup):
        self.warmup = warmup
        self.total = 0
        self.count = 0
        self.first = None
        self.last = None
        self.empty = 0
        self.corrupted = 0
        self.previous = None
        self.max_gap = 0
        self.timing_errors = 0

    def observe(self, now, size, corrupted=False):
        """Exclude warmup from rate; include empty/corrupt buffers in failure evidence."""
        self.total += 1
        self.empty += int(size <= 0)
        self.corrupted += int(corrupted)
        if not math.isfinite(now) or (self.previous is not None and now < self.previous):
            self.timing_errors += 1
        previous = self.previous
        self.previous = now
        if self.total <= self.warmup:
            return
        self.count += 1
        if self.first is None:
            # Include the first post-warmup interval; otherwise a stall here is hidden.
            self.first = previous if previous is not None else now
        if previous is not None:
            self.max_gap = max(self.max_gap, now - previous)
        self.last = now

    def result(self):
        duration = self.last - self.first if self.count > 1 else 0
        intervals = max(0, self.count - int(self.warmup == 0))
        return {"total_buffers": self.total, "measured_buffers": self.count,
                "measurement_intervals": intervals, "max_buffer_gap_seconds": self.max_gap,
                "timing_errors": self.timing_errors,
                "measurement_seconds": duration,
                "measured_fps": intervals / duration if duration > 0 else None,
                "empty_buffers": self.empty, "corrupted_buffers": self.corrupted}


def hardware_worker(config, phase):
    """Measure compressed capture or decoded delivery using a finite live pipeline.

    Device paths are assigned as properties, never interpolated into pipeline
    syntax. Handoffs execute in the streaming thread; results are read only after
    the pipeline has stopped. The parent enforces the total wall-clock deadline.
    """
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
    Gst.init(None)
    pipeline = Gst.Pipeline.new("adapter-diagnostic")
    source = Gst.ElementFactory.make("v4l2src", "capture")
    capsfilter = Gst.ElementFactory.make("capsfilter", "requested-mode")
    sink = Gst.ElementFactory.make("fakesink", "measurement")
    elements = [source, capsfilter]
    if phase == "decode":
        elements.append(Gst.ElementFactory.make("jpegdec", "decoder"))
    elements.append(sink)
    if any(element is None for element in elements):
        raise RuntimeError("Required GStreamer element missing: v4l2src/capsfilter/jpegdec/fakesink")
    source.set_property("device", config["device"])
    source.set_property("num-buffers", config["warmup_buffers"] + config["measurement_buffers"])
    source.set_property("do-timestamp", True)
    capsfilter.set_property("caps", Gst.Caps.from_string(
        f'image/jpeg,width={config["width"]},height={config["height"]},framerate={config["fps"]}/1'))
    sink.set_property("sync", False)
    sink.set_property("signal-handoffs", True)
    sink.set_property("enable-last-sample", False)
    for element in elements:
        pipeline.add(element)
    for left, right in zip(elements, elements[1:]):
        if not left.link(right):
            raise RuntimeError("GStreamer element linking failed")
    measurement = BufferMeasurements(config["warmup_buffers"])
    result = {"phase": phase, "eos": False, "errors": [], "warnings": [], "caps": [],
              "output_caps": [], "input_buffers": 0, "invalid_input_buffers": 0,
              "gst_version": Gst.version_string()}

    def record_caps(pad, destination):
        """Retain all observed input/output modes, including renegotiation."""
        caps = pad.get_current_caps()
        if caps is None or caps.is_empty():
            raise RuntimeError("No negotiated caps available")
        structure = caps.get_structure(0)
        ok, numerator, denominator = structure.get_fraction("framerate")
        mode = {"media_type": structure.get_name(),
                "width": structure.get_value("width"), "height": structure.get_value("height"),
                "fps_numerator": numerator if ok else None,
                "fps_denominator": denominator if ok else None}
        if mode not in destination:
            destination.append(mode)

    def invalid_buffer(buffer):
        return buffer.get_size() <= 0 or any(buffer.has_flags(flag) for flag in
            (Gst.BufferFlags.CORRUPTED, Gst.BufferFlags.GAP, Gst.BufferFlags.DECODE_ONLY))

    def input_probe(pad, info):
        try:
            buffer = info.get_buffer()
            result["input_buffers"] += 1
            result["invalid_input_buffers"] += int(invalid_buffer(buffer))
            record_caps(pad, result["caps"])
        except Exception as error:
            if not result["errors"]:
                result["errors"].append(f"Input measurement: {error}")
        return Gst.PadProbeReturn.OK

    def handoff(_sink, buffer, pad):
        try:
            measurement.observe(time.monotonic(), buffer.get_size(),
                                invalid_buffer(buffer))
            record_caps(pad, result["output_caps"])
        except Exception as error:
            if not result["errors"]:
                result["errors"].append(f"Measurement callback: {error}")

    capsfilter.get_static_pad("src").add_probe(Gst.PadProbeType.BUFFER, input_probe)
    sink.connect("handoff", handoff)
    bus = pipeline.get_bus()

    def record_message(message):
        if message.type == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            result["errors"].append(f"{error}: {debug}")
        elif message.type == Gst.MessageType.WARNING:
            warning, debug = message.parse_warning()
            result["warnings"].append(f"{warning}: {debug}")

    try:
        if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            result["errors"].append("Pipeline could not enter PLAYING")
        else:
            while True:
                message = bus.timed_pop_filtered(
                    Gst.SECOND, Gst.MessageType.ERROR | Gst.MessageType.WARNING | Gst.MessageType.EOS)
                if message is None:
                    continue
                if message.type == Gst.MessageType.EOS:
                    result["eos"] = True
                    break
                if message.type == Gst.MessageType.ERROR:
                    record_message(message)
                    break
                record_message(message)
        # EOS must not hide an already queued decoder warning/error.
        while True:
            message = bus.timed_pop_filtered(0, Gst.MessageType.ERROR | Gst.MessageType.WARNING)
            if message is None:
                break
            record_message(message)
    finally:
        transition = pipeline.set_state(Gst.State.NULL)
        _status, current, _pending = pipeline.get_state(0)
        if transition == Gst.StateChangeReturn.FAILURE or current != Gst.State.NULL:
            result["errors"].append("Pipeline teardown did not confirm NULL state")
    result.update(measurement.result())
    return result


def evaluate(config, execution, phase="capture"):
    """Require complete positive measurement evidence; capability listings are excluded."""
    if execution.get("cleanup_complete") is not True:
        return {"status": "FAIL", "reason": f'Cleanup unconfirmed for PID {execution.get("pid")}; further device tests stopped'}
    if execution["timed_out"]:
        return {"status": "FAIL", "reason": "Hardware test timed out; worker terminated"}
    if execution["returncode"] != 0:
        return {"status": "INCONCLUSIVE", "reason": "Worker unavailable or failed; inspect raw diagnostics"}
    try:
        result = json.loads(execution["stdout"])
        if result.get("errors"):
            return {"status": "FAIL", "reason": "Capture/decoder errors", "measurement": result}
        required = {"phase", "eos", "caps", "output_caps", "input_buffers", "invalid_input_buffers",
                    "total_buffers", "measured_buffers", "measured_fps", "measurement_intervals",
                    "max_buffer_gap_seconds", "timing_errors", "measurement_seconds",
                    "empty_buffers", "corrupted_buffers", "warnings", "errors"}
        if not isinstance(result, dict) or not required <= result.keys():
            raise ValueError("Missing worker evidence")
        for key in ("total_buffers", "measured_buffers", "empty_buffers", "corrupted_buffers",
                    "input_buffers", "invalid_input_buffers", "measurement_intervals", "timing_errors"):
            if type(result[key]) is not int or result[key] < 0:
                raise ValueError("Invalid buffer count")
        if any(not isinstance(result[key], list) for key in ("caps", "output_caps", "warnings", "errors")):
            raise ValueError("Invalid worker evidence lists")
        for mode in result["caps"] + result["output_caps"]:
            if not isinstance(mode, dict) or any(type(mode.get(key)) is not int for key in
                    ("width", "height", "fps_numerator", "fps_denominator")):
                raise ValueError("Invalid caps evidence")
        expected_caps = {"media_type": "image/jpeg", "width": config["width"],
                         "height": config["height"], "fps_numerator": config["fps"],
                         "fps_denominator": 1}
        output_caps = {**expected_caps, "media_type": "video/x-raw" if phase == "decode" else "image/jpeg"}
        intervals = config["measurement_buffers"] - int(config["warmup_buffers"] == 0)
        if (result["phase"] != phase or result["eos"] is not True or result["caps"] != [expected_caps]
                or result["output_caps"] != [output_caps]
                or result["input_buffers"] != config["warmup_buffers"] + config["measurement_buffers"]
                or result["invalid_input_buffers"] or result["timing_errors"]
                or result["measurement_intervals"] != intervals
                or result["measured_buffers"] != config["measurement_buffers"]
                or result["total_buffers"] != config["warmup_buffers"] + config["measurement_buffers"]
                or result["empty_buffers"] or result["corrupted_buffers"]):
            return {"status": "FAIL", "reason": "Incomplete buffers, invalid buffers, or mode mismatch", "measurement": result}
        rate = result["measured_fps"]
        duration = result["measurement_seconds"]
        gap = result["max_buffer_gap_seconds"]
        elapsed = execution.get("elapsed_seconds")
        if (type(rate) not in (int, float) or not math.isfinite(rate)
                or type(duration) not in (int, float) or not math.isfinite(duration)
                or duration <= 0
                or type(gap) not in (int, float) or not math.isfinite(gap) or gap <= 0
                or gap > duration or gap < duration / intervals - 1e-9
                or type(elapsed) not in (int, float) or not math.isfinite(elapsed)
                or elapsed < duration
                or not math.isclose(rate, intervals / duration, rel_tol=1e-9)):
            raise ValueError("Missing finite rate measurement")
        if elapsed > config["test_timeout_seconds"]:
            return {"status": "FAIL", "reason": "Worker exceeded the total test time budget", "measurement": result}
        tolerance = config["fps"] * config["rate_tolerance_percent"] / 100
        if abs(rate - config["fps"]) > tolerance:
            return {"status": "FAIL", "reason": "Measured buffer rate outside configured tolerance", "measurement": result}
        if gap > config["max_buffer_gap_seconds"]:
            return {"status": "FAIL", "reason": "Buffer delivery stall exceeds configured maximum gap", "measurement": result}
        if result["warnings"] or execution["stderr"].strip():
            return {"status": "INCONCLUSIVE", "reason": "Warnings or worker stderr require inspection", "measurement": result}
        return {"status": "PASS", "reason": "Exact mode, complete nonempty buffers, EOS, and measured rate within tolerance", "measurement": result}
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError):
        return {"status": "INCONCLUSIVE", "reason": "Missing or malformed worker measurement"}


def host_identity():
    """Record observed host identity separately from the specified Pi configuration."""
    identity = {"specified_host": "Raspberry Pi 5, 4 GB RAM", "platform": platform.platform(),
                "python": sys.version, "device_model": "unavailable", "memory": "unavailable"}
    for key, filename in (("device_model", "/proc/device-tree/model"), ("memory", "/proc/meminfo")):
        try:
            identity[key] = Path(filename).read_text().replace("\x00", "").splitlines()[0]
        except (OSError, IndexError):
            pass
    return identity


def diagnose(config, capabilities_only=False):
    """Inventory one explicit device and run sequential independent hardware tests."""
    report = {"created_utc": datetime.now(timezone.utc).isoformat(), "host": host_identity(),
              "config": config, "boundary": BOUNDARY, "probes": {}, "tests": {}}
    for name, option in (("identity", "--all"), ("formats", "--list-formats-ext")):
        report["probes"][name] = run_command(
            ["v4l2-ctl", f'--device={config["device"]}', option], config["probe_timeout_seconds"],
            cleanup_timeout=config["cleanup_timeout_seconds"])
        if not report["probes"][name]["cleanup_complete"]:
            break
    probe = report["probes"].get("formats", {"stdout": "", "returncode": None})
    modes = detected_modes(probe["stdout"]) if probe["returncode"] == 0 and not probe["timed_out"] else []
    report["detected_discrete_modes"] = modes
    report["target_mode_detected"] = any(
        mode == {"fourcc": "MJPG", "width": config["width"], "height": config["height"], "fps": config["fps"]}
        for mode in modes)
    cleanup_complete = all(probe["cleanup_complete"] for probe in report["probes"].values())
    for phase in ("capture", "decode"):
        if not cleanup_complete:
            report["tests"][phase] = {"status": "SKIPPED", "reason": "Prior process cleanup unconfirmed; device operations stopped"}
            continue
        if capabilities_only:
            report["tests"][phase] = {"status": "SKIPPED", "reason": "Capabilities-only run; no capture attempted"}
            continue
        execution = run_command([sys.executable, str(Path(__file__).resolve()), "--worker", phase],
                                config["test_timeout_seconds"], json.dumps(config),
                                cleanup_timeout=config["cleanup_timeout_seconds"])
        cleanup_complete = execution["cleanup_complete"]
        report["tests"][phase] = {**evaluate(config, execution, phase), "execution": execution}
    return report


def render_report(report):
    """Render a plain-text audit report with independent evidence sections and raw logs."""
    config = report["config"]
    lines = ["AHD ADAPTER DIAGNOSTIC", f'UTC: {report["created_utc"]}',
             f'Device: {config["device"]}',
             f'Target: MJPG {config["width"]}x{config["height"]} at {config["fps"]} fps',
             "", "HOST AND TEST SETTINGS", json.dumps(report["host"], indent=2),
             json.dumps(config, indent=2), "", "DETECTED CAPABILITIES (NOT HARDWARE TEST PASSES)",
             "Target discrete mode: " + ("DETECTED" if report["target_mode_detected"] else "NOT CONFIRMED"),
             "Only discrete format/size/fps records are parsed. Inspect raw output for ranges or errors.",
             json.dumps(report["detected_discrete_modes"], indent=2), "", "HARDWARE TEST RESULTS"]
    for phase, test in report["tests"].items():
        lines.append(f'{phase.upper()}: {test["status"]} - {test["reason"]}')
        if "measurement" in test:
            lines.append(json.dumps(test["measurement"], indent=2))
    lines.extend(["", "EVIDENCE LIMITS", report["boundary"], "", "RAW COMMAND AND WORKER EVIDENCE"])
    lines.append(json.dumps({"probes": report["probes"], "tests": report["tests"]}, indent=2))
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DIRECTORY / "diagnostic.json")
    parser.add_argument("--device", help="Explicit capture node or stable /dev/v4l path")
    parser.add_argument("--report-dir", type=Path, default=DIRECTORY / "diagnostic-reports")
    parser.add_argument("--capabilities-only", action="store_true")
    parser.add_argument("--check-config", action="store_true")
    parser.add_argument("--worker", choices=("capture", "decode"), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        try:
            config = validate(json.load(sys.stdin))
            print(json.dumps(hardware_worker(config, args.worker)))
            return 0
        except Exception as error:
            print(f"Diagnostic worker unavailable: {error}", file=sys.stderr)
            return 2
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        if args.device:
            config["device"] = args.device
        validate(config)
        if args.check_config:
            print(json.dumps(config, indent=2))
            return 0
        if not config["device"]:
            parser.error("Select a capture device using --device or diagnostic.json")
        args.report_dir.mkdir(parents=True, exist_ok=True)
        report = diagnose(config, args.capabilities_only)
        text_report = render_report(report)
        stem = datetime.now(timezone.utc).strftime("adapter-%Y%m%dT%H%M%S-%fZ")
        for suffix, content in ((".json", json.dumps(report, indent=2) + "\n"), (".txt", text_report)):
            with (args.report_dir / (stem + suffix)).open("x", encoding="utf-8") as output:
                output.write(content)
        print(text_report)
        print(f"Reports: {(args.report_dir / stem).resolve()}.txt / .json")
        return 0 if all(test["status"] == "PASS" for test in report["tests"].values()) else 1
    except (OSError, ValueError, TypeError) as error:
        print(f"Diagnostic error: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Diagnostic interrupted; no completed report is claimed.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
