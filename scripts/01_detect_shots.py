"""Shot boundary detection with PySceneDetect (ContentDetector).

Input : output/analysis/normalized.mp4
Output: output/analysis/shots.json  [{shot_id, start, end, duration}]
"""
import json, os
from scenedetect import detect, ContentDetector, SceneManager
import cv2

BASE = os.environ.get('CCE_BASE', '/home/z/my-project/clipextractor')
VIDEO = f'{BASE}/output/analysis/normalized.mp4'
OUT = f'{BASE}/output/analysis/shots.json'

cap = cv2.VideoCapture(VIDEO)
fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
nfr = cap.get(cv2.CAP_PROP_FRAME_COUNT)
cap.release()
print(f'fps={fps:.3f} frames={nfr:.0f}')

scene_list = detect(VIDEO, ContentDetector(threshold=27.0))

shots = []
for i, (start, end) in enumerate(scene_list):
    shots.append({
        'shot_id': i,
        'start': round(start.get_seconds(), 3),
        'end': round(end.get_seconds(), 3),
        'duration': round((end - start).get_seconds(), 3),
    })
# ensure full coverage to EOF
if shots:
    last_end = shots[-1]['end']
    vid_dur = nfr / fps
    if vid_dur - last_end > 0.25:
        shots.append({'shot_id': len(shots), 'start': last_end,
                      'end': round(vid_dur, 3), 'duration': round(vid_dur - last_end, 3)})

with open(OUT, 'w') as f:
    json.dump({'fps': fps, 'video_duration': round(nfr / fps, 3), 'shots': shots}, f, indent=1)
durs = [s['duration'] for s in shots]
print(f'SHOTS {len(shots)}  mean={sum(durs)/len(durs):.2f}s  min={min(durs):.2f}  max={max(durs):.2f}')
print('DETECT_SHOTS_OK')
