import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile
import threading
import media_output as media


GOOD = {'format': {'format_name': 'mov,mp4,m4a,3gp,3g2,mj2', 'duration': '2'},
        'streams': [{'codec_type': 'video', 'codec_name': 'hevc', 'pix_fmt': 'yuv420p'},
                    {'codec_type': 'audio', 'codec_name': 'aac'}]}


class MediaTests(unittest.TestCase):
    def test_bad_transport_clock_uses_measured_standard_frame_rate(self):
        info = {'streams': [{'codec_type': 'video', 'r_frame_rate': '90000/1',
            'avg_frame_rate': '0/0', 'duration': '369.116011',
            'nb_read_packets': '10922'}]}
        self.assertEqual(media.output_frame_rate(info), '30000/1001')

    def test_validation_explains_full_range_pixel_format(self):
        info = {'format': {'format_name': 'mov,mp4', 'duration': '2'},
                'streams': [{'codec_type': 'video', 'codec_name': 'hevc',
                             'pix_fmt': 'yuvj420p',
                             'avg_frame_rate': '90000/1'}]}
        self.assertEqual(media.validation_errors(info),
                         ['pixel format is yuvj420p, expected yuv420p',
                          'frame rate is 90000, expected 120 or lower'])

    def test_legacy_layout_rebuilds_existing_chat_output(self):
        info = {'format': {'duration': '20'}, 'streams': [
            {'codec_type': 'video', 'width': 640, 'height': 360}]}
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'test.source'
            source.write_bytes(b'source')
            source.with_suffix('.chat-options.json').write_text('{"offset_seconds": 0}')
            subtitle = source.with_suffix('.ass')
            subtitle.write_text('subtitle')
            target = source.with_suffix('.chat.mp4')
            with patch.object(media, 'probe', return_value=info), \
                    patch('chat_subtitles.generate', return_value=subtitle), \
                    patch.object(media, 'convert', return_value=target) as convert, \
                    patch.object(media, 'cleanup_recording') as cleanup:
                media.process_recording(source, threading.Event())
            self.assertTrue(convert.call_args.kwargs['overwrite'])
            cleanup.assert_called_once_with(source, target)

    def test_cleanup_failure_retains_source_for_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'test.source'
            target = Path(folder) / 'test.chat.mp4'
            source.write_bytes(b'source')
            target.write_bytes(b'output')
            original_unlink = Path.unlink
            def unlink(path, *args, **kwargs):
                if path.name == 'test.ass':
                    raise OSError('locked')
                return original_unlink(path, *args, **kwargs)
            source.with_suffix('.ass').write_bytes(b'subtitle')
            with patch.object(Path, 'unlink', autospec=True, side_effect=unlink):
                with self.assertRaises(RuntimeError):
                    media.cleanup_recording(source, target)
            self.assertTrue(source.exists())
            self.assertTrue(target.exists())

    def test_cleanup_retains_only_final_chat_mp4_and_unrelated_files(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'test.source'
            target = Path(folder) / 'test.chat.mp4'
            unrelated = Path(folder) / 'another.source'
            for file in (source, target, unrelated, source.with_suffix('.mp4'),
                         source.with_suffix('.chat.jsonl'), source.with_suffix('.ass'),
                         source.with_suffix('.chat.ffmpeg.log')):
                file.write_bytes(b'data')
            media.cleanup_recording(source, target)
            self.assertEqual(sorted(file.name for file in Path(folder).iterdir()),
                             ['another.source', 'test.chat.mp4'])

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
