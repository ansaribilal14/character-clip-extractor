"""Send deliverables to the user via Telegram bot API.

- sendVideo for clips <= 49MB; if larger, transcode to smaller and send.
- sendDocument for report files (timeline.json, matches.json, report.csv,
  report.html, WORKLOG.md) + clip contact sheet.
- Sends a summary message first (raw vs grouped timestamps).
"""
import os, json, subprocess, time, requests

TOKEN = os.environ.get('CCE_TG_TOKEN', 'REDACTED')
CHAT = int(os.environ.get('CCE_TG_CHAT', 'REDACTED'))
API = f'https://api.telegram.org/bot{TOKEN}'
BASE = os.environ.get('CCE_BASE', '/home/z/my-project/clipextractor')
TARGET = os.environ.get('CCE_TARGET', 'ahyeon')
DISP = TARGET.capitalize()
TKEY = f'peak_{TARGET}_cos'
OUTDIR = f'{BASE}/output/clips/{TARGET}'
REP = f'{BASE}/output/reports'
MAXB = 49 * 1024 * 1024

def tg(method, **data):
    for attempt in range(3):
        r = requests.post(f'{API}/{method}', data=data, timeout=180)
        j = r.json()
        if j.get('ok'):
            return j
        if j.get('parameters', {}).get('retry_after'):
            time.sleep(j['parameters']['retry_after'] + 1); continue
        print('TG_ERR', method, j); return j
    return {'ok': False}

def send_file(path, as_video=True, caption=''):
    size = os.path.getsize(path)
    if size > MAXB and as_video:
        small = path.replace('.mp4', '_small.mp4')
        subprocess.run(['ffmpeg', '-y', '-i', path, '-vf', 'scale=-2:480',
                        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '30',
                        '-c:a', 'aac', '-b:a', '96k', '-movflags', '+faststart', small],
                       capture_output=True)
        path, as_video = small, True
    with open(path, 'rb') as f:
        m = 'sendVideo' if as_video else 'sendDocument'
        files = {'video' if as_video else 'document': (os.path.basename(path), f)}
        r = requests.post(f'{API}/{m}', data={'chat_id': CHAT, 'caption': caption[:1000],
                                              'supports_streaming': 'true'},
                          files=files, timeout=600)
        j = r.json()
        if not j.get('ok'):
            print('SEND_ERR', os.path.basename(path), j)
        return j

grouped = json.load(open(f'{BASE}/output/analysis/grouped_scenes.json'))
raw = json.load(open(f'{BASE}/output/analysis/raw_visibility.json'))
qc = json.load(open(f'{BASE}/output/analysis/qc.json'))

def ts(sec):
    m, s = divmod(int(sec), 60)
    return f'{m:02d}:{s:02d}'

n_clips = qc['n_ok']
summary = (f"✅ {DISP} clip extraction complete (MODE B)\n"
           f"RAW {DISP.upper()} VISIBILITY: {len(raw['intervals'])} intervals, {raw['total_visible_s']:.0f}s total\n"
           f"GROUPED {DISP.upper()} SCENES: {len(grouped['scenes'])} scenes → {n_clips} clips (+5s padding)\n\n"
           + '\n'.join(f"{s['scene_id']}: {ts(s['start'])}–{ts(s['end'])} "
                       f"(span {s['span_s']:.0f}s, vis {s['raw_visible_s']:.0f}s, conf {s['confidence']:.2f})"
                       for s in grouped['scenes'][:20]))
tg('sendMessage', chat_id=CHAT, text=summary)

# clips as videos
for c in qc['results']:
    p = os.path.join(OUTDIR, c['clip'])
    if not c.get('exists') or not os.path.exists(p):
        continue
    scenes_txt = '+'.join(c['scenes'])
    send_file(p, True, f"▶ {c['clip']} | scenes: {scenes_txt} | {ts(c['window'][0])}–{ts(c['window'][1])} | peak cos {c.get(TKEY,'-')}")
    time.sleep(1)

# reports as documents
for fn in ['timeline.json', 'matches.json', 'report.csv', 'report.html', 'WORKLOG.md']:
    p = os.path.join(REP, fn)
    if os.path.exists(p):
        send_file(p, False, f'📄 {fn}')
        time.sleep(1)

sheet = f'{REP}/clip_contact_sheet.jpg'
if os.path.exists(sheet):
    send_file(sheet, False, '🖼 clip thumbnails contact sheet')

print('TELEGRAM_SEND_DONE')
