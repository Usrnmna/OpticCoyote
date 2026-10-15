#!/usr/bin/env python3
"""Check combined reverse/blinker assignments without opening GPIO, USB, or video.

Run from a complete checkout. Component validators remain the source of their
configuration rules; this tool checks only conflicts between those assignments.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import stat
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "rpi-ahd-selector"), str(ROOT / "rpi-oled-bridge")]
import selector
import reverse_control


def unique_object(pairs):
    """Reject duplicate audited keys instead of silently selecting the last value."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def properties(tokens, allowed):
    """Accept unique properties whose entire values match the narrow allowlist."""
    seen = set()
    for token in tokens:
        key, separator, value = token.partition("=")
        if not separator or key in seen or key not in allowed:
            return False
        if re.fullmatch(allowed[key], value) is None:
            return False
        seen.add(key)
    return True


def inspect_source(source):
    """Extract explicit device assignments and recognize a linear V4L2 fragment.

    Unknown elements, properties, branches, and extra resources require manual
    inspection even when an explicit V4L2 device can be extracted for conflicts.
    This is a resource allowlist, not a general GStreamer parser or mode test.
    """
    tokens = shlex.split(source)
    paths = [token[7:] for token in tokens if token.startswith("device=")]
    segments = [[]]
    for token in tokens:
        if token == "!":
            segments.append([])
        else:
            segments[-1].append(token)
    if any(not segment for segment in segments):
        return paths, False
    first = segments[0]
    if first[0] != "v4l2src" or len(paths) != 1:
        return paths, False
    if not properties(first[1:], {"device": r"[^\x00\s!()\"';]+", "do-timestamp": r"true|false"}):
        return paths, False
    tail = segments[1:]
    if tail and len(tail[0]) == 1 and tail[0][0].startswith(("image/jpeg", "video/x-raw")):
        caps = tail.pop(0)[0].split(",")
        if caps[0] not in ("image/jpeg", "video/x-raw") or not properties(caps[1:], {
            "width": r"[1-9][0-9]*", "height": r"[1-9][0-9]*",
            "framerate": r"[1-9][0-9]*/[1-9][0-9]*", "format": r"[A-Z][A-Z0-9]*",
        }):
            return paths, False
    return paths, not tail or tail in ([["decodebin"]], [["jpegdec"]])


def inspect_sink(sink):
    """Recognize resource-bounded display fragments; unknown sinks need review."""
    tokens = shlex.split(sink)
    allowed = {
        "kmssink": {"driver-name": r"vc4", "force-modesetting": r"true|false", "sync": r"true|false"},
        "fakesink": {"sync": r"true|false", "async": r"true|false"},
    }
    return bool(tokens) and tokens[0] in allowed and properties(tokens[1:], allowed[tokens[0]])


def inspect_device(path):
    """Read identity metadata without opening a device; preserve stat failures."""
    try:
        metadata = os.stat(path)
    except OSError as error:
        if isinstance(error, FileNotFoundError):
            status = "DANGLING_LINK" if os.path.lexists(path) else "MISSING"
        elif isinstance(error, PermissionError):
            status = "INACCESSIBLE"
        else:
            status = "STAT_ERROR"
        return None, {"status": status, "detail": str(error)}
    if not stat.S_ISCHR(metadata.st_mode):
        return metadata, {"status": "NOT_CHARACTER_DEVICE", "detail": "A serial or V4L2 character device is required"}
    return metadata, None


def aliases(path, other_path, metadata, other_metadata):
    """Compare path aliases, inode identity, and character-device major/minor IDs."""
    if os.path.normcase(os.path.realpath(path)) == os.path.normcase(os.path.realpath(other_path)):
        return True
    if metadata is None or other_metadata is None:
        return False
    if metadata.st_ino and (metadata.st_dev, metadata.st_ino) == (other_metadata.st_dev, other_metadata.st_ino):
        return True
    return (stat.S_ISCHR(metadata.st_mode) and stat.S_ISCHR(other_metadata.st_mode)
            and metadata.st_rdev == other_metadata.st_rdev)


def check_assignments(camera, reverse, sensor_port, display_port, buzzer=None):
    """Reject overlapping active GPIO and known device paths; report missing paths.

    Filesystem aliases are resolved on this host only. A missing path cannot
    establish physical identity, USB topology, or suitability for its role.
    """
    if not camera["trigger_enabled"]:
        raise ValueError("Combined trigger operation requires trigger_enabled: true")
    pin = reverse["reverse_gpio_pin"]
    if pin is None:
        raise ValueError("Assign reverse_gpio_pin before checking combined operation")
    blinker_pins = [camera["trigger_left_pin"], camera["trigger_right_pin"]]
    if pin in blinker_pins:
        raise ValueError(f"BCM GPIO{pin} is assigned to both reverse and blinker input")
    gpio = {"reverse": pin, "blinker_left": blinker_pins[0], "blinker_right": blinker_pins[1]}
    buzzer_unconfigured = False
    if buzzer is not None:
        buzzer_pin = buzzer["gpio_pin"]
        if buzzer_pin is not None and buzzer_pin in gpio.values():
            raise ValueError(f"BCM GPIO{buzzer_pin} is assigned to both buzzer and a trigger input")
        gpio["buzzer"] = buzzer_pin
        buzzer_unconfigured = buzzer_pin is None or buzzer["hardware_type"] is None
    devices = {"sensor Nano": sensor_port, "display Nano": display_port}
    if camera["serial_port"] is not None:
        devices["selector JSON control"] = camera["serial_port"]
    uninspected_sources = []
    for index, source in enumerate(camera["sources"], 1):
        paths, inspected = inspect_source(source)
        for resource, path in enumerate(paths, 1):
            suffix = "" if len(paths) == 1 else f" resource {resource}"
            devices[f"camera {index} capture{suffix}"] = path
        if not inspected:
            uninspected_sources.append(index)
    sink_requires_review = not inspect_sink(camera["sink"])
    for role, path in devices.items():
        if not isinstance(path, str) or not path.strip() or "\0" in path:
            raise ValueError(f"{role} requires a nonempty device path")
    observations = {role: inspect_device(path) for role, path in devices.items()}
    items = list(devices.items())
    for index, (role, path) in enumerate(items):
        for other_role, other_path in items[index + 1:]:
            if aliases(path, other_path, observations[role][0], observations[other_role][0]):
                raise ValueError(f"Device conflict: {role} and {other_role} resolve to {path}")
    issues = [{"role": role, "path": devices[role], **problem}
              for role, (_, problem) in observations.items() if problem is not None]
    incomplete = bool(issues or uninspected_sources or sink_requires_review)
    return {
        "result": "INCOMPLETE" if incomplete else "NO_CONFLICTS_IN_INSPECTED_ASSIGNMENTS",
        "gpio_bcm": gpio,
        "devices": devices,
        "device_issues": issues,
        "unresolved_paths": [issue["path"] for issue in issues],
        "sources_requiring_manual_inspection": uninspected_sources,
        "sink_requires_manual_inspection": sink_requires_review,
        "buzzer_checked": buzzer is not None,
        "buzzer_unconfigured": buzzer_unconfigured,
        "limits": "Configuration metadata only; no hardware tests. Other processes, device suitability, implicit DRM resources, physical USB topology, bandwidth, power, and timing are not verified. Paths may change after inspection.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selector-config", type=Path, default=ROOT / "rpi-ahd-selector/config.json")
    parser.add_argument("--reverse-config", type=Path, default=ROOT / "rpi-oled-bridge/reverse.json")
    parser.add_argument("--buzzer-config", type=Path, help="Optional buzzer configuration; assigned pins are reserved even when disabled")
    parser.add_argument("--sensor-port", required=True)
    parser.add_argument("--display-port", required=True)
    args = parser.parse_args(argv)
    try:
        camera = selector.validate(json.loads(args.selector_config.read_text(encoding="utf-8"), object_pairs_hook=unique_object))
        reverse = reverse_control.load_config(args.reverse_config)
        buzzer_config = None
        if args.buzzer_config is not None:
            sys.path.insert(0, str(ROOT / "rpi-buzzer"))
            import buzzer
            buzzer_config = buzzer.load_config(args.buzzer_config)
        report = check_assignments(camera, reverse, args.sensor_port, args.display_port, buzzer_config)
    except (OSError, ValueError) as error:
        print(f"Combined trigger configuration error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    return 1 if report["result"] == "INCOMPLETE" else 0


if __name__ == "__main__":
    raise SystemExit(main())
