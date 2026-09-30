"""Derive RAW AHYEON VISIBILITY intervals from analysis.jsonl.

Bridges single-sample misses (max 1 sample = 0.5s gap) to tolerate flicker,
but does NOT cross shot boundaries with >1.0s no-visibility.

Output: output/analysis/raw_visibility.json
  {intervals: [{start, end, duration, n_samples, mean_cos, max_cos, shots: [ids]}]}
"""
import json, os

BASE = os.environ.get('CCE_BASE', '/home/z/my-project/clipextractor')
TARGET = os.environ.get('CCE_TARGET', 'ahyeon')
TKEY = f'{TARGET}_best_cos'
AN = f'{BASE}/output/analysis'
IN = f'{AN}/analysis.jsonl'
SHOTS = f'{AN}/shots.json'
OUT = f'{AN}/raw_visibility.json'
SAMPLE_STEP = 0.5
MAX_MISS = 1        # tolerate 1 consecutive missing sample inside an interval

shots = json.load(open(SHOTS))['shots']

def shot_of(t):
    for s in shots:
        if s['start'] - 1e-6 <= t < s['end'] + 1e-6:
            return s['shot_id']
    return shots[-1]['shot_id'] if shots else -1

recs = [json.loads(l) for l in open(IN)]
hits = []   # (t, cos) where target visible
for r in recs:
    if r.get(TKEY) is not None:
        hits.append((r['t'], r[TKEY]))

# build intervals: group hits, bridging <=MAX_MISS consecutive misses
intervals = []
if hits:
    cur = [hits[0]]
    miss = 0
    for t, c in hits[1:]:
        gap = t - cur[-1][0]
        if gap <= SAMPLE_STEP * (MAX_MISS + 1) + 1e-6:
            cur.append((t, c)); miss = 0
        else:
            cos_list = [c2 for _, c2 in cur]
            intervals.append({
                'start': cur[0][0], 'end': cur[-1][0],
                'duration': round(cur[-1][0] - cur[0][0], 3),
                'n_samples': len(cur),
                'mean_cos': round(sum(cos_list) / len(cos_list), 4),
                'max_cos': round(max(cos_list), 4),
                'shots': sorted({shot_of(tt) for tt, _ in cur}),
            })
            cur = [(t, c)]
    cos_list = [c2 for _, c2 in cur]
    intervals.append({
        'start': cur[0][0], 'end': cur[-1][0],
        'duration': round(cur[-1][0] - cur[0][0], 3),
        'n_samples': len(cur),
        'mean_cos': round(sum(cos_list) / len(cos_list), 4),
        'max_cos': round(max(cos_list), 4),
        'shots': sorted({shot_of(tt) for tt, _ in cur}),
    })

# drop micro-intervals (< 1.0s) as likely false positives
kept = [iv for iv in intervals if iv['duration'] >= 1.0]
dropped = [iv for iv in intervals if iv['duration'] < 1.0]

with open(OUT, 'w') as f:
    json.dump({'intervals': kept, 'dropped_micro': dropped,
               'total_visible_s': round(sum(i['duration'] for i in kept), 1),
               'n_intervals': len(kept)}, f, indent=1)
print(f'RAW_VISIBILITY intervals={len(kept)} (dropped {len(dropped)} micro) '
      f'total_visible={sum(i["duration"] for i in kept):.1f}s')
print('RAW_VISIBILITY_OK')
