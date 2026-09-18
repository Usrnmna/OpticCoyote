#!/usr/bin/env python3
"""Print a local command, or send it over a physical serial connection."""
import argparse
import json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", help="sender's serial device, e.g. /dev/ttyUSB0 or COM3")
    parser.add_argument("--baud", type=int, default=115200)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--camera", type=int, choices=range(1, 5))
    group.add_argument("--inputs", nargs=4, type=int, choices=(0, 1))
    group.add_argument("--status", action="store_true")
    args = parser.parse_args()
    data = {"status": True}
    if args.camera is not None:
        data = {"camera": args.camera}
    elif args.inputs is not None:
        data = {"inputs": args.inputs}
    message = json.dumps(data) + "\n"
    if not args.serial:
        print(message, end="")
        return
    try:
        import serial
        with serial.Serial(args.serial, args.baud, timeout=3, write_timeout=3) as port:
            port.write(message.encode())
            reply = port.read_until(b"\n", size=2048)
            if not reply.endswith(b"\n"):
                parser.exit(1, "No complete acknowledgement received\n")
            result = json.loads(reply)
            print(json.dumps(result))
            if not result.get("ok"):
                parser.exit(1)
    except ImportError:
        parser.exit(1, "Serial control requires pyserial (python3-serial on Raspberry Pi OS)\n")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Control failed: {exc}\n")


if __name__ == "__main__":
    main()
