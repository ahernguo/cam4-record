"""Durable MP4 post-processing with cleanup only after output validation."""
import json
import logging
import os
from pathlib import Path
from fractions import Fraction
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
    result = subprocess.run([executable('ffprobe'), '-v', 'error', '-count_packets', '-show_format',
                             '-show_streams', '-of', 'json', str(file)],
                            capture_output=True, text=True, check=True, timeout=60,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return json.loads(result.stdout)


def validation_errors(info):
    errors = []
    videos = [s for s in info.get('streams', []) if s['codec_type'] == 'video']
    audio = [s for s in info.get('streams', []) if s['codec_type'] == 'audio']
    if 'mp4' not in info.get('format', {}).get('format_name', '').split(','):
        errors.append('container is not MP4')
    try:
        if float(info.get('format', {}).get('duration', 0)) <= 0:
            errors.append('duration is not positive')
    except (TypeError, ValueError):
        errors.append('duration is invalid')
    if not videos:
        errors.append('video stream is missing')
    else:
        if videos[0].get('codec_name') != 'h264':
            errors.append(f"video codec is {videos[0].get('codec_name')}, expected h264")
        if videos[0].get('pix_fmt') != 'yuv420p':
            errors.append(f"pixel format is {videos[0].get('pix_fmt')}, expected yuv420p")
        level = videos[0].get('level')
        if isinstance(level, int) and level > 52:
            errors.append(f'H.264 level is {level / 10:g}, expected 5.2 or lower')
        try:
            rate = Fraction(videos[0].get('avg_frame_rate', '0/1'))
            if float(rate) > 120:
                errors.append(f'frame rate is {float(rate):g}, expected 120 or lower')
        except (ValueError, ZeroDivisionError):
            pass
    invalid_audio = [s.get('codec_name') for s in audio if s.get('codec_name') != 'aac']
    if invalid_audio:
        errors.append(f'audio codec is {invalid_audio[0]}, expected aac')
    return errors


def verify_mp4(info):
    return not validation_errors(info)


def output_frame_rate(info):
    video = next((s for s in info.get('streams', []) if s.get('codec_type') == 'video'), {})
    for field in ('avg_frame_rate', 'r_frame_rate'):
        try:
            rate = Fraction(video.get(field, '0/1'))
            if 1 <= float(rate) <= 120:
                return str(rate)
        except (ValueError, ZeroDivisionError):
            pass
    try:
        measured = int(video['nb_read_packets']) / float(video['duration'])
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        measured = 30.0
    common = [Fraction(15), Fraction(20), Fraction(24000, 1001), Fraction(24),
              Fraction(25), Fraction(30000, 1001), Fraction(30), Fraction(50),
              Fraction(60000, 1001), Fraction(60)]
    nearest = min(common, key=lambda rate: abs(float(rate) - measured))
    if abs(float(nearest) - measured) / float(nearest) <= 0.1:
        return str(nearest)
    return f'{min(120, max(1, measured)):.3f}'


def convert(source, stop, subtitle=None, suffix='', overwrite=False):
    source = Path(source)
    target = source.with_suffix(suffix + '.mp4')
    if target.exists() and not overwrite:
        if verify_mp4(probe(target)):
            return target
        raise ValueError(f'existing output is not a valid MP4: {target}')
    info = probe(source)
    videos = [s for s in info['streams'] if s['codec_type'] == 'video']
    if not videos:
        raise ValueError('capture contains no video stream')
    temporary = target.with_suffix('.encoding.mp4')
    command = [executable('ffmpeg'), '-nostdin', '-y', '-v', 'warning', '-i', str(source),
               '-map', '0:v:0', '-map', '0:a:0?', '-sn', '-dn']
    # Remux compatible streams; encode only when necessary or when burning text.
    compatible = videos[0].get('codec_name') == 'h264' and videos[0].get('pix_fmt') == 'yuv420p'
    if compatible and not subtitle:
        command += ['-c:v', 'copy']
    else:
        filters = []
        if videos[0].get('pix_fmt') == 'yuvj420p' or videos[0].get('color_range') == 'pc':
            filters.append('scale=in_range=full:out_range=limited')
        filters.append('format=yuv420p')
        if subtitle:
            filters.append('ass=' + subtitle.as_posix())
        filters.append('pad=ceil(iw/2)*2:ceil(ih/2)*2')
        command += ['-vf', ','.join(filters), '-c:v', 'libx264', '-preset', 'veryfast',
                    '-crf', '20', '-pix_fmt', 'yuv420p', '-color_range', 'tv',
                    '-r', output_frame_rate(info), '-fps_mode', 'cfr']
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
    errors = validation_errors(probe(temporary))
    if errors:
        raise ValueError('output failed MP4/H.264/AAC validation: ' + '; '.join(errors))
    os.replace(temporary, target)
    log.info('verified MP4: %s', target)
    return target


def cleanup_recording(source, target):
    source = Path(source)
    artifacts = [
        source.with_suffix('.mp4'),
        source.with_suffix('.chat.jsonl'),
        source.with_suffix('.chat-status.json'),
        source.with_suffix('.ass'),
        source.with_suffix('.ffmpeg.log'),
        source.with_suffix('.chat.ffmpeg.log'),
        source.with_suffix('.encoding.mp4'),
        source.with_suffix('.chat.encoding.mp4'),
        source.with_suffix('.chat-options.json'),
    ]
    failures = []
    for artifact in artifacts:
        if artifact == target:
            continue
        try:
            artifact.unlink(missing_ok=True)
        except OSError as error:
            failures.append((artifact, error))
    if failures:
        details = ', '.join(str(artifact) for artifact, _ in failures)
        raise RuntimeError(f'could not remove temporary artifacts: {details}')
    source.unlink()


def process_recording(source, stop):
    import chat_subtitles
    source = Path(source)
    info = probe(source)
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    subtitle = chat_subtitles.generate(source, float(info['format']['duration']),
                                       video['width'], video['height'])
    options_path = source.with_suffix('.chat-options.json')
    options = json.loads(options_path.read_text(encoding='utf-8')) if options_path.exists() else {}
    rebuild = options.get('layout') != chat_subtitles.LAYOUT_VERSION
    if subtitle:
        import tempfile
        with tempfile.TemporaryDirectory(prefix='chat-', dir=source.parent) as folder:
            safe = Path(folder) / 'chat.ass'
            shutil.copyfile(subtitle, safe)
            relative = safe.relative_to(source.parent).as_posix()
            target = convert(source, stop, subtitle=Path(relative), suffix='.chat',
                             overwrite=rebuild)
    else:
        log.warning('no usable chat messages; creating video-only chat MP4: %s', source)
        target = convert(source, stop, suffix='.chat', overwrite=rebuild)
    cleanup_recording(source, target)
    log.info('final recording retained; temporary artifacts removed: %s', target)


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
