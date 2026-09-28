import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile
import threading
import media_output as media


GOOD = {'format': {'format_name': 'mov,mp4,m4a,3gp,3g2,mj2', 'duration': '2'},
        'streams': [{'codec_type': 'video', 'codec_name': 'h264', 'pix_fmt': 'yuv420p'},
                    {'codec_type': 'audio', 'codec_name': 'aac'}]}


class MediaTests(unittest.TestCase):
    def test_shutdown_terminates_encoder_and_retains_source(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'test.source'
            source.write_bytes(b'original')
            stop = threading.Event()
            stop.set()
            with patch.object(media, 'probe', return_value=GOOD), patch.object(media, 'executable', return_value='ffmpeg'), patch.object(media.subprocess, 'Popen') as popen:
                popen.return_value.poll.return_value = None
                with self.assertRaises(InterruptedError):
                    media.convert(source, stop)
                popen.return_value.terminate.assert_called_once()
            self.assertTrue(source.exists())
            self.assertFalse(source.with_suffix('.mp4').exists())

    def test_rejects_transport_stream_and_missing_video(self):
        self.assertTrue(media.verify_mp4(GOOD))
        self.assertFalse(media.verify_mp4(dict(GOOD, format={'format_name': 'mpegts', 'duration': '2'})))
        self.assertFalse(media.verify_mp4(dict(GOOD, streams=[])))

    def test_failed_conversion_preserves_source_and_never_publishes_output(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'test.source'
            source.write_bytes(b'original')
            with patch.object(media, 'probe', return_value=GOOD), patch.object(media, 'executable', return_value='ffmpeg'), patch.object(media.subprocess, 'Popen') as popen:
                popen.return_value.poll.return_value = 1
                popen.return_value.returncode = 1
                with self.assertRaises(RuntimeError):
                    media.convert(source, threading.Event())
            self.assertEqual(source.read_bytes(), b'original')
            self.assertFalse(source.with_suffix('.mp4').exists())


if __name__ == '__main__':
    unittest.main()
