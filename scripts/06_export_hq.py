"""Re-export GROUPED AHYEON SCENES clips at BEST QUALITY from source.

Replaces the ultrafast/CRF22 exports (user: 'quality of video format is bad').
- Same windows and filenames as output/analysis/export_plan.json (consistency
  with reports / contact sheet).
- Encoding: libx264 -preset medium -crf 16  + AAC 192k  (+faststart).
  CRF16/medium on a 720p 860kbps source is visually transparent; the encode
  is the LAST generation, preserving all source detail.
- Atomic writes (.tmp then rename) so interrupted runs can resume safely.
Output: output/clips/ahyeon/scene_XXX.mp4 (overwritten) + export_plan_hq.json
"""
import json, os, subprocess, sys, time

BASE = '/home/z/my-project/clipextractor'
VIDEO = f'{BASE}/output/analysis/normalized.mp4'
AN = f'{BASE}/output/analysis'
OUTDIR = f'{BASE}/output/clips/ahyeon'

plan = json.load(open(f'{AN}/export_plan.json'))['clips']

results = []
t0 = time.time()
for c in plan:
    a, b = c['window']
    out = f"{OUTDIR}/{c['clip']}"
    tmp = out.replace('.mp4', '.hq.tmp.mp4')
    dur = b - a
    if os.path.exists(out) and os.path.exists(out + '.hq.done') and os.path.getsize(out) > 100_000:
        print(f"SKIP {c['clip']} (already HQ)")
        results.append({**c, 'hq': True})
        continue
    if os.path.exists(tmp):
        os.remove(tmp)
    cmd = ['ffmpeg', '-y', '-loglevel', 'error', '-ss', f'{a:.3f}', '-i', VIDEO,
           '-t', f'{dur:.3f}',
           '-c:v', 'libx264', '-preset', 'medium', '-crf', '16',
           '-pix_fmt', 'yuv420p',
           '-c:a', 'aac', '-b:a', '192k',
           '-movflags', '+faststart', tmp]
    p = subprocess.run(cmd, capture_output=True, text=True)
    ok = p.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 100_000
    if ok:
        os.replace(tmp, out)
        open(out + '.hq.done', 'w').write('crf16 medium aac192k')
    else:
        print(f"FFMPEG_ERR {c['clip']}: {p.stderr[-300:]}")
    size_mb = os.path.getsize(out) / 1e6 if os.path.exists(out) else 0
    print(f"{c['clip']}: [{'OK' if ok else 'FAIL'}] {dur:5.1f}s  {size_mb:6.1f}MB  "
          f"({time.time()-t0:5.0f}s elapsed)")
    results.append({**c, 'hq': ok, 'size_mb': round(size_mb, 2)})

json.dump({'encoder': 'libx264 crf16 preset medium, aac 192k',
           'clips': results}, open(f'{AN}/export_plan_hq.json', 'w'), indent=1)
n_ok = sum(1 for r in results if r.get('hq'))
print(f'EXPORT_HQ_OK {n_ok}/{len(results)}')
sys.exit(0 if n_ok == len(results) else 1)
