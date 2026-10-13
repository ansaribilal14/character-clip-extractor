"""Generate deliverable reports:
- timeline.json : RAW AHYEON VISIBILITY + GROUPED AHYEON SCENES + clips
- matches.json  : all face detections/matches (full detail)
- report.csv    : one row per grouped scene
- report.html   : human-readable report with thumbnails + both timestamp tables
"""
import json, os, html, csv, datetime

BASE = os.environ.get('CCE_BASE', '/home/z/my-project/clipextractor')
TARGET = os.environ.get('CCE_TARGET', 'ahyeon')
TKEY = f'{TARGET}_best_cos'
DISP = TARGET.capitalize()
VIDEO_ID = os.environ.get('CCE_VIDEO_ID', '9G3BYRKujo8')
VIDEO_URL = os.environ.get('CCE_VIDEO_URL', f'https://youtu.be/{VIDEO_ID}')
AN = f'{BASE}/output/analysis'
REP = f'{BASE}/output/reports'
os.makedirs(REP, exist_ok=True)

shots_doc = json.load(open(f'{AN}/shots.json'))
raw = json.load(open(f'{AN}/raw_visibility.json'))
grouped = json.load(open(f'{AN}/grouped_scenes.json'))
plan = json.load(open(f'{AN}/export_plan.json'))
qc = json.load(open(f'{AN}/qc.json'))
audio = json.load(open(f'{AN}/audio_activity.json'))
cap_doc = json.load(open(f'{AN}/captions.json')) if os.path.exists(f'{AN}/captions.json') else None
recs = []
for l in open(f'{AN}/analysis.jsonl'):
    l = l.strip()
    if not l:
        continue
    try:
        recs.append(json.loads(l))
    except json.JSONDecodeError:
        continue          # torn line from a mid-write kill — skip it
refs = json.load(open(f'{BASE}/references/refs_summary.json'))

def ts(sec):
    m, s = divmod(int(sec), 60)
    return f'{m:02d}:{s:02d}'

# ---------- timeline.json ----------
timeline = {
    'video': {'youtube_id': VIDEO_ID, 'url': VIDEO_URL,
              'duration_s': shots_doc['video_duration'],
              'normalized_file': 'output/analysis/normalized.mp4'},
    'generated_at_utc': datetime.datetime.utcnow().isoformat() + 'Z',
    'mode': f'B ({DISP} Scenes)',
    'sampling_fps': 2.0,
    'match_threshold_cos': 0.42,
    'padding_s': plan['pad_s'],
    f'raw_{TARGET}_visibility': [
        {'start': ts(i['start']), 'end': ts(i['end']),
         'start_s': i['start'], 'end_s': i['end'],
         'duration_s': i['duration'], 'mean_cos': i['mean_cos'], 'max_cos': i['max_cos'],
         'shots': i['shots']}
        for i in raw['intervals']],
    'raw_total_visible_s': raw['total_visible_s'],
    f'grouped_{TARGET}_scenes': [
        {'scene_id': s['scene_id'], 'start': ts(s['start']), 'end': ts(s['end']),
         'start_s': s['start'], 'end_s': s['end'], 'span_s': s['span_s'],
         'raw_visible_s': s['raw_visible_s'], 'visibility_ratio': s['visibility_ratio'],
         'n_raw_intervals': s['n_raw_intervals'],
         'members_present': s['members_present'],
         'speech_seconds': s['speech_seconds'], 'confidence': s['confidence']}
        for s in grouped['scenes']],
    'clips': qc['results'],
    'notes': {
        'audio_evidence': 'energy-based voice activity only; no speaker identity '
                          'or dialogue understanding claimed',
        'vlm': 'not available in CPU-constrained MVP',
        'captions': ('available, ' + str(cap_doc['n_segments']) + ' segments')
                     if cap_doc and cap_doc.get('available') else 'not available',
        'shot_vs_scene': 'shots = PySceneDetect visual cuts; scenes = continuity layer '
                         'merging Ahyeon visibility intervals with multi-evidence scoring',
    },
    'scene_merge_params': grouped['params'],
    'merge_trace': grouped['merge_trace'],
}
json.dump(timeline, open(f'{REP}/timeline.json', 'w'), indent=1)

# ---------- matches.json ----------
matches = {
    'members': {m: {'n_refs': refs['members'][m]['n_refs'],
                    'refs': refs['members'][m]['refs']}
                for m in refs['members']},
    'frame_matches': recs,
    'stats': {
        'frames_sampled': len(recs),
        'frames_with_' + TARGET: sum(1 for r in recs if r.get(TKEY) is not None),
        'total_face_instances': sum(r['n_faces'] for r in recs),
        'per_member_frames': {m: sum(1 for r in recs if any(f['member'] == m for f in r['faces']))
                              for m in refs['members']},
    },
}
json.dump(matches, open(f'{REP}/matches.json', 'w'), indent=1)

# ---------- report.csv ----------
with open(f'{REP}/report.csv', 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['scene_id', 'start', 'end', 'start_s', 'end_s', 'span_s',
                'raw_visible_s', 'visibility_ratio', 'n_raw_intervals',
                'members_present', 'speech_seconds', 'confidence',
                'clip_file', 'clip_exists', 'clip_duration_s', 'clip_size_mb'])
    for s in grouped['scenes']:
        clip = next((c for c in qc['results'] if s['scene_id'] in c['scenes']), None)
        w.writerow([s['scene_id'], ts(s['start']), ts(s['end']),
                    s['start'], s['end'], s['span_s'], s['raw_visible_s'],
                    s['visibility_ratio'], s['n_raw_intervals'],
                    ';'.join(s['members_present']), s['speech_seconds'], s['confidence'],
                    clip['clip'] if clip else '', clip.get('exists', False) if clip else False,
                    clip.get('duration', '') if clip else '', clip.get('size_mb', '') if clip else ''])

# ---------- report.html ----------
def table_rows(intervals, grouped_mode=False):
    rows = []
    for i in intervals:
        if grouped_mode:
            rows.append(f"<tr><td><b>{i['scene_id']}</b></td><td>{i['start']}–{i['end']}</td>"
                        f"<td>{i['span_s']:.1f}s</td><td>{i['raw_visible_s']:.1f}s ({i['visibility_ratio']*100:.0f}%)</td>"
                        f"<td>{i['n_raw_intervals']}</td><td>{html.escape(', '.join(i['members_present']))}</td>"
                        f"<td>{i['speech_seconds']:.0f}s</td><td>{i['confidence']:.2f}</td></tr>")
        else:
            rows.append(f"<tr><td>{i['start']}–{i['end']}</td><td>{i['duration_s']:.1f}s</td>"
                        f"<td>{i['mean_cos']:.3f}</td><td>{i['max_cos']:.3f}</td>"
                        f"<td>{','.join(map(str, i['shots']))}</td></tr>")
    return '\n'.join(rows)

clip_cards = []
for c in qc['results']:
    th = c.get('thumbnail') or ''
    p = f'../clips/{TARGET}/{th}' if th else ''
    img = f'<img src="{p}" width="240">' if th and os.path.exists(f'{BASE}/output/clips/{TARGET}/{th}') else '<i>no thumb</i>'
    clip_cards.append(f'<div class="card">{img}<div><b>{c["clip"]}</b><br>'
                      f'{ts(c["window"][0])}–{ts(c["window"][1])} · {c.get("duration","?")}s · '
                      f'{c.get("resolution","?")} · {c.get("size_mb","?")}MB<br>'
                      f'peak {DISP} cos: {c.get(f"peak_{TARGET}_cos","-")}</div></div>')

html_doc = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>{DISP} Scenes — MODE B</title>
<style>
body{{font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:1080px;margin:24px auto;padding:0 16px;color:#1a1a2e}}
h1{{border-bottom:3px solid #4f46e5;padding-bottom:8px}} h2{{color:#4f46e5;margin-top:32px}}
table{{border-collapse:collapse;width:100%;font-size:14px}} td,th{{border:1px solid #d1d5db;padding:5px 9px;text-align:left}}
th{{background:#eef2ff}} tr:nth-child(even){{background:#fafafa}}
.card{{display:inline-flex;gap:10px;border:1px solid #e5e7eb;border-radius:8px;padding:8px;margin:6px;align-items:center;background:#fff}}
.note{{background:#fefce8;border-left:4px solid #eab308;padding:8px 12px;font-size:14px}}
.meta{{color:#6b7280;font-size:13px}}
.kpi{{display:inline-block;background:#eef2ff;border-radius:8px;padding:8px 14px;margin:4px;font-size:14px}}
</style></head><body>
<h1>Character-Centric Clip Extraction — {DISP} (MODE B)</h1>
<p class="meta">Video: <a href="{VIDEO_URL}">{VIDEO_ID}</a> ·
generated {timeline['generated_at_utc']} · CPU-only pipeline (InsightFace buffalo_l @ 2fps sampling)</p>
<div>
<span class="kpi">Video: {ts(shots_doc['video_duration'])}</span>
<span class="kpi">Shots: {len(shots_doc['shots'])}</span>
<span class="kpi">RAW visibility: {len(raw['intervals'])} intervals · {raw['total_visible_s']:.0f}s</span>
<span class="kpi">GROUPED scenes: {len(grouped['scenes'])}</span>
<span class="kpi">Clips exported: {qc['n_ok']}/{qc['n_total']}</span>
</div>
<h2>1. RAW {DISP.upper()} VISIBILITY</h2>
<p class="meta">Direct face-recognition visibility (2fps sampling, ≤0.5s miss bridging, ≥1.0s minimum duration).
This is what a naive "cut when face appears, cut when face disappears" pipeline would produce.</p>
<table><tr><th>Interval</th><th>Duration</th><th>mean cos</th><th>max cos</th><th>Shots</th></tr>
{table_rows(timeline[f'raw_{TARGET}_visibility'])}</table>
<h2>2. GROUPED {DISP.upper()} SCENES</h2>
<p class="meta">Scene-continuity layer output: raw intervals merged when temporal gap, shot adjacency,
audio activity, captions, member continuity and visual stability indicate one continuous conversation.
Padding ±5s applied at export.</p>
<table><tr><th>Scene</th><th>Interval</th><th>Span</th><th>{DISP} visible</th><th>#raw</th><th>Members present</th><th>Speech</th><th>Conf.</th></tr>
{table_rows(timeline[f'grouped_{TARGET}_scenes'], True)}</table>
<div class="note"><b>Evidence limitations (honest reporting):</b> {html.escape(timeline['notes']['audio_evidence'])}.
VLM: {html.escape(timeline['notes']['vlm'])}. Captions: {html.escape(timeline['notes']['captions'])}.</div>
<h2>3. Exported clips</h2>
{''.join(clip_cards) or '<i>none</i>'}
<h2>4. Pipeline</h2>
<ol class="meta">
<li>yt-dlp/ytagent download → 00 normalize 720p H.264</li>
<li>01 PySceneDetect ContentDetector → {len(shots_doc['shots'])} shots</li>
<li>02 InsightFace detect+embed @2fps, match vs member centroids (cos ≥ 0.42)</li>
<li>03 RAW visibility (miss-bridging ≤0.5s, min 1.0s)</li>
<li>04 silencedetect voice activity + captions attempt</li>
<li>05 scene continuity layer (multi-evidence merge, threshold 3.0, hard blocks: gap&gt;12s / &gt;2 shot cuts)</li>
<li>06 export ±5s padding (merged overlapping windows) → 07 ffprobe QC → 08 reports</li>
</ol>
</body></html>"""
open(f'{REP}/report.html', 'w').write(html_doc)

# ---------- WORKLOG.md ----------
wl = []
wl.append(f'# WORKLOG — {DISP} Scene Extraction (MODE B)\n')
wl.append(f"Video: {VIDEO_URL}")
wl.append(f"Generated: {timeline['generated_at_utc']}\n")
wl.append('## Pipeline stages')
wl.append('1. ytagent download (BGutil POT) — first download was A/V-truncated (video 137s/audio 494s), '
          'detected by stream-parity check, re-downloaded full 23:07 (172MB)')
wl.append('2. Lossless remux -> normalized.mp4 (720p h264/aac)')
wl.append(f"3. PySceneDetect ContentDetector: {len(shots_doc['shots'])} shots (mean {sum(s['duration'] for s in shots_doc['shots'])/len(shots_doc['shots']):.2f}s)")
wl.append('4. InsightFace buffalo_l @2fps (cos>=0.42 vs member centroids)')
wl.append('5. RAW visibility: miss-bridging 0.5s, min duration 1.0s (49 micro-intervals dropped)')
wl.append('6. Voice activity: ffmpeg silencedetect -30dB — continuous BGM makes energy evidence weak '
          '(1383.7/1387.4s "active"); NOT used as speaker identity')
wl.append(f"7. Captions: YouTube captions {'available' if cap_doc and cap_doc.get('available') else 'UNAVAILABLE (bot-check on metadata endpoints)'}")
wl.append('8. Scene continuity layer: merge threshold 3.0 pts; evidence = gap, shot adjacency, speech span, '
          'caption span, member continuity, position stability; hard blocks gap>12s or >2 shot cuts; VLM unavailable\n')
wl.append(f'\n## RAW {DISP.upper()} VISIBILITY ({len(raw["intervals"])} intervals, {raw["total_visible_s"]:.1f}s)')
for i in timeline[f'raw_{TARGET}_visibility']:
    wl.append(f"- {i['start']}-{i['end']} ({i['duration_s']:.1f}s) cos {i['mean_cos']:.2f}/{i['max_cos']:.2f} shots {','.join(map(str,i['shots']))}")
wl.append(f'\n## GROUPED {DISP.upper()} SCENES ({len(grouped["scenes"])} scenes)')
for s in timeline[f'grouped_{TARGET}_scenes']:
    wl.append(f"- {s['scene_id']}: {s['start']}-{s['end']} span {s['span_s']:.1f}s visible {s['raw_visible_s']:.1f}s "
              f"({s['visibility_ratio']*100:.0f}%) members [{', '.join(s['members_present'])}] conf {s['confidence']:.2f}")
wl.append('\n## Exported clips (QC)')
for c in qc['results']:
    wl.append(f"- {c['clip']}: {c['window'][0]:.1f}-{c['window'][1]:.1f}s dur {c.get('duration','?')}s "
              f"{c.get('resolution','?')} {c.get('size_mb','?')}MB peak cos {c.get(f'peak_{TARGET}_cos','-')} scenes {','.join(c['scenes'])}")
wl.append('\n## Known limitations / honest notes')
wl.append(f'- Known weakest matches and FN risks are documented per run; side-profile/backlit/blurry '
          f'{DISP} moments under 0.42 cos or between 2fps samples can be missed')
wl.append('- Merge decisions for scenes 005_grp (8.5s gap) and 010_grp (7.4s gap) relied on shot adjacency + '
          'member continuity + position stability; visually verified continuous')
wl.append('- Voice-activity evidence is nearly constant due to BGM; it did not dominate merge decisions')
open(f'{REP}/WORKLOG.md', 'w').write('\n'.join(wl))

print(f'REPORTS_OK timeline.json matches.json report.csv report.html WORKLOG.md '
      f'(raw={len(raw["intervals"])}, scenes={len(grouped["scenes"])}, clips={qc["n_ok"]})')
