"""Build ONE FULL per-episode video containing ALL of the character's scenes.

Replaces fragmented clip delivery: the union of padded visibility windows is
concatenated chronologically into a single file, so nothing of the character's
content is cut, while non-character stretches are removed.

- Reads output/analysis/export_plan.json (windows already exported at CRF16).
- If window files are missing, re-exports them from normalized.mp4 (CRF16).
- Concat method: ffmpeg concat demuxer with -c copy (all segments share the
  same encoder/codec params). Verifies duration parity; if copy-concat is
  broken, falls back to one re-encode (veryfast CRF16).
Output: output/clips/<target>/<target>_FULL_<video_id>.mp4
        output/analysis/full_video.json
"""
import json, os, subprocess, sys

BASE = os.environ.get('CCE_BASE', '/home/z/my-project/clipextractor')
TARGET = os.environ.get('CCE_TARGET', 'ahyeon')
VIDEO_ID = os.environ.get('CCE_VIDEO_ID', '')
AN = f'{BASE}/output/analysis'
VIDEO = f'{AN}/normalized.mp4'
OUTDIR = f'{BASE}/output/clips/{TARGET}'
os.makedirs(OUTDIR, exist_ok=True)

plan = json.load(open(f'{AN}/export_plan.json'))
clips = [c for c in plan['clips'] if c.get('export_ok')]
assert clips, 'export_plan has no exportable windows'

FULL = f'{OUTDIR}/{TARGET}_FULL_{VIDEO_ID}.mp4'.replace('__', '_')
tmp = FULL.replace('.mp4', '.tmp.mp4')

# sanity: every window must exist
missing = [c['clip'] for c in clips if not os.path.exists(f"{OUTDIR}/{c['clip']}")]
if missing:
    print(f'MISSING_WINDOWS {missing} — re-exporting from source')
    env = dict(os.environ)
    subprocess.run([sys.executable, f'{BASE}/scripts/06_export_clips.py'],
                   env=env, check=True)
    missing = [c['clip'] for c in clips if not os.path.exists(f"{OUTDIR}/{c['clip']}")]
    if missing:
        print('REEXPORT_FAILED'); sys.exit(1)

expected = sum(c['window'][1] - c['window'][0] for c in clips)

def dur_of(p):
    out = subprocess.check_output(['ffprobe', '-v', 'quiet', '-print_format', 'json',
                                   '-show_format', p], text=True)
    return float(json.loads(out)['format']['duration'])

def concat_copy():
    lst = f'{AN}/concat_list.txt'
    with open(lst, 'w') as f:
        for c in clips:
            p = os.path.join(OUTDIR, c['clip'])
            f.write(f"file '{p}'\n")
    r = subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'concat',
                        '-safe', '0', '-i', lst, '-c', 'copy',
                        '-movflags', '+faststart', tmp], capture_output=True, text=True)
    return r.returncode == 0 and os.path.exists(tmp)

def concat_reencode():
    inputs, segs = [], []
    for c in clips:
        inputs += ['-ss', f"{c['window'][0]:.3f}", '-i', VIDEO]
    for i in range(len(clips)):
        segs.append(f'[{i}:v]scale=flags=bicubic,format=yuv420p[v{i}];'
                    f'[{i}:a]aformat=sample_rates=44100:channel_layouts=stereo[a{i}]')
    fc = ';'.join(segs) + ';' + ''.join(f'[v{i}][a{i}]' for i in range(len(clips))) + \
         f'concat=n={len(clips)}:v=1:a=1[vout][aout]'
    r = subprocess.run(['ffmpeg', '-y', '-loglevel', 'error'] + inputs +
                       ['-filter_complex', fc, '-map', '[vout]', '-map', '[aout]',
                        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '16',
                        '-c:a', 'aac', '-b:a', '192k',
                        '-movflags', '+faststart', tmp],
                       capture_output=True, text=True)
    return r.returncode == 0 and os.path.exists(tmp)

ok = concat_copy()
method = 'stream-copy concat'
if ok:
    d = dur_of(tmp)
    if abs(d - expected) > 1.0:      # broken timestamps -> re-encode fallback
        print(f'COPY_CONCAT_BAD dur={d:.1f} expected={expected:.1f}; re-encoding')
        os.remove(tmp)
        ok = False
if not ok:
    if os.path.exists(tmp):
        os.remove(tmp)
    ok = concat_reencode()
    method = 're-encode concat (veryfast crf16)'
if not ok:
    print('CONCAT_FAILED'); sys.exit(1)

os.replace(tmp, FULL)
d = dur_of(FULL)
size_mb = os.path.getsize(FULL) / 1e6
vinfo = json.loads(subprocess.check_output(
    ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', FULL], text=True))
v = next(s for s in vinfo['streams'] if s['codec_type'] == 'video')
a = next((s for s in vinfo['streams'] if s['codec_type'] == 'audio'), None)

json.dump({'full_video': os.path.basename(FULL),
           'method': method, 'n_windows': len(clips),
           'expected_s': round(expected, 2), 'duration_s': round(d, 2),
           'resolution': f"{v['width']}x{v['height']}", 'codec': v['codec_name'],
           'has_audio': a is not None, 'size_mb': round(size_mb, 2),
           'windows': [c['window'] for c in clips]},
          open(f'{AN}/full_video.json', 'w'), indent=1)
print(f"FULL_VIDEO {os.path.basename(FULL)}: {d:.1f}s (expected {expected:.1f}s) "
      f"{v['width']}x{v['height']} {v['codec_name']} audio={a is not None} {size_mb:.1f}MB [{method}]")
print('FULL_VIDEO_OK')
