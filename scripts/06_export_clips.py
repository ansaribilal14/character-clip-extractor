"""Export GROUPED AHYEON SCENES as clips with configurable padding (default 5s).

- Padding clamped to [0, video_duration]; padded windows that overlap are merged.
- Accurate export via re-encode (libx264 veryfast) with input seek.
- Thumbnail = best Ahyeon frame (max cos) inside clip.
Output: output/clips/ahyeon/scene_XXX.mp4 + scene_XXX.jpg
        output/analysis/export_plan.json
"""
import json, os, subprocess
import numpy as np, cv2

BASE = os.environ.get('CCE_BASE', '/home/z/my-project/clipextractor')
TARGET = os.environ.get('CCE_TARGET', 'ahyeon')
TKEY = f'{TARGET}_best_cos'
VIDEO = f'{BASE}/output/analysis/normalized.mp4'
GROUPED = f'{BASE}/output/analysis/grouped_scenes.json'
OUTDIR = f'{BASE}/output/clips/{TARGET}'
AN = f'{BASE}/output/analysis'
PAD = float(os.environ.get('CCE_PAD', '5.0'))
MIN_CLIP_S = 1.0
os.makedirs(OUTDIR, exist_ok=True)

dur = float(json.loads(subprocess.check_output(
    ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', VIDEO]
))['format']['duration'])

grouped = json.load(open(GROUPED))
scenes = [s for s in grouped['scenes'] if s['span_s'] >= MIN_CLIP_S]

# padded windows, merged if overlapping
wins = []
for s in scenes:
    a = max(0.0, s['start'] - PAD)
    b = min(dur, s['end'] + PAD)
    if wins and a <= wins[-1][1] + 0.5:
        wins[-1][1] = max(wins[-1][1], b)
        wins[-1][2].append(s['scene_id'])
    else:
        wins.append([a, b, [s['scene_id']]])

recs = [json.loads(l) for l in open(f'{AN}/analysis.jsonl')]
plan = []
for i, (a, b, sids) in enumerate(wins):
    name = '_'.join(sids)
    out = f'{OUTDIR}/{sids[0].replace("scene_", "scene_")}.mp4'
    if len(sids) > 1:
        out = f'{OUTDIR}/scene_{i+1:03d}_grp.mp4'
    cmd = ['ffmpeg', '-y', '-ss', f'{a:.3f}', '-i', VIDEO, '-t', f'{b-a:.3f}',
           '-c:v', 'libx264', '-preset', 'medium', '-crf', '16',
           '-pix_fmt', 'yuv420p',
           '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', out]
    p = subprocess.run(cmd, capture_output=True, text=True) if not (
        os.path.exists(out) and os.path.getsize(out) > 100_000) else None
    ok = (p is None or p.returncode == 0) and os.path.exists(out) and os.path.getsize(out) > 100_000

    # peak Ahyeon frame
    best_t, best_c = None, -1
    for r in recs:
        if a <= r['t'] <= b and r.get(TKEY) is not None and r[TKEY] > best_c:
            best_c, best_t = r[TKEY], r['t']
    thumb = None
    if best_t is not None:
        cap = cv2.VideoCapture(VIDEO)
        cap.set(cv2.CAP_PROP_POS_MSEC, best_t * 1000)
        okf, frame = cap.read()
        cap.release()
        if okf:
            h, w = frame.shape[:2]
            th = cv2.resize(frame, (480, int(480 * h / w)))
            thumb = out.replace('.mp4', '.jpg')
            cv2.imwrite(thumb, th, [cv2.IMWRITE_JPEG_QUALITY, 88])

    plan.append({'clip': os.path.basename(out), 'window': [round(a, 2), round(b, 2)],
                 'scenes': sids, 'export_ok': ok,
                 f'peak_{TARGET}_t': round(best_t, 2) if best_t is not None else None,
                 f'peak_{TARGET}_cos': round(best_c, 4) if best_c >= 0 else None,
                 'thumbnail': os.path.basename(thumb) if thumb else None})
    print(f'{os.path.basename(out)}: [{"OK" if ok else "FAIL"}] {a:.1f}-{b:.1f}s peak@{best_t} cos={best_c:.3f}' if best_c >= 0
          else f'{os.path.basename(out)}: [{"OK" if ok else "FAIL"}] {a:.1f}-{b:.1f}s NO_{TARGET.upper()}_FRAME')

with open(f'{AN}/export_plan.json', 'w') as f:
    json.dump({'pad_s': PAD, 'video_duration': round(dur, 2), 'clips': plan}, f, indent=1)
print(f'EXPORT_OK clips={sum(1 for p in plan if p["export_ok"])}/{len(plan)}')
