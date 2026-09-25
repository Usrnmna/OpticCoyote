"""Controller helper checks; uses fake serial ports and needs no hardware.

Run with the rest of the suite: python -m unittest discover -v
CLI tests cover editable options; serial tests cover reply handling and cleanup.
"""
import contextlib
import io
import json
import types
import unittest
from unittest.mock import Mock, patch

import control


class CommandTests(unittest.TestCase):
    """Ensure command-line options generate the receiver's exact JSON shapes."""

    def test_command_messages(self):
        for options, expected in (
            (["--camera", "4"], {"camera": 4}),
            (["--inputs", "0", "1", "0", "0"], {"inputs": [0, 1, 0, 0]}),
            (["--status"], {"status": True}),
        ):
            with self.subTest(options=options):
                args = control.build_parser().parse_args(options)
                message = control.make_message(args)
                self.assertTrue(message.endswith("\n"))
                self.assertEqual(json.loads(message), expected)

    def test_invalid_tuning_is_rejected_before_opening_a_port(self):
        for option, value in (
            ("--baud", "0"), ("--baud", "-1"), ("--baud", "1.5"),
            ("--timeout", "0"), ("--timeout", "-1"),
            ("--timeout", "nan"), ("--timeout", "inf"), ("--timeout", "text"),
        ):
            with self.subTest(option=option, value=value):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as caught:
                        control.build_parser().parse_args(["--status", option, value])
                self.assertEqual(caught.exception.code, 2)

    def test_print_only_mode_does_not_open_serial(self):
        output = io.StringIO()
        with patch("sys.argv", ["control.py", "--camera", "2"]), \
                patch.object(control, "send_serial_command") as send, \
                contextlib.redirect_stdout(output):
            control.main()
        self.assertEqual(json.loads(output.getvalue()), {"camera": 2})
        send.assert_not_called()


class SerialReplyTests(unittest.TestCase):
    """Check complete/invalid replies without depending on pyserial installation."""

    def exchange(self, reply):
        """Run a real exchange against a mock port and verify it is closed."""
        port = Mock()
        port.read_until.return_value = reply
        session = Mock()
        session.__enter__ = Mock(return_value=port)
        session.__exit__ = Mock(return_value=False)
        constructor = Mock(return_value=session)
        module = types.SimpleNamespace(Serial=constructor)
        try:
            with patch.dict("sys.modules", {"serial": module}):
                result = control.send_serial_command('{"status":true}\n', "test-port", 9600, 1.5)
            constructor.assert_called_once_with("test-port", 9600, timeout=1.5, write_timeout=1.5)
            port.write.assert_called_once_with(b'{"status":true}\n')
            port.read_until.assert_called_once_with(b"\n", size=control.MAX_REPLY_BYTES)
            return result
        finally:
            session.__exit__.assert_called_once()

    def test_positive_and_negative_acknowledgements(self):
        for ok in (True, False):
            with self.subTest(ok=ok):
                self.assertEqual(self.exchange((json.dumps({"ok": ok}) + "\n").encode()),
                                 {"ok": ok})

    def test_malformed_reply_is_a_readable_error(self):
        for reply in (b'[]\n', b'null\n', b'2\n', b'{}\n', b'{"ok":1}\n',
                      b'{"ok":"false"}\n', b'{\n', b'\xff\n'):
            with self.subTest(reply=reply):
                with self.assertRaises(ValueError):
                    self.exchange(reply)

    def test_incomplete_reply_is_rejected(self):
        for reply in (b'', b'{"ok":true}', b'x' * control.MAX_REPLY_BYTES):
            with self.subTest(reply=reply):
                with self.assertRaisesRegex(ValueError, "complete acknowledgement"):
                    self.exchange(reply)

    def test_deeply_nested_reply_is_a_readable_error(self):
        with patch.object(control.json, "loads", side_effect=RecursionError):
            with self.assertRaisesRegex(ValueError, "nested too deeply"):
                self.exchange(b'[[[]]]\n')

    def test_negative_acknowledgement_exits_unsuccessfully(self):
        output = io.StringIO()
        with patch("sys.argv", ["control.py", "--serial", "test-port", "--status"]), \
                patch.object(control, "send_serial_command", return_value={"ok": False}), \
                contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as caught:
                control.main()
        self.assertEqual(caught.exception.code, 1)
        self.assertEqual(json.loads(output.getvalue()), {"ok": False})


if __name__ == "__main__":
    unittest.main()
