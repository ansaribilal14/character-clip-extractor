"""Sample frames (2fps) + InsightFace detect/embed + match vs member centroids.

Input : output/analysis/normalized.mp4, references/refs_summary.json
Output: output/analysis/analysis.jsonl  (one record per sampled frame)
        each: {t, n_faces, faces:[{member, cos, bbox, det_score, size}], ahyeon_best_cos}
"""
import json, os, time
import numpy as np, cv2
from insightface.app import FaceAnalysis

BASE = os.environ.get('CCE_BASE', '/home/z/my-project/clipextractor')
TARGET = os.environ.get('CCE_TARGET', 'ahyeon')   # character slug (must exist in refs)
TKEY = f'{TARGET}_best_cos'
VIDEO = f'{BASE}/output/analysis/normalized.mp4'
REFS = f'{BASE}/references/refs_summary.json'
OUT = f'{BASE}/output/analysis/analysis.jsonl'
FPS_SAMPLE = 2.0
DET_SIZE = (640, 640)
MATCH_THRESHOLD = 0.42   # cos to member centroid; centroids separated by >=0.72

summary = json.load(open(REFS))
# members = whoever has verified references in this workspace (generic)
MEMBERS = list(summary['members'].keys())
if TARGET not in MEMBERS:
    raise SystemExit(f'TARGET "{TARGET}" has no references in {REFS} (have: {MEMBERS})')
C = {m: np.array(summary['members'][m]['centroid'], dtype=np.float32) for m in MEMBERS}

app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
app.prepare(ctx_id=-1, det_size=DET_SIZE)

cap = cv2.VideoCapture(VIDEO)
src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
total = cap.get(cv2.CAP_PROP_FRAME_COUNT)
dur = total / src_fps
step = src_fps / FPS_SAMPLE

# resume support: skip frames already analyzed in a previous (timed-out) run
records = []
resume_t = 0.0
if os.path.exists(OUT):
    prev = [json.loads(l) for l in open(OUT)]
    if prev:
        records = prev
        resume_t = prev[-1]['t']
        print(f'RESUMING from t={resume_t:.1f}s ({len(prev)} records)')
out_f = open(OUT, 'a' if records else 'w')
next_idx = int(resume_t * src_fps)
t_start = time.time()
idx = 0
while True:
    ok = cap.grab()
    if not ok:
        break
    if idx >= next_idx:
        ok, frame = cap.retrieve()
        if not ok:
            break
        t = idx / src_fps
        scale = 960.0 / frame.shape[1] if frame.shape[1] > 960 else 1.0
        proc = cv2.resize(frame, (int(frame.shape[1]*scale), int(frame.shape[0]*scale))) if scale != 1.0 else frame
        faces = app.get(proc)
        rec_faces = []
        for f in faces:
            x1, y1, x2, y2 = f.bbox
            emb = f.normed_embedding
            sims = {m: float(np.dot(emb, C[m])) for m in MEMBERS}
            best = max(sims, key=sims.get)
            if sims[best] < MATCH_THRESHOLD:
                best_m, best_c = 'unknown', float(sims[best])
            else:
                best_m, best_c = best, sims[best]
            rec_faces.append({
                'member': best_m, 'cos': round(float(best_c), 4),
                'bbox': [round(float(v)/scale, 1) for v in (x1, y1, x2, y2)],
                'det_score': round(float(f.det_score), 3),
                'size': round(float(y2 - y1)/scale, 1),
            })
        ah = max((f['cos'] for f in rec_faces if f['member'] == TARGET), default=None)
        rec = {'t': round(t, 3), 'n_faces': len(rec_faces),
               'faces': rec_faces,
               TKEY: round(ah, 4) if ah is not None else None}
        records.append(rec)
        out_f.write(json.dumps(rec) + '\n')
        out_f.flush()
        next_idx = next_idx + step
    idx += 1
cap.release()
out_f.close()

n_ah = sum(1 for r in records if any(f['member'] == TARGET for f in r['faces']))
n_unknown = sum(1 for r in records for f in r['faces'] if f['member'] == 'unknown')
n_tot_faces = sum(r['n_faces'] for r in records)
dt = time.time() - t_start
print(f'FRAMES_SAMPLED={len(records)} video_dur={dur:.1f}s faces_total={n_tot_faces} '
      f'{TARGET}_frames={n_ah} unknown_face_inst={n_unknown} elapsed={dt:.0f}s ({dt/max(1,len(records)):.3f}s/frame)')
print('ANALYZE_FACES_OK')
