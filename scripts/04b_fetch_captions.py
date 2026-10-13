"""Fetch YouTube captions (auto or manual) as lightweight transcript.

Tries ytagent's own environment first (same plugin stack), then plain yt-dlp.
Converts VTT -> segments JSON: [{start, end, text}]
Output: output/analysis/captions.json  (or CAPTIONS_UNAVAILABLE)
"""
import json, os, subprocess, glob, re

BASE = os.environ.get('CCE_BASE', '/home/z/my-project/clipextractor')
VID = os.environ.get('CCE_VIDEO_ID', '9G3BYRKujo8')
TMP = f'{BASE}/output/analysis/subs_tmp'
OUT = f'{BASE}/output/analysis/captions.json'
os.makedirs(TMP, exist_ok=True)

def try_fetch(label, extra_args):
    for f in glob.glob(f'{TMP}/*'):
        os.remove(f)
    cmd = ['python3', '-m', 'yt_dlp', '--skip-download', '--no-warnings',
           '--write-auto-subs', '--write-subs', '--sub-langs', 'en.*',
           '--sub-format', 'vtt/srt/best', '-o', f'{TMP}/cap'] + extra_args + \
          [f'https://www.youtube.com/watch?v={VID}']
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    files = glob.glob(f'{TMP}/cap*.vtt') + glob.glob(f'{TMP}/cap*.srt')
    print(f'{label}: rc={p.returncode} files={len(files)} '
          f'{(p.stderr or p.stdout).strip().splitlines()[-1][:120] if (p.stderr or p.stdout).strip() else ""}')
    return files[0] if files else None

def ts_to_s(ts):
    parts = ts.replace(',', '.').split(':')
    while len(parts) < 3:
        parts.insert(0, '0')
    h, m, s = parts
    return int(h) * 3600 + int(m) * 60 + float(s)

def parse_vtt(path):
    segs, cur_start, cur_end = [], None, None
    for line in open(path, encoding='utf-8', errors='ignore'):
        m = re.match(r'(\d[\d:,]+)\s*-->\s*(\d[\d:,]+)', line)
        if m:
            cur_start, cur_end = ts_to_s(m.group(1)), ts_to_s(m.group(2))
            continue
        txt = line.strip()
        if not txt or cur_start is None or '-->' in txt or txt.startswith(('WEBVTT', 'Kind:', 'Language:', 'NOTE')) or re.match(r'^\d+$', txt):
            continue
        txt = re.sub(r'<[^>]+>', '', txt)
        if segs and segs[-1]['text'] == txt:
            segs[-1]['end'] = cur_end
        elif segs and segs[-1]['text'].endswith(txt) and abs(segs[-1]['start'] - cur_start) < 5:
            continue  # rolling-window duplicate
        else:
            segs.append({'start': round(cur_start, 2), 'end': round(cur_end, 2), 'text': txt})
    return segs

picked = try_fetch('with-pot', ['--js-runtimes', 'node', '--extractor-args',
                   'youtube:player_skip=webpage,configs;player_client=android_vr,android,web;youtubepot-bgutilhttp:base_url=http://127.0.0.1:4416'])
if not picked:
    picked = try_fetch('plain', [])

if not picked:
    with open(OUT, 'w') as f:
        json.dump({'available': False, 'note': 'captions not fetchable (IP throttled)'}, f, indent=1)
    print('CAPTIONS_UNAVAILABLE')
else:
    segs = parse_vtt(picked)
    with open(OUT, 'w') as f:
        json.dump({'available': True, 'source': os.path.basename(picked),
                   'n_segments': len(segs), 'segments': segs}, f, indent=1)
    print(f'CAPTIONS_OK segments={len(segs)}')
