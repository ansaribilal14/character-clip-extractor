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

# Human-review extras (see README "Human review"): micro-detections that the
# grouping layer dropped as likely false positives, visually verified by a
# human and accepted into the full video. Each entry: {start, end, accept}.
review_path = f'{AN}/review_verified.json'
review = []
if os.path.exists(review_path):
    review = [r for r in json.load(open(review_path)) if r.get('accept')]


def merge_windows(windows, gap=0.25):
    """Union-merge overlapping/adjacent [start, end] windows (no dup content)."""
    ws = sorted([list(w) for w in windows])
    if not ws:
        return []
    out = [ws[0]]
    for a, b in ws[1:]:
        if a <= out[-1][1] + gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [tuple(w) for w in out]


# union-merge ALL windows (plan windows already padded, review raw micros get
# the same PAD as scenes) then export one segment per merged window
PAD = float(os.environ.get('CCE_PAD', '5'))
def _video_dur():
    try:
        out = subprocess.check_output(['ffprobe', '-v', 'quiet', '-print_format', 'json',
                                       '-show_format', VIDEO], text=True)
        return float(json.loads(out)['format']['duration'])
    except Exception:
        return None


VDUR = _video_dur()
raw_windows = [(c['window'][0], min(c['window'][1], VDUR)) for c in clips] if VDUR else \
    [(c['window'][0], c['window'][1]) for c in clips]
raw_windows += [(max(0.0, r['start'] - PAD), min(r['end'] + PAD, VDUR)) for r in review]
merged = merge_windows(raw_windows)


def encode_segment(idx, a, b):
    out = f'{OUTDIR}/full_{idx:03d}.mp4'
    if not os.path.exists(out):
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error',
                        '-ss', f'{a:.3f}', '-to', f'{b:.3f}', '-i', VIDEO,
                        '-c:v', 'libx264', '-preset', 'medium', '-crf', '16',
                        '-c:a', 'aac', '-b:a', '192k',
                        '-movflags', '+faststart', out], check=True)
    return {'window': [a, b], 'clip': os.path.basename(out)}


clips = [encode_segment(i, a, b) for i, (a, b) in enumerate(merged)]

assert clips, 'no exportable windows'
print(f'WINDows: {len(raw_windows)} raw -> {len(merged)} merged '
      f'({len(review)} human-review extras)', flush=True)

FULL = f'{OUTDIR}/{TARGET}_FULL_{VIDEO_ID}.mp4'.replace('__', '_')
tmp = FULL.replace('.mp4', '.tmp.mp4')

# sanity: every window must exist
missing = [c['clip'] for c in clips if not os.path.exists(f"{OUTDIR}/{c['clip']}")]
if missing:
    print(f'MISSING_WINDOWS {missing} — re-encoding from source')
    for c in clips:
        p = os.path.join(OUTDIR, c['clip'])
        if not os.path.exists(p):
            a, b = c['window']
            subprocess.run(['ffmpeg', '-y', '-loglevel', 'error',
                            '-ss', f'{a:.3f}', '-to', f'{b:.3f}', '-i', VIDEO,
                            '-c:v', 'libx264', '-preset', 'medium', '-crf', '16',
                            '-c:a', 'aac', '-b:a', '192k',
                            '-movflags', '+faststart', p], check=True)
    missing = [c['clip'] for c in clips if not os.path.exists(f"{OUTDIR}/{c['clip']}")]
    if missing:
        print('REEXPORT_FAILED'); sys.exit(1)

def dur_of(p):
    try:
        out = subprocess.check_output(['ffprobe', '-v', 'quiet', '-print_format', 'json',
                                       '-show_format', p], text=True)
        return float(json.loads(out)['format']['duration'])
    except Exception:
        return -1.0


# parity baseline = the ACTUAL segment durations (input-seeking keyframe
# rounding makes per-segment files a bit longer than their windows); comparing
# the concat output against this sum still catches broken concatenation
expected = sum(dur_of(os.path.join(OUTDIR, c['clip'])) for c in clips)

def concat_copy():
    lst = f'{AN}/concat_list.txt'
    if os.path.exists(tmp):
        os.remove(tmp)
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
    # per-segment keyframe rounding accumulates a little drift; only GROSS
    # mismatch (broken timestamps / missing streams) triggers re-encode
    tol = max(3.0, expected * 0.025)
    if abs(d - expected) > tol:      # broken timestamps -> re-encode fallback
        print(f'COPY_CONCAT_BAD dur={d:.1f} expected={expected:.1f} tol={tol:.1f}; re-encoding')
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
           'n_review_windows': len(review),
           'expected_s': round(expected, 2), 'duration_s': round(d, 2),
           'resolution': f"{v['width']}x{v['height']}", 'codec': v['codec_name'],
           'has_audio': a is not None, 'size_mb': round(size_mb, 2),
           'windows': [c['window'] for c in clips]},
          open(f'{AN}/full_video.json', 'w'), indent=1)
print(f"FULL_VIDEO {os.path.basename(FULL)}: {d:.1f}s (expected {expected:.1f}s) "
      f"{v['width']}x{v['height']} {v['codec_name']} audio={a is not None} {size_mb:.1f}MB [{method}]")
print('FULL_VIDEO_OK')
