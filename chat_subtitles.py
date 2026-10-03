"""Generate transparent outlined chat text, with bounded scrolling history."""
import html
import json
import math
from pathlib import Path
import re
import textwrap

LAYOUT_VERSION = 'persistent-stack-v2'


def clean(value):
    value = html.unescape(re.sub(r'<[^>]*>', '', value))
    return ''.join(c for c in value if c >= ' ').replace('\\', '＼').replace('{', '｛').replace('}', '｝')


def stamp(seconds):
    ticks = max(0, round(seconds * 100))
    return f'{ticks // 360000}:{ticks // 6000 % 60:02}:{ticks // 100 % 60:02}.{ticks % 100:02}'


def generate(source, duration, width, height):
    source = Path(source)
    chat = source.with_suffix('.chat.jsonl')
    if not chat.exists():
        return None
    settings = source.with_suffix('.chat-options.json')
    options = json.loads(settings.read_text(encoding='utf-8')) if settings.exists() else {}
    offset = float(options.get('offset_seconds', 0))
    if not math.isfinite(offset):
        raise ValueError('chat offset must be finite')
    messages = []
    for line in chat.read_text(encoding='utf-8').splitlines():
        try:
            item = json.loads(line)
            start = float(item['elapsed']) + offset
            if math.isfinite(start) and start < duration:
                messages.append((max(0, start), item))
        except (ValueError, KeyError, TypeError):
            continue
    if not messages:
        return None
    messages.sort(key=lambda item: item[0])
    font = max(12, round(height / 36))
    margin = max(10, round(width / 60))
    panel_width = max(120, round(width * 0.42))
    chars = max(10, panel_width // font)  # Conservative for CJK glyph widths.
    header = f'''[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Chat,Microsoft JhengHei,{font},&H00FFFFFF,&H00FFFFFF,&H00000000,&HFF000000,0,0,0,0,100,100,0,0,1,2,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    line_height = max(font + 4, round(font * 1.25))
    gap = max(4, round(font * 0.5))
    available_height = height - 2 * margin

    def prepare(item):
        name = clean(item['username'])[:chars]
        wrapped = textwrap.wrap(clean(item['text']), width=chars) or ['']
        content = wrapped[:2]
        if len(wrapped) > 2:
            content[-1] = content[-1][:-1] + '…'
        return name, content, line_height * (1 + len(content)) + gap

    # Repaint the active stack only when a message arrives. Each message remains
    # visible until newer blocks need its vertical space.
    events = {}
    for index, (start, item) in enumerate(messages):
        events.setdefault(start, []).append((index, item))
    active = []
    lines = [header]
    times = sorted(events) + [duration]
    for i, moment in enumerate(times[:-1]):
        for index, item in events[moment]:
            active.append((index, *prepare(item)))
        while len(active) > 1 and sum(block[3] for block in active) > available_height:
            active.pop(0)
        end = times[i + 1]
        y = margin
        for _, name, content, block_height in active:
            text = r'{\c&H00FFFF&}' + name + r':{\c&HFFFFFF&}\N' + r'\N'.join(content)
            position = f'{{\\an7\\pos({margin},{y})}}'
            lines.append(f'Dialogue: 0,{stamp(moment)},{stamp(end)},Chat,,0,0,0,,{position}{text}\n')
            y += block_height
    # Fixed safe filename avoids FFmpeg filter escaping of arbitrary room/path text.
    target = source.with_suffix('.ass')
    target.write_text(''.join(lines), encoding='utf-8-sig')
    return target
