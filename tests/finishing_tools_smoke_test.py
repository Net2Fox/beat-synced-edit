"""Synthetic smoke test for the standalone finishing tools.

Generates a pulse track and colour-bar footage, measures the tempo with
`edit_project.py music`, assembles a white-flash montage, stacks it over-under
and checks both exports with `edit_project.py verify`. No private media needed.
Use --scripts-dir to test an installed skill.
"""
from pathlib import Path
import argparse
import json
import math
import os
import struct
import subprocess
import sys
import wave

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--scripts-dir', type=Path, default=ROOT)
parser.add_argument('--work-dir', type=Path, default=ROOT / 'work/finishing-smoke')
args = parser.parse_args()
scripts = args.scripts_dir.resolve()
root = args.work_dir.resolve() / 'финальные инструменты'
root.mkdir(parents=True, exist_ok=True)
os.environ.setdefault('NUMBA_CACHE_DIR', str(root / 'numba-cache'))
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'


def run(name, command):
    print(f'Running {name}...', flush=True)
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
    (root / f'{name}.log').write_text(result.stdout + '\n' + result.stderr, encoding='utf-8')
    if result.returncode:
        print(result.stdout[-2500:] + result.stderr[-2500:], flush=True)
        raise RuntimeError(f'{name} failed ({result.returncode})')
    print(f'PASS {name}', flush=True)
    return result.stdout


def cli(name, script, *arguments):
    return run(name, [sys.executable, '-X', 'utf8', str(scripts / f'{script}.py'), *map(str, arguments)])


def probe(path):
    data = json.loads(run('probe-' + path.stem, ['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)]))
    video = next(s for s in data['streams'] if s['codec_type'] == 'video')
    assert any(s['codec_type'] == 'audio' for s in data['streams']), path
    return video, float(data['format']['duration'])


song = root / 'ритм 120 BPM.wav'
footage = root / 'исходник.mp4'
if not song.exists():
    sample_rate = 22050
    audio = []
    for i in range(sample_rate * 8):
        t = i / sample_rate
        phase = t % 0.5
        kick = 0.75 * math.exp(-phase * 45) * math.sin(2 * math.pi * (70 * phase + 60 * phase * phase))
        tone = 0.06 * math.sin(2 * math.pi * 220 * t)
        audio.append(struct.pack('<h', int(32767 * (kick + tone))))
    with wave.open(str(song), 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b''.join(audio))
if not footage.exists():
    writer = cv2.VideoWriter(str(footage), cv2.VideoWriter_fourcc(*'mp4v'), 30, (320, 180))
    assert writer.isOpened()
    colors = [(80, 50, 210), (50, 190, 50), (220, 100, 40), (80, 190, 210)]
    for frame_number in range(20 * 30):
        scene = frame_number // 30
        frame = np.full((180, 320, 3), colors[scene % len(colors)], dtype=np.uint8)
        cv2.circle(frame, (40 + (frame_number * 4) % 240, 90), 24, (245, 245, 245), -1)
        cv2.putText(frame, f'SCENE {scene:02}', (65, 155), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
        writer.write(frame)
    writer.release()

for script in ('flash_montage', 'overunder_stack'):
    run(script + '-help', [sys.executable, '-X', 'utf8', str(scripts / f'{script}.py'), '--help'])

beats = root / 'beats.json'
cli('music', 'edit_project', 'music', song, '--duration', '6', '-o', beats)
tempo = json.loads(beats.read_text(encoding='utf-8'))['tempo']
assert 115 <= tempo <= 125, tempo

# Four beats per slot, as the finishing-tools reference recommends.
slot, flash = round(4 * 60 / tempo, 3), 0.2
sequence = {'items': [{'video': str(footage), 'start': 0, 'dur': slot}, {'video': str(footage), 'start': 2, 'dur': slot}]}
(root / 'seq.json').write_text(json.dumps(sequence), encoding='utf-8')
montage = root / 'вспышки.mp4'
cli('flash_montage', 'flash_montage', '--seq', root / 'seq.json', '--audio', song, '--out', montage, '--size', '320', '--flash', flash)
video, duration = probe(montage)
assert (video['width'], video['height']) == (320, 320), video
assert abs(duration - (2 * slot - flash)) < 0.1, duration

stacked = root / 'over-under.mp4'
cli('overunder_stack', 'overunder_stack', montage, '-o', stacked, '--size', '320x360')
stacked_video, stacked_duration = probe(stacked)
assert (stacked_video['width'], stacked_video['height']) == (320, 360), stacked_video
assert abs(stacked_duration - duration) < 0.1, stacked_duration

for path in (montage, stacked):
    cli('verify-' + path.stem, 'edit_project', 'verify', path, '--work', root / 'qa')

report = {'tempo': tempo, 'slot': slot, 'montage_duration': duration, 'stacked_size': [stacked_video['width'], stacked_video['height']]}
(root / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report, indent=2), flush=True)
print('Finishing tools smoke test passed', flush=True)
