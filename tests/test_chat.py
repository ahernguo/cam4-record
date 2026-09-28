import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from types import ModuleType
from chat_capture import ChatCapture, FirebaseFrames, parse_message
from chat_subtitles import generate, clean


class ChatTests(unittest.TestCase):
    def test_capture_persists_only_new_public_messages_and_closes_browser(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'record.capture'
            capture = ChatCapture(file, 'example', {})
            context = MagicMock()
            browser = context.__enter__.return_value.chromium.launch.return_value
            page = browser.new_page.return_value
            events = {}
            page.on.side_effect = lambda name, callback: events.update({name: callback})
            ws = MagicMock()
            callbacks = {}
            ws.on.side_effect = lambda name, callback: callbacks.update({name: callback})
            def navigate(*args, **kwargs):
                events['websocket'](ws)
                feed = callbacks['framereceived']
                timestamp = int(capture.wall_started * 1000) + 10
                frame = self.packet(data={'p': f'b00men0hash$Alice${timestamp}$10', 'm': 'hello'})
                feed(frame)
                feed(frame)
                feed(self.packet(data={'p': 'b00men0hash$Old$1$10', 'm': 'old'}))
                feed(self.packet(room='other'))
            page.goto.side_effect = navigate
            page.wait_for_timeout.side_effect = lambda _: capture.stop.set()
            module = ModuleType('playwright.sync_api')
            module.sync_playwright = lambda: context
            with patch.dict('sys.modules', {'playwright': ModuleType('playwright'), 'playwright.sync_api': module}):
                capture.run()
            rows = file.with_suffix('.chat.jsonl').read_text(encoding='utf-8').splitlines()
            self.assertEqual(len(rows), 1)
            self.assertEqual(json.loads(rows[0])['text'], 'hello')
            status = json.loads(file.with_suffix('.chat-status.json').read_text())
            self.assertEqual(status['state'], 'stopped')
            self.assertEqual(status['messages'], 1)
            browser.close.assert_called_once()

    def packet(self, room='example', data=None):
        return json.dumps({'t': 'd', 'd': {'a': 'd', 'b': {'p': '/c/' + room,
            'd': data or {'p': 'b00men0hash$Alice$1800000000000$10', 'm': 'Hello'}}}})

    def test_public_frame_and_fragment_assembly(self):
        parser = FirebaseFrames('example')
        frame = self.packet()
        self.assertIsNone(parser.feed('2'))
        self.assertIsNone(parser.feed(frame[:25]))
        self.assertEqual(parser.feed(frame[25:])['username'], 'Alice')
        self.assertIsNone(parser.feed(self.packet(room='other')))
        self.assertIsNone(parser.feed('not json'))
        self.assertIsNone(parser.feed('0'))

    def test_notifications_and_deletions_are_not_text(self):
        self.assertIsNone(parse_message({'t': 3, 'ou': 'Bob', 'tk': 5}))
        self.assertIsNone(parse_message({'delete': True, 'p': 'b$A$123', 'm': 'x'}))
        self.assertIsNone(parse_message({'p': 'invalid', 'm': 'x'}))

    def test_ass_escaping_offset_expiry_and_colors(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'test.source'
            source.with_suffix('.chat.jsonl').write_text(json.dumps({
                'elapsed': 1, 'username': 'Alice', 'text': r'{\pos(1,1)}<b>Hello</b>'}) + '\n', encoding='utf-8')
            source.with_suffix('.chat-options.json').write_text('{"offset_seconds": 2}')
            output = generate(source, 20, 1280, 720).read_text(encoding='utf-8-sig')
            self.assertIn('0:00:03.00,0:00:15.00', output)
            self.assertIn(r'\c&H00FFFF&', output)
            self.assertIn(r'\c&HFFFFFF&', output)
            self.assertNotIn(r'{\pos(1,1)}', output)
            self.assertNotIn('<b>', output)
            self.assertEqual(clean(r'\N'), '＼N')

    def test_empty_capture_does_not_create_overlay(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(generate(Path(folder) / 'empty.source', 20, 1280, 720))


if __name__ == '__main__':
    unittest.main()
