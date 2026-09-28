"""Durable, restartable MP4 post-processing. Never discard captured bytes."""
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess

log = logging.getLogger('cam4_capture')


def executable(name):
    value = os.environ.get('CAM4_' + name.upper(), name)
    found = shutil.which(value)
    if not found and value == name:
        found = next((str(p) for p in (Path(__file__).parent / '.tools').glob(f'ffmpeg*/bin/{name}.exe')), None)
    if not found:
        raise RuntimeError(f'{name} not found; set CAM4_{name.upper()} to its executable path')
    return found


def probe(file):
    result = subprocess.run([executable('ffprobe'), '-v', 'error', '-show_format',
                             '-show_streams', '-of', 'json', str(file)],
                            capture_output=True, text=True, check=True, timeout=60,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return json.loads(result.stdout)


def verify_mp4(info):
    videos = [s for s in info.get('streams', []) if s['codec_type'] == 'video']
    audio = [s for s in info.get('streams', []) if s['codec_type'] == 'audio']
    return ('mp4' in info.get('format', {}).get('format_name', '').split(',')
            and float(info.get('format', {}).get('duration', 0)) > 0
            and bool(videos) and videos[0].get('codec_name') == 'h264'
            and videos[0].get('pix_fmt') == 'yuv420p'
            and all(s.get('codec_name') == 'aac' for s in audio))


def convert(source, stop, subtitle=None, suffix=''):
    source = Path(source)
    target = source.with_suffix(suffix + '.mp4')
    if target.exists():
        return target
    info = probe(source)
    videos = [s for s in info['streams'] if s['codec_type'] == 'video']
    if not videos:
        raise ValueError('capture contains no video stream')
    temporary = target.with_suffix('.encoding.mp4')
    command = [executable('ffmpeg'), '-nostdin', '-y', '-v', 'warning', '-i', str(source),
               '-map', '0:v:0', '-map', '0:a:0?', '-sn', '-dn']
    # Remux compatible streams; encode only when necessary or when burning text.
    compatible = videos[0].get('codec_name') == 'h264' and videos[0].get('pix_fmt') == 'yuv420p'
    command += ['-c:v', 'copy'] if compatible and not subtitle else [
        '-vf', ('ass=' + subtitle.name + ',' if subtitle else '') + 'pad=ceil(iw/2)*2:ceil(ih/2)*2',
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p']
    audio = [s for s in info['streams'] if s['codec_type'] == 'audio']
    command += ['-c:a', 'copy' if not audio or audio[0].get('codec_name') == 'aac' else 'aac',
                '-movflags', '+faststart', '-f', 'mp4', str(temporary)]
    with target.with_suffix('.ffmpeg.log').open('w', encoding='utf-8') as errors:
        child = subprocess.Popen(command, cwd=source.parent, stdout=subprocess.DEVNULL,
                                 stderr=errors, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            while child.poll() is None:
                if stop.wait(0.5):
                    child.terminate()
                    raise InterruptedError('conversion interrupted; source retained for retry')
            if child.returncode:
                raise RuntimeError(f'ffmpeg failed ({child.returncode}); see {target.with_suffix(".ffmpeg.log")}')
        finally:
            if child.poll() is None:
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
    if not verify_mp4(probe(temporary)):
        raise ValueError('output failed MP4/H.264/AAC validation')
    os.replace(temporary, target)
    log.info('verified MP4: %s', target)
    return target


def process_recording(source, stop):
    convert(source, stop)


def worker(root, stop):
    attempted = set()
    while not stop.is_set():
        for source in Path(root).resolve().rglob('*.source'):
            if stop.is_set():
                return
            if source in attempted:
                continue
            attempted.add(source)
            try:
                process_recording(source, stop)
            except Exception:
                log.exception('post-processing failed; source retained: %s', source)
        stop.wait(5)
