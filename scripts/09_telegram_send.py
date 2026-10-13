"""Deliver per-workspace artifacts through the ONE delivery path.

- Summary message first (RAW visibility vs GROUPED scenes timestamps).
- FULL per-episode video: <=49MB -> Telegram document; larger -> uploaded to
  storage.to and the download link is messaged (never split, never
  transcoded just for delivery).
- Report files as Telegram documents.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from character_clip_extractor import delivery  # noqa: E402

BASE = os.environ.get('CCE_BASE', '/home/z/my-project/clipextractor')
TARGET = os.environ.get('CCE_TARGET', 'ahyeon')
DISP = TARGET.capitalize()
TKEY = f'peak_{TARGET}_cos'
OUTDIR = f'{BASE}/output/clips/{TARGET}'
REP = f'{BASE}/output/reports'


def ts(sec):
    m, s = divmod(int(sec), 60)
    return f'{m:02d}:{s:02d}'


grouped = json.load(open(f'{BASE}/output/analysis/grouped_scenes.json'))
raw = json.load(open(f'{BASE}/output/analysis/raw_visibility.json'))
qc = json.load(open(f'{BASE}/output/analysis/qc.json'))
fv = json.load(open(f'{BASE}/output/analysis/full_video.json'))

summary = (f"✅ {DISP} extraction complete\n"
           f"RAW {DISP.upper()} VISIBILITY: {len(raw['intervals'])} intervals, "
           f"{raw['total_visible_s']:.0f}s total\n"
           f"GROUPED {DISP.upper()} SCENES: {len(grouped['scenes'])} scenes → "
           f"{qc['n_ok']} merged windows (+5s padding)\n"
           f"FULL EPISODE VIDEO: {fv['full_video']} — {fv['duration_s']:.0f}s, "
           f"{fv['resolution']}, {fv['size_mb']:.0f}MB\n\n"
           + '\n'.join(f"{s['scene_id']}: {ts(s['start'])}–{ts(s['end'])} "
                       f"(span {s['span_s']:.0f}s, vis {s['raw_visible_s']:.0f}s, "
                       f"conf {s['confidence']:.2f})"
                       for s in grouped['scenes'][:20]))
delivery._tg('sendMessage', {'chat_id': delivery.TG_CHAT, 'text': summary})

# the FULL per-episode video — same delivery path as everything else
full_path = os.path.join(OUTDIR, fv['full_video'])
if os.path.exists(full_path):
    delivery.deliver_auto(full_path,
                          caption=f'{DISP} FULL episode video (all scenes, '
                                  f'no cuts)', keep=True)

for fn in ['timeline.json', 'matches.json', 'report.csv', 'report.html',
           'WORKLOG.md']:
    p = os.path.join(REP, fn)
    if os.path.exists(p) and os.path.getsize(p) <= delivery.SAFE_TG_BYTES:
        delivery.send_document(p, f'📄 {fn}')

print('TELEGRAM_SEND_DONE')
