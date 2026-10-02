"""Scene continuity layer: merge RAW AHYEON VISIBILITY intervals into GROUPED SCENES.

Evidence signals (each contributes points to a merge decision):
  E1 temporal gap          : small gap -> strong evidence
  E2 shot adjacency        : fewer intervening shot boundaries -> stronger
  E3 audio continuity      : speech activity spans the gap (energy VAD only,
                             NOT speaker identity)
  E4 caption continuity    : a caption segment spans/covers the gap (if captions
                             available; may be absent in MVP)
  E5 member continuity     : same set of other members visible on both sides
  E6 visual/pos similarity : Ahyeon bbox center/size stable across gap
  E7 embedding similarity  : mean Ahyeon embedding cosine across gap
(VLM affordance NOT available in this CPU-constrained MVP; recorded as null.)

HARD BLOCKS: gap > MAX_GAP_S or intervening shot boundaries > MAX_SHOTS.
Merge if evidence score >= MERGE_THRESHOLD.

Output: output/analysis/grouped_scenes.json
"""
import json, os
import numpy as np

BASE = os.environ.get('CCE_BASE', '/home/z/my-project/clipextractor')
TARGET = os.environ.get('CCE_TARGET', 'ahyeon')
TKEY = f'{TARGET}_best_cos'
AN = f'{BASE}/output/analysis'
OUT = f'{AN}/grouped_scenes.json'

MERGE_THRESHOLD = 3.0
MAX_GAP_S = 12.0
MAX_SHOTS = 2
SAMPLE_STEP = 0.5

raw = json.load(open(f'{AN}/raw_visibility.json'))
shots_doc = json.load(open(f'{AN}/shots.json'))
shots = shots_doc['shots']
# actual normalized-video width (position stats must be resolution-aware)
def _vw():
    try:
        import subprocess
        out = subprocess.check_output(['ffprobe', '-v', 'quiet', '-print_format', 'json',
                                       '-select_streams', 'v:0', '-show_streams',
                                       f'{AN}/normalized.mp4'], text=True)
        return float(json.loads(out)['streams'][0]['width'])
    except Exception:
        return 1280.0
VW = _vw()
audio = json.load(open(f'{AN}/audio_activity.json')) if os.path.exists(f'{AN}/audio_activity.json') else None
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

def shot_starts_between(a, b):
    return sum(1 for s in shots if a['end'] < s['start'] < b['start'])

def speech_spans(a, b):
    if not audio:
        return False, 0.0
    gap0, gap1 = a['end'], b['start']
    if gap1 <= gap0:
        return False, 0.0
    ov = 0.0
    for s, e in audio['speech_intervals']:
        ov += max(0.0, min(e, gap1) - max(s, gap0))
    return ov > 0.2 * (gap1 - gap0), ov

def caption_spans(a, b):
    if not cap_doc:
        return False
    gap0, gap1 = a['end'] - 1.0, b['start'] + 1.0
    for seg in cap_doc.get('segments', []):
        if seg['start'] <= gap0 and seg['end'] >= gap1 - 0.5:
            return True
    return False

def side_stats(ivl, side):
    """Ahyeon stats in samples within `side` seconds of interval edge."""
    lo = ivl['start'] if side == 'left' else max(0.0, ivl['end'] - 3.0)
    hi = min(lo + 3.0, ivl['end']) if side == 'left' else ivl['end']
    centers, sizes, embs, others = [], [], [], set()
    for r in recs:
        if not (lo <= r['t'] <= hi):
            continue
        for f in r['faces']:
            if f['member'] == TARGET:
                x1, y1, x2, y2 = f['bbox']
                centers.append(((x1 + x2) / 2, (y1 + y2) / 2))
                sizes.append(y2 - y1)
            elif f['member'] != 'unknown':
                others.add(f['member'])
    return centers, sizes, others, VW

def merge_evidence(a, b):
    ev = {}
    gap = b['start'] - a['end']
    ev['gap_s'] = round(gap, 2)
    if gap > MAX_GAP_S:
        return None, {'hard': 'gap_too_large', 'gap_s': round(gap, 2)}
    nshots = shot_starts_between(a, b)
    ev['intervening_shots'] = nshots
    if nshots > MAX_SHOTS:
        return None, {'hard': 'too_many_shot_cuts', 'n': nshots}

    score = 0.0
    if gap <= 1.5: score += 2.0; ev['e1_gap'] = 2.0
    elif gap <= 3.0: score += 1.5; ev['e1_gap'] = 1.5
    elif gap <= 6.0: score += 1.0; ev['e1_gap'] = 1.0
    else: score += 0.5; ev['e1_gap'] = 0.5

    if nshots == 0: score += 1.0; ev['e2_shots'] = 1.0
    elif nshots == 1: score += 0.5; ev['e2_shots'] = 0.5
    else: ev['e2_shots'] = 0.0

    sp, sp_s = speech_spans(a, b)
    if sp: score += 1.0; ev['e3_speech_span'] = 1.0
    else: ev['e3_speech_span'] = 0.0
    ev['speech_in_gap_s'] = round(sp_s, 2)

    cap = caption_spans(a, b)
    if cap: score += 1.0
    ev['e4_caption_span'] = 1.0 if cap else 0.0

    lc, ls, lo, W = side_stats(a, 'left')
    rc, rs, ro, _ = side_stats(b, 'right')
    same_members = bool(lo & ro)
    if same_members: score += 1.0
    ev['e5_same_members'] = 1.0 if same_members else 0.0
    ev['members_left'] = sorted(lo); ev['members_right'] = sorted(ro)

    if lc and rc:
        dx = abs(np.mean([c[0] for c in lc]) - np.mean([c[0] for c in rc])) / W
        dy = abs(np.mean([c[1] for c in lc]) - np.mean([c[1] for c in rc])) / (W * 9 / 16)
        ratio = (np.mean(ls) / np.mean(rs)) if (ls and rs) else 2.0
        pos_ok = dx < 0.15 and dy < 0.15 and 0.6 < ratio < 1.6
        if pos_ok: score += 1.0
        ev['e6_position'] = 1.0 if pos_ok else 0.0
        ev['pos_dx'] = round(float(dx), 3); ev['pos_ratio'] = round(float(ratio), 3)
    else:
        ev['e6_position'] = 0.0

    ev['e7_embedding'] = None  # VLM/embedding-across-gap: see note
    merged = score >= MERGE_THRESHOLD
    ev['score'] = round(score, 2)
    ev['merged'] = merged
    return merged, ev

# sequential grouping
intervals = sorted(raw['intervals'], key=lambda x: x['start'])
scenes = []
cur = None
trace = []
for ivl in intervals:
    if cur is None:
        cur = {'intervals': [ivl], 'start': ivl['start'], 'end': ivl['end']}
        continue
    ok, ev = merge_evidence(cur['intervals'][-1], ivl)
    if ok:
        cur['intervals'].append(ivl)
        cur['end'] = ivl['end']
        trace.append({'between': [round(cur['intervals'][0]['start'], 1), round(ivl['start'], 1)], **ev})
    else:
        scenes.append(cur)
        cur = {'intervals': [ivl], 'start': ivl['start'], 'end': ivl['end']}
        trace.append({'between': [round(scenes[-1]['intervals'][-1]['end'], 1), round(ivl['start'], 1)], **ev})
if cur:
    scenes.append(cur)

# build scene records with participation stats
out_scenes = []
for i, sc in enumerate(scenes):
    ivls = sc['intervals']
    visible = sum(x['duration'] for x in ivls)
    span = sc['end'] - sc['start']
    # samples inside scene
    members = {}
    ah_cos = []
    n_ah_samples = 0
    n_samples = 0
    for r in recs:
        if sc['start'] - 1e-6 <= r['t'] <= sc['end'] + 1e-6:
            n_samples += 1
            seen = set()
            for f in r['faces']:
                if f['member'] != 'unknown':
                    members.setdefault(f['member'], 0)
                    seen.add(f['member'])
            for m in seen:
                members[m] += 1
            if r.get(TKEY) is not None:
                n_ah_samples += 1
                ah_cos.append(r[TKEY])
    # speech seconds inside scene
    sp_s = 0.0
    if audio:
        for s, e in audio['speech_intervals']:
            sp_s += max(0.0, min(e, sc['end']) - max(s, sc['start']))
    out_scenes.append({
        'scene_id': f'scene_{i+1:03d}',
        'start': round(sc['start'], 2), 'end': round(sc['end'], 2),
        'span_s': round(span, 2),
        'raw_visible_s': round(visible, 2),
        'visibility_ratio': round(visible / span, 3) if span > 0 else 0,
        'n_raw_intervals': len(ivls),
        'raw_intervals': [{k: x[k] for k in ('start', 'end', 'duration', 'mean_cos', 'max_cos', 'shots')} for x in ivls],
        'n_samples': n_samples, f'n_{TARGET}_samples': n_ah_samples,
        f'{TARGET}_mean_cos': round(sum(ah_cos) / len(ah_cos), 4) if ah_cos else None,
        'members_present': {m: v for m, v in sorted(members.items())},
        'speech_seconds': round(sp_s, 1),
        'confidence': round(min(1.0, (sum(x['max_cos'] for x in ivls) / len(ivls)) * 0.7
                                + min(1.0, visible / max(span, 1e-6)) * 0.3), 3),
    })

with open(OUT, 'w') as f:
    json.dump({
        'params': {'merge_threshold': MERGE_THRESHOLD, 'max_gap_s': MAX_GAP_S,
                   'max_intervening_shots': MAX_SHOTS},
        'limitation_vlm': 'VLM affordance not available in CPU-constrained MVP',
        'limitation_audio': 'audio evidence is energy-based voice activity only; '
                            'no speaker identity or dialogue understanding claimed',
        'scenes': out_scenes,
        'merge_trace': trace,
    }, f, indent=1)

print(f'GROUPED scenes={len(out_scenes)} from {len(intervals)} raw intervals')
for s in out_scenes:
    print(f"  {s['scene_id']}: {s['start']:>7.1f}-{s['end']:>7.1f} span={s['span_s']:>6.1f}s "
          f"vis={s['raw_visible_s']:>5.1f}s ratio={s['visibility_ratio']:.2f} conf={s['confidence']}")
print('GROUP_SCENES_OK')
