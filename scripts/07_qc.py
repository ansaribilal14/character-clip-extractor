"""QC exported clips: ffprobe every clip, compare duration vs plan window,
generate thumbnail contact sheet.
Output: output/analysis/qc.json + output/reports/clip_contact_sheet.jpg
"""
import json, os, subprocess
import cv2, numpy as np

BASE = os.environ.get('CCE_BASE', '/home/z/my-project/clipextractor')
TARGET = os.environ.get('CCE_TARGET', 'ahyeon')
PLAN = f'{BASE}/output/analysis/export_plan.json'
OUTDIR = f'{BASE}/output/clips/{TARGET}'
QC = f'{BASE}/output/analysis/qc.json'

plan = json.load(open(PLAN))
results = []
for c in plan['clips']:
    p = os.path.join(OUTDIR, c['clip'])
    if not os.path.exists(p):
        results.append({**c, 'exists': False}); continue
    info = json.loads(subprocess.check_output(
        ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', p]))
    v = next(s for s in info['streams'] if s['codec_type'] == 'video')
    a = next((s for s in info['streams'] if s['codec_type'] == 'audio'), None)
    d = float(info['format']['duration'])
    exp = c['window'][1] - c['window'][0]
    results.append({**c, 'exists': True, 'duration': round(d, 2),
                    'expected': round(exp, 2), 'dur_delta': round(d - exp, 2),
                    'resolution': f"{v['width']}x{v['height']}", 'codec': v['codec_name'],
                    'has_audio': a is not None, 'size_mb': round(os.path.getsize(p)/1e6, 1)})

# contact sheet of clip thumbnails
thumbs = [os.path.join(OUTDIR, r['thumbnail']) for r in results
          if r.get('thumbnail') and os.path.exists(os.path.join(OUTDIR, r['thumbnail']))]
if thumbs:
    cols = 4
    rows = (len(thumbs) + cols - 1) // cols
    cw, ch = 320, 180
    sheet = np.full((rows*ch, cols*cw, 3), 245, np.uint8)
    for i, t in enumerate(thumbs):
        img = cv2.imread(t)
        if img is None: continue
        img = cv2.resize(img, (cw, ch))
        r, col = divmod(i, cols)
        sheet[r*ch:(r+1)*ch, col*cw:(col+1)*cw] = img
    os.makedirs(f'{BASE}/output/reports', exist_ok=True)
    cv2.imwrite(f'{BASE}/output/reports/clip_contact_sheet.jpg', sheet,
                [cv2.IMWRITE_JPEG_QUALITY, 85])

ok = [r for r in results if r.get('exists') and abs(r['dur_delta']) <= 1.5 and r['has_audio']]
with open(QC, 'w') as f:
    json.dump({'results': results, 'n_ok': len(ok), 'n_total': len(results)}, f, indent=1)
for r in results:
    if r.get('exists'):
        print(f"{r['clip']}: dur={r['duration']}s (exp {r['expected']}s, d={r['dur_delta']:+.2f}) "
              f"{r['resolution']} {r['codec']} audio={r['has_audio']} {r['size_mb']}MB")
    else:
        print(f"{r['clip']}: MISSING")
print(f'QC_OK {len(ok)}/{len(results)} clips pass')
