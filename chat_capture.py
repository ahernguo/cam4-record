"""Read public CAM4 Firebase messages observed in a normal browser session."""
from collections import deque
import json
import logging
from pathlib import Path
import threading
import time
from urllib.parse import quote

log = logging.getLogger('cam4_capture')


def parse_message(data):
    if not isinstance(data, dict) or 'delete' in data:
        return None
    props = data.get('p')
    if not isinstance(props, str) or not isinstance(data.get('m'), str):
        return None
    parts = props.split('$')
    if len(parts) < 3 or not parts[1] or not parts[2].isdigit():
        return None
    return {'username': parts[1], 'text': data['m'], 'server_ms': int(parts[2])}


class FirebaseFrames:
    def __init__(self, room):
        self.path = '/c/' + room.lower()
        self.fragments = []
        self.remaining = 0
        self.buffered = 0
        self.state = {}

    def feed(self, frame):
        if not isinstance(frame, str) or len(frame) > 2_000_000:
            return None
        if self.remaining:
            self.buffered += len(frame)
            if self.buffered > 2_000_000:
                self.fragments = []
                self.remaining = 0
                self.buffered = 0
                return None
            self.fragments.append(frame)
            self.remaining -= 1
            if self.remaining:
                return None
            frame = ''.join(self.fragments)
            self.fragments = []
            self.buffered = 0
        elif frame.isdigit() and len(frame) <= 6:
            count = int(frame)
            if 0 < count <= 128:
                self.remaining = count
            return None
        try:
            packet = json.loads(frame)
            if not isinstance(packet, dict) or packet.get('t') != 'd':
                return None
            message = packet.get('d', {})
            if message.get('a') not in ('d', 'm'):
                return None
            body = message.get('b', {})
            if '/' + body.get('p', '').strip('/') != self.path:
                return None
            data = body.get('d')
            if message['a'] == 'm' and isinstance(data, dict):
                self.state.update(data)
            else:
                self.state = data if isinstance(data, dict) else {}
            return parse_message(self.state)
        except (ValueError, TypeError, AttributeError):
            return None


class ChatCapture:
    def __init__(self, file, room, options):
        self.file = Path(file)
        self.room = room
        self.options = options
        self.stop = threading.Event()
        self.started = time.monotonic()
        self.wall_started = time.time()
        self.thread = threading.Thread(target=self.run, name=f'chat-{room}', daemon=True)

    def start(self):
        self.thread.start()

    def close(self):
        self.stop.set()
        self.thread.join(50)
        if self.thread.is_alive():
            log.warning('chat did not stop in time: %s', self.room)

    def run(self):
        count = 0
        sockets = 0
        seen = set()
        recent = deque()
        status = self.file.with_suffix('.chat-status.json')
        def report(state):
            status.write_text(json.dumps({'state': state, 'messages': count, 'sockets': sockets,
                'updated': time.time(), 'timing': 'receive-time; HLS delay not calibrated'}), encoding='utf-8')
        try:
            from playwright.sync_api import sync_playwright
            with self.file.with_suffix('.chat.jsonl').open('w', encoding='utf-8') as output, sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True, channel=self.options.get('browser_channel', 'msedge'))
                try:
                    page = browser.new_page()
                    page.route('**/*', lambda route: route.abort() if route.request.resource_type in
                               ('image', 'media') else route.continue_())
                    def connected(ws):
                        nonlocal sockets
                        sockets += 1
                        parser = FirebaseFrames(self.room)
                        def received(frame):
                            nonlocal count
                            item = parser.feed(frame)
                            if not item or not item['text'].strip() or item['server_ms'] < self.wall_started * 1000:
                                return
                            key = (item['server_ms'], item['username'], item['text'])
                            if key in seen:
                                return
                            seen.add(key)
                            recent.append(key)
                            if len(recent) > 10000:
                                seen.discard(recent.popleft())
                            item.update(elapsed=time.monotonic() - self.started, received_at=time.time())
                            output.write(json.dumps(item, ensure_ascii=False) + '\n')
                            output.flush()
                            count += 1
                        ws.on('framereceived', received)
                    page.on('websocket', connected)
                    while not self.stop.is_set():
                        try:
                            page.goto('https://www.cam4.com/' + quote(self.room, safe=''),
                                      wait_until='domcontentloaded', timeout=20000)
                            report('observing')
                            last_report = time.monotonic()
                            while not self.stop.is_set():
                                page.wait_for_timeout(250)
                                if time.monotonic() - last_report > 10:
                                    report('observing' if count else 'waiting-for-public-messages')
                                    last_report = time.monotonic()
                        except Exception as error:
                            log.warning('chat retry %s: %s', self.room, type(error).__name__)
                            report('retrying')
                            self.stop.wait(5)
                finally:
                    browser.close()
            report('stopped')
        except Exception:
            log.exception('chat capture unavailable: %s', self.room)
            report('failed')


def start(file, room, options):
    if not options.get('enabled', True):
        return None
    try:
        capture = ChatCapture(file, room, options)
        capture.start()
        return capture
    except Exception:
        log.exception('could not start chat; video capture will continue')
        return None
