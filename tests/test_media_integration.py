"""Offline end-to-end verification with generated media, never a live broadcast."""
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
import media_output as media


class MediaIntegrationTests(unittest.TestCase):
    def test_full_range_source_becomes_standard_yuv420p(self):
        try:
            ffmpeg = media.executable('ffmpeg')
            media.executable('ffprobe')
        except RuntimeError as error:
            self.skipTest(str(error))
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'full-range.source'
            subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi',
                '-i', 'color=c=gray:s=640x360:r=30', '-t', '2', '-c:v', 'libx264',
                '-pix_fmt', 'yuvj420p', '-color_range', 'pc', '-f', 'mpegts', str(source)],
                check=True, timeout=30)
            self.assertEqual(media.probe(source)['streams'][0]['pix_fmt'], 'yuvj420p')
            media.process_recording(source, threading.Event())
            target = source.with_suffix('.chat.mp4')
            info = media.probe(target)
            self.assertTrue(media.verify_mp4(info))
            self.assertEqual(info['streams'][0]['codec_name'], 'hevc')
            self.assertEqual(info['streams'][0]['codec_tag_string'], 'hvc1')
            self.assertEqual(info['streams'][0]['pix_fmt'], 'yuv420p')
            # Limited range is the default for yuv420p; encoders may omit the
            # optional color_range tag rather than reporting it as "tv".
            self.assertIn(info['streams'][0].get('color_range'), (None, 'tv'))

    def test_h264_without_audio_is_transcoded_to_hevc(self):
        try:
            ffmpeg = media.executable('ffmpeg')
            media.executable('ffprobe')
        except RuntimeError as error:
            self.skipTest(str(error))
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'silent.source'
            subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'color=s=320x240:r=25',
                '-t', '1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-f', 'mpegts', str(source)],
                check=True, timeout=30)
            target = media.convert(source, threading.Event())
            info = media.probe(target)
            self.assertTrue(media.verify_mp4(info))
            self.assertEqual(len(info['streams']), 1)
            self.assertEqual(info['streams'][0]['codec_name'], 'hevc')
            self.assertEqual(info['streams'][0]['codec_tag_string'], 'hvc1')

    def test_transport_stream_transcode_and_chat_burn_in(self):
        try:
            ffmpeg = media.executable('ffmpeg')
            media.executable('ffprobe')
        except RuntimeError as error:
            self.skipTest(str(error))
        with tempfile.TemporaryDirectory(prefix='cam4 media ') as folder:
            source = Path(folder) / 'synthetic.source'
            subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=640x360:r=25',
                '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-t', '14',
                '-c:v', 'mpeg2video', '-c:a', 'mp2', '-f', 'mpegts', str(source)], check=True, timeout=30)
            self.assertEqual(media.probe(source)['format']['format_name'], 'mpegts')
            source.with_suffix('.chat.jsonl').write_text(json.dumps({
                'elapsed': 0, 'username': 'Alice', 'text': 'Hello 測試'}) + '\n', encoding='utf-8')
            source.with_suffix('.chat-options.json').write_text(json.dumps({
                'layout': 'persistent-stack-v2'}), encoding='utf-8')
            before = subprocess.run([ffmpeg, '-v', 'error', '-ss', '13', '-i', str(source), '-frames:v', '1',
                '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True,
                check=True, timeout=30).stdout
            media.process_recording(source, threading.Event())
            chat = source.with_suffix('.chat.mp4')
            self.assertTrue(media.verify_mp4(media.probe(chat)))
            # The first message remains burned in after 13 seconds; the old layout
            # would have removed it at 12 seconds.
            after = subprocess.run([ffmpeg, '-v', 'error', '-ss', '13', '-i', str(chat), '-frames:v', '1',
                '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True,
                check=True, timeout=30).stdout
            self.assertEqual(len(before), 640 * 360 * 3)
            self.assertEqual(len(before), len(after))
            self.assertNotEqual(before, after)
            self.assertFalse(source.exists())
            self.assertFalse(source.with_suffix('.chat.jsonl').exists())
            self.assertFalse(source.with_suffix('.chat-options.json').exists())
            self.assertFalse(source.with_suffix('.ass').exists())
            self.assertFalse(source.with_suffix('.mp4').exists())
            self.assertEqual([file.name for file in Path(folder).iterdir()],
                             ['synthetic.chat.mp4'])
            # The right half is outside the overlay; it stays visually blue.
            offset = (180 * 640 + 600) * 3
            self.assertGreater(after[offset + 2], 240)


if __name__ == '__main__':
    unittest.main()
