#!/usr/bin/env python3
"""Build one camera command and print it, or send it over physical USB serial.

Reading order: defaults -> argument validation -> message -> serial exchange -> main.
Run ``python control.py --help`` for editable options. Without --serial, this
program only prints JSON; it does not select a camera unless that JSON reaches
selector.py. This helper can run on the controller computer, including Windows.
"""
import argparse
import json
import math


# User defaults. The sender baud must match selector.py's serial_baud setting.
DEFAULT_BAUD = 115200
DEFAULT_TIMEOUT_SECONDS = 3.0
# Protocol bound, not a speed setting; replies larger than this are rejected.
MAX_REPLY_BYTES = 2048


def positive_integer(value):
    """Convert a CLI baud value to an integer greater than zero."""
    try:
        result = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a positive integer") from None
    if result <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return result


def positive_seconds(value):
    """Convert CLI timeout seconds; reject zero, negatives, NaN, and infinity."""
    try:
        result = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a finite number greater than zero") from None
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("must be a finite number greater than zero")
    return result


def build_parser():
    """Describe editable options and require exactly one command action."""
    parser = argparse.ArgumentParser(
        description="Print a camera command, or send it over physical USB serial.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--serial", help="sender's serial device, e.g. /dev/ttyUSB0 or COM3")
    parser.add_argument("--baud", type=positive_integer, default=DEFAULT_BAUD,
                        help="serial bits per second; must match the receiver")
    parser.add_argument("--timeout", type=positive_seconds, default=DEFAULT_TIMEOUT_SECONDS,
                        help="seconds allowed for each serial read or write")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--camera", type=int, choices=range(1, 5), help="select camera 1-4")
    group.add_argument("--inputs", nargs=4, type=int, choices=(0, 1),
                       help="camera 1-4 input snapshot; lowest active input wins")
    group.add_argument("--status", action="store_true", help="request current selection/status")
    return parser


def make_message(args):
    """Return one newline-terminated JSON command from parsed CLI arguments."""
    data = {"status": True}
    if args.camera is not None:
        data = {"camera": args.camera}
    elif args.inputs is not None:
        data = {"inputs": args.inputs}
    return json.dumps(data) + "\n"


def send_serial_command(message, device, baud, timeout):
    """Open one serial session, send JSON, read one reply, and close the port.

    Return the decoded reply object, including negative acknowledgements.
    Raise ImportError for missing pyserial, OSError for port errors, or ValueError
    for incomplete/malformed replies. A successful reply confirms acceptance,
    not live video. Opening some controllers resets them; those need a separate
    persistent-session sender with a readiness handshake.
    """
    import serial

    with serial.Serial(device, baud, timeout=timeout, write_timeout=timeout) as port:
        port.write(message.encode("utf-8"))
        reply = port.read_until(b"\n", size=MAX_REPLY_BYTES)
    if not reply.endswith(b"\n"):
        raise ValueError("No complete acknowledgement received")
    try:
        result = json.loads(reply)
    except RecursionError:
        raise ValueError("Acknowledgement JSON is nested too deeply") from None
    if not isinstance(result, dict) or type(result.get("ok")) is not bool:
        raise ValueError("Acknowledgement must be a JSON object with boolean 'ok'")
    return result


def main():
    """Print a command/reply to stdout; report errors to stderr and exit nonzero."""
    parser = build_parser()
    args = parser.parse_args()
    message = make_message(args)
    if not args.serial:
        print(message, end="")
        return
    try:
        result = send_serial_command(message, args.serial, args.baud, args.timeout)
        print(json.dumps(result))
        if not result["ok"]:
            parser.exit(1)
    except ImportError:
        parser.exit(1, "Serial control requires pyserial (python3-serial on Raspberry Pi OS)\n")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Control failed: {exc}\n")


if __name__ == "__main__":
    main()
