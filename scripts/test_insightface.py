"""Smoke test: InsightFace buffalo_l on CPU. Downloads model weights on first run."""
import time, os
import numpy as np, cv2
from insightface.app import FaceAnalysis

os.makedirs('/home/z/my-project/clipextractor/output/analysis', exist_ok=True)

app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
app.prepare(ctx_id=-1, det_size=(640, 640))
print('MODEL_LOADED')

# synthetic noisy frame 1280x720
frame = np.random.randint(0, 255, (720, 1280, 3), dtype=np.uint8)
t0 = time.time()
faces = app.get(frame)
dt = time.time() - t0
print(f'NOISE_FRAME det_time={dt:.3f}s faces={len(faces)}')
print('SMOKE_OK')
