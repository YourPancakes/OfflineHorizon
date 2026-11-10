"""The parity runner must install only signals available on its host."""
import types
import unittest
from unittest import mock

from tools import parity


class TerminationTests(unittest.TestCase):
    def test_windows_without_sighup_keeps_sigterm_cleanup(self):
        install = mock.Mock()
        signals = types.SimpleNamespace(SIGTERM=15, signal=install)
        with mock.patch.object(parity, "signal", signals):
            parity.exit_on_termination()
        install.assert_called_once()
        number, handler = install.call_args.args
        self.assertEqual(number, 15)
        with self.assertRaises(SystemExit) as result:
            handler(15, None)
        self.assertEqual(result.exception.code, 143)

    def test_posix_keeps_both_cleanup_handlers(self):
        install = mock.Mock()
        signals = types.SimpleNamespace(SIGTERM=15, SIGHUP=1, signal=install)
        with mock.patch.object(parity, "signal", signals):
            parity.exit_on_termination()
        self.assertEqual([call.args[0] for call in install.call_args_list], [15, 1])
        with self.assertRaises(SystemExit) as result:
            install.call_args_list[1].args[1](1, None)
        self.assertEqual(result.exception.code, 129)


if __name__ == "__main__":
    unittest.main()
