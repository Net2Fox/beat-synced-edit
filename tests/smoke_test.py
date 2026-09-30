from pathlib import Path
import argparse
import os
import json
import math
import struct
import subprocess
import sys
import wave

import cv2
import numpy as np

repository = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description='Synthetic video/audio smoke test; no private media required.')
parser.add_argument('--skill-dir', type=Path, default=repository / 'skills/beat-sync-edit')
parser.add_argument('--work-dir', type=Path, default=repository / 'work/smoke')
args = parser.parse_args()
root = args.work_dir.resolve() / 'тест эдита'
root.mkdir(parents=True, exist_ok=True)
skill = args.skill_dir.resolve()
scripts = skill / 'scripts'
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


def cli(name, *args):
    return run(name, [sys.executable, '-X', 'utf8', str(scripts / f'{name}.py'), *map(str, args)])


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

for name in ('beat_map', 'clip_tag', 'plan_edit', 'render_edit', 'vertical_style', 'flash_montage', 'overunder_stack'):
    run(name + '-help', [sys.executable, '-X', 'utf8', str(scripts / f'{name}.py'), '--help'])

beatmap, clips, edl = (root / name for name in ('beatmap.json', 'clips.json', 'edit.json'))
cli('beat_map', song, '-o', beatmap)
cli('clip_tag', footage, '--thumbs', '-o', clips)
cli('plan_edit', beatmap, clips, '--full', '-o', edl)
cli('render_edit', edl, '-a', song, '-v', footage, '-o', root / 'cut.mp4')
cli('vertical_style', root / 'cut.mp4', '--fit', 'cover', '--grade', 'none', '--size', '1080x1920', '-o', root / 'vertical.mp4')

sequence = {'items': [{'video': str(footage), 'start': 0, 'dur': 1.5}, {'video': str(footage), 'start': 2, 'dur': 1.5}]}
(root / 'seq.json').write_text(json.dumps(sequence), encoding='utf-8')
cli('flash_montage', '--seq', root / 'seq.json', '--audio', song, '--out', root / 'flash.mp4', '--size', '320', '--flash', '0.2')

data = json.loads(beatmap.read_text(encoding='utf-8'))
plan = json.loads(edl.read_text(encoding='utf-8'))
assert data['beat_count'] >= 8, data
assert 115 <= data['tempo'] <= 125, data['tempo']
assert len(plan['edits']) >= 4
assert plan['edits'][0]['timeline_start'] == 0
assert abs(plan['audio_segment']['start'] - data['beats'][0]) < 0.001
assert (root / 'clips_thumbs.jpg').exists()
probe = json.loads(run('probe', ['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(root / 'vertical.mp4')]))
video = next(s for s in probe['streams'] if s['codec_type'] == 'video')
assert (video['width'], video['height']) == (1080, 1920)
assert any(s['codec_type'] == 'audio' for s in probe['streams'])
assert video['codec_name'] == 'h264'
assert abs(float(probe['format']['duration']) - plan['timeline_duration']) < 0.07
report = {'tempo': data['tempo'], 'beats': data['beat_count'], 'cuts': len(plan['edits']), 'planned_duration': plan['timeline_duration'], 'rendered_duration': float(probe['format']['duration']), 'dimensions': [video['width'], video['height']], 'first_planned_cut_start': plan['edits'][0]['timeline_start']}
(root / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report, indent=2), flush=True)
print('Smoke test passed', flush=True)
