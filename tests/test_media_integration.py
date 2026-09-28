"""Offline end-to-end verification with generated media, never a live broadcast."""
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
import media_output as media


class MediaIntegrationTests(unittest.TestCase):
    def test_h264_without_audio_is_remuxed(self):
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
            # Decoded frames stay identical through the copy/remux path.
            hashes = []
            for file in (source, target):
                hashes.append(subprocess.run([ffmpeg, '-v', 'error', '-i', str(file), '-map', '0:v',
                    '-f', 'hash', '-'], check=True, capture_output=True, timeout=30).stdout)
            self.assertEqual(hashes[0], hashes[1])

    def test_transport_stream_transcode_and_chat_burn_in(self):
        try:
            ffmpeg = media.executable('ffmpeg')
            media.executable('ffprobe')
        except RuntimeError as error:
            self.skipTest(str(error))
        with tempfile.TemporaryDirectory(prefix='cam4 media ') as folder:
            source = Path(folder) / 'synthetic.source'
            subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=640x360:r=25',
                '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-t', '2',
                '-c:v', 'mpeg2video', '-c:a', 'mp2', '-f', 'mpegts', str(source)], check=True, timeout=30)
            self.assertEqual(media.probe(source)['format']['format_name'], 'mpegts')
            source.with_suffix('.chat.jsonl').write_text(json.dumps({
                'elapsed': 0, 'username': 'Alice', 'text': 'Hello 測試'}) + '\n', encoding='utf-8')
            media.process_recording(source, threading.Event())
            plain = source.with_suffix('.mp4')
            chat = source.with_suffix('.chat.mp4')
            self.assertTrue(media.verify_mp4(media.probe(plain)))
            self.assertTrue(media.verify_mp4(media.probe(chat)))
            self.assertTrue(source.exists())
            def frame(file):
                return subprocess.run([ffmpeg, '-v', 'error', '-i', str(file), '-frames:v', '1',
                    '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True, check=True, timeout=30).stdout
            before, after = frame(plain), frame(chat)
            self.assertEqual(len(before), 640 * 360 * 3)
            self.assertEqual(len(before), len(after))
            self.assertNotEqual(before, after)
            # The right half is outside the overlay; it stays visually blue.
            offset = (180 * 640 + 600) * 3
            self.assertGreater(after[offset + 2], 240)


if __name__ == '__main__':
    unittest.main()
