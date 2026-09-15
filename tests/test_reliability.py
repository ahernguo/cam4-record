import ast
import io
import logging
import pathlib
import tempfile
import threading
import time
import unittest
from datetime import datetime
from unittest.mock import Mock, patch


def load_functions():
    source = pathlib.Path(__file__).resolve().parents[1] / "main.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    functions = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef)], type_ignores=[])
    ns = dict(str=str, logging=logging, log=Mock(), recording=[],
              reqSs=Mock(), headers={}, datetime=datetime, path=__import__('os').path,
              makedirs=__import__('os').makedirs, Livestreamer=Mock(),
              Thread=threading.Thread, recording_lock=threading.Lock(),
              monotonic=time.monotonic, progress={}, progress_lock=threading.Lock())
    # Postponed annotations allow loading functions without starting the application.
    exec(compile(functions, str(source), 'exec', flags=__import__('__future__').annotations.compiler_flag), ns)
    return ns


class ReliabilityTests(unittest.TestCase):
    def test_request_has_timeouts_and_http_errors_are_caught(self):
        ns = load_functions()
        ns['reqSs'].get.return_value.raise_for_status.side_effect = RuntimeError('HTTP failure')
        self.assertEqual(ns['getStreamInfo']('test'), '')
        self.assertEqual(ns['reqSs'].get.call_args.kwargs['timeout'], (10, 30))
        ns['log'].exception.assert_called()

    def record(self, write_failure=False):
        ns = load_functions()
        fd = Mock()
        fd.read.side_effect = [b'video', b'']
        ns['Livestreamer'].return_value.streams.return_value = {'best': Mock(open=Mock(return_value=fd))}
        ns['recording'] = ['test']
        with tempfile.TemporaryDirectory() as directory:
            ns['save_dir'] = directory
            if write_failure:
                with patch('builtins.open', side_effect=OSError('disk failure')):
                    ns['startRecording']('test', 'https://example.invalid/stream')
            else:
                ns['startRecording']('test', 'https://example.invalid/stream')
                self.assertEqual(next(pathlib.Path(directory).rglob('*.mp4')).read_bytes(), b'video')
                self.assertEqual(fd.read.call_count, 2)
        fd.close.assert_called_once()
        self.assertNotIn('test', ns['recording'])

    def test_eof_exits_and_closes_stream(self):
        self.record()

    def test_file_failure_closes_stream(self):
        self.record(write_failure=True)

    def test_fast_worker_does_not_block_launcher(self):
        ns = load_functions()
        def finish(**kwargs):
            worker = Mock()
            worker.start.side_effect = lambda: ns['recording'].remove(kwargs['args'][0])
            return worker
        ns['Thread'] = Mock(side_effect=finish)
        ns['launchRecording']('TEST', 'url')
        self.assertEqual(ns['recording'], [])

    def test_duplicate_launch_and_start_failure(self):
        ns = load_functions()
        ns['Thread'] = Mock()
        ns['launchRecording']('TEST', 'url')
        ns['launchRecording']('test', 'url')
        ns['Thread'].assert_called_once()
        ns['recording'].clear()
        ns['Thread'].return_value.start.side_effect = RuntimeError('thread limit')
        with self.assertRaises(RuntimeError):
            ns['launchRecording']('test', 'url')
        self.assertEqual(ns['recording'], [])


if __name__ == '__main__':
    unittest.main()

