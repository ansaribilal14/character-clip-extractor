"""Verify member reference images with InsightFace.

Per member: detect faces -> keep largest face if height>=80px -> embed (normed 512-d)
-> member centroid -> drop outliers (cosine distance > 0.35 from centroid, 2 passes)
-> cross-member separation matrix (warn if any pair distance < 0.45)
-> save accepted face crops to references/<member>/NN.jpg + contact sheet
-> refs_summary.json with centroids + per-image metadata.
"""
import os, json
import numpy as np, cv2
from insightface.app import FaceAnalysis

BASE = '/home/z/my-project/clipextractor'
RAW = f'{BASE}/refs_raw'
REFS = f'{BASE}/references'
MEMBERS = ['ahyeon', 'ruka', 'rami', 'rora', 'chiquita', 'pharita', 'asa']
TARGET = 'ahyeon'
MIN_FACE_PX = 80
OUTLIER_DIST = 0.35

app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
app.prepare(ctx_id=-1, det_size=(640, 640))

def embed(img_bgr):
    faces = app.get(img_bgr)
    if not faces:
        return None, None
    f = max(faces, key=lambda x: (x.bbox[3] - x.bbox[1]))
    h = f.bbox[3] - f.bbox[1]
    if h < MIN_FACE_PX:
        return None, h
    e = f.normed_embedding
    return e, h

per_member = {}
for m in MEMBERS:
    items = []
    for i in range(8):
        p = f'{RAW}/{m}_{i:02d}.jpg'
        if not os.path.exists(p):
            continue
        img = cv2.imread(p)
        if img is None:
            continue
        e, h = embed(img)
        if e is None:
            print(f'{m}_{i:02d}: no qualifying face (h={h})', flush=True)
            continue
        items.append({'file': p, 'emb': e, 'face_h': float(h)})
    per_member[m] = items
    print(f'{m}: {len(items)}/8 usable', flush=True)

# centroid + iterative outlier removal
centroids, kept = {}, {}
for m, items in per_member.items():
    embs = np.stack([it['emb'] for it in items])
    for _ in range(2):
        c = embs.mean(axis=0)
        c /= (np.linalg.norm(c) + 1e-9)
        d = 1.0 - embs @ c
        mask = d <= OUTLIER_DIST
        if mask.all():
            break
        embs, items2 = embs[mask], [it for it, k in zip(items, mask) if k]
        items = items2
    centroids[m] = (embs.mean(axis=0) / (np.linalg.norm(embs.mean(axis=0)) + 1e-9)).tolist()
    kept[m] = items
    print(f'{m}: kept {len(items)} after outlier removal', flush=True)

# separation matrix
names = [m for m in MEMBERS if kept[m]]
sep = {}
for i, a in enumerate(names):
    for b in names[i + 1:]:
        d = 1.0 - float(np.dot(np.array(centroids[a]), np.array(centroids[b])))
        sep[f'{a}|{b}'] = round(d, 3)
warn = {k: v for k, v in sep.items() if v < 0.45}
print('SEPARATION_MATRIX', json.dumps(sep))
if warn:
    print('WARNING low-separation pairs:', json.dumps(warn))

# save crops + contact sheets
summary = {'members': {}, 'separation': sep, 'min_face_px': MIN_FACE_PX,
           'outlier_dist': OUTLIER_DIST}
for m in names:
    items = kept[m]
    # order by face height desc, keep top 8
    items = sorted(items, key=lambda x: -x['face_h'])[:8]
    os.makedirs(f'{REFS}/{m}', exist_ok=True)
    for old in os.listdir(f'{REFS}/{m}'):
        os.remove(f'{REFS}/{m}/{old}')
    crops, meta = [], []
    for j, it in enumerate(items):
        img = cv2.imread(it['file'])
        faces = app.get(img)
        f = max(faces, key=lambda x: (x.bbox[3] - x.bbox[1]))
        x1, y1, x2, y2 = [int(v) for v in f.bbox]
        H, W = img.shape[:2]
        pad = int(0.35 * max(x2 - x1, y2 - y1))
        x1p, y1p, x2p, y2p = max(0, x1 - pad), max(0, y1 - pad), min(W, x2 + pad), min(H, y2 + pad)
        crop = img[y1p:y2p, x1p:x2p]
        crop = cv2.resize(crop, (256, int(256 * crop.shape[0] / crop.shape[1])))
        out = f'{REFS}/{m}/{j+1:02d}.jpg'
        cv2.imwrite(out, crop, [cv2.IMWRITE_JPEG_QUALITY, 92])
        crops.append(crop)
        meta.append({'ref': f'{j+1:02d}.jpg', 'src': os.path.basename(it['file']),
                     'face_h': round(it['face_h'], 1),
                     'cos_to_centroid': round(float(np.dot(it['emb'], np.array(centroids[m]))), 3)})
    # contact sheet: grid 4 cols
    rows = (len(crops) + 3) // 4
    ch = max(c.shape[0] for c in crops); cw = max(c.shape[1] for c in crops)
    sheet = np.full((rows * ch, 4 * cw, 3), 255, np.uint8)
    for j, c in enumerate(crops):
        r, col = divmod(j, 4)
        sheet[r*ch:r*ch+c.shape[0], col*cw:col*cw+c.shape[1]] = c
    cv2.imwrite(f'{REFS}/contact_{m}.jpg', sheet, [cv2.IMWRITE_JPEG_QUALITY, 90])
    summary['members'][m] = {'n_refs': len(meta), 'centroid': centroids[m], 'refs': meta}
    print(f'{m}: saved {len(meta)} refs + contact sheet', flush=True)

with open(f'{REFS}/refs_summary.json', 'w') as f:
    json.dump(summary, f, indent=1)
print('VERIFY_REFS_OK', {m: len(v) for m, v in kept.items()})
