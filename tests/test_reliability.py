import ast
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
    ns = dict(chat_capture=Mock(start=Mock(return_value=None)), chat_options={}, json=__import__('json'), os=__import__('os'), Path=pathlib.Path, str=str, logging=logging, log=Mock(), recording=[],
              reqSs=Mock(), headers={}, datetime=datetime, path=__import__('os').path,
              makedirs=__import__('os').makedirs, Livestreamer=Mock(),
              Thread=threading.Thread, recording_lock=threading.Lock(),
              stop_event=threading.Event(),
              monotonic=time.monotonic, time_ns=time.time_ns, progress={}, progress_lock=threading.Lock())
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

    def record(self, write_failure=False, chat_failure=False):
        ns = load_functions()
        fd = Mock()
        fd.read.side_effect = [b'video', b'']
        ns['Livestreamer'].return_value.streams.return_value = {'best': Mock(open=Mock(return_value=fd))}
        ns['recording'] = ['test']
        if chat_failure:
            ns['chat_capture'].start.return_value = Mock(close=Mock(side_effect=RuntimeError('chat error')))
        with tempfile.TemporaryDirectory() as directory:
            ns['save_dir'] = directory
            if write_failure:
                with patch('builtins.open', side_effect=OSError('disk failure')):
                    ns['startRecording']('test', 'https://example.invalid/stream')
            else:
                ns['startRecording']('test', 'https://example.invalid/stream')
                self.assertEqual(next(pathlib.Path(directory).rglob('*.source')).read_bytes(), b'video')
                self.assertEqual(fd.read.call_count, 2)
        fd.close.assert_called_once()
        self.assertNotIn('test', ns['recording'])

    def test_eof_exits_and_closes_stream(self):
        self.record()

    def test_file_failure_closes_stream(self):
        self.record(write_failure=True)

    def test_chat_failure_does_not_prevent_video_cleanup(self):
        self.record(chat_failure=True)

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

    def test_uncaught_thread_exception_is_logged_with_traceback(self):
        ns = load_functions()
        error = RuntimeError('worker crashed')
        args = Mock(exc_type=RuntimeError, exc_value=error, exc_traceback=None)
        ns['logThreadException'](args)
        self.assertEqual(ns['log'].critical.call_args.kwargs['exc_info'],
                         (RuntimeError, error, None))

    def test_watchdog_detects_stall_and_old_process(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'watchdog', pathlib.Path(__file__).resolve().parents[1] / 'watchdog.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        status = {'pid': 10, 'updated': 100, 'unhealthy': False}
        self.assertFalse(module.stale_status(status, 10, 110, 180))
        self.assertTrue(module.stale_status(status, 11, 110, 180))
        self.assertTrue(module.stale_status(status, 10, 281, 180))
        status['unhealthy'] = True
        self.assertTrue(module.stale_status(status, 10, 110, 180))
        with tempfile.TemporaryDirectory() as directory:
            child = Mock()
            stop_path = pathlib.Path(directory) / 'stop.request'
            module.stop_child(child, stop_path)
            self.assertTrue(stop_path.exists())
            child.kill.assert_not_called()
            child.wait.side_effect = [module.subprocess.TimeoutExpired('child', 80), 0]
            module.stop_child(child, stop_path)
            child.kill.assert_called_once()

    def test_health_marks_stalled_worker_and_writes_snapshot(self):
        ns = load_functions()
        import os
        import shutil
        import json
        ns.update(os=os, shutil=shutil, json=json, Path=pathlib.Path,
                  main_progress=time.monotonic(), last_scan=None, faulthandler=Mock())
        ns['progress'] = {'test': {'updated': time.monotonic() - 181, 'bytes': 123}}
        ns['stop_event'] = Mock()
        ns['stop_event'].is_set.side_effect = [False, True]
        with tempfile.TemporaryDirectory() as directory:
            ns.update(save_dir=directory, log_dir=pathlib.Path(directory))
            target = pathlib.Path(directory) / 'health.json'
            with patch.dict(os.environ, {'CAM4_HEALTH_FILE': str(target)}, clear=True):
                ns['reportHealth']()
            status = json.loads(target.read_text())
            self.assertTrue(status['unhealthy'])
            self.assertEqual(status['recordings']['test']['bytes'], 123)
            ns['faulthandler'].dump_traceback.assert_called_once()

    def test_rollover_supports_dotted_directories(self):
        ns = load_functions()
        self.assertEqual(ns['dailyLogNamer']('D:/logs.v1/capture.log.20260915.log'),
                         'D:/logs.v1/capture_20260915.log')


if __name__ == '__main__':
    unittest.main()


