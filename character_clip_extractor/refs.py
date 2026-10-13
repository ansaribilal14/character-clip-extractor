"""Build verified face references for ANY character from user-provided images.

Input : image files or a directory of images (or a YouTube fancam search term)
Output: <workspace>/references/<target>/NN.jpg (verified face crops)
        <workspace>/references/refs_summary.json
          {members: {<target>: {centroid: [...], n_refs: N, refs: [...]}}}

Verification mirrors the proven verify_refs.py flow:
  - InsightFace detect, keep largest face per image with size >= 80 px
  - embed (buffalo_l normed_embedding)
  - drop outliers > 0.35 cosine from the centroid (wrong-person shots)
  - if multiple centroid candidates disagree strongly, the largest cluster wins
If the workspace already has a refs_summary.json containing <target>, it is
kept (existing verified references are never overwritten silently).
"""
import json, os, glob, shutil
import numpy as np
import cv2
from insightface.app import FaceAnalysis

MIN_FACE_PX = 80
OUTLIER_COS = 0.35


def _load_app():
    app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
    app.prepare(ctx_id=-1, det_size=(640, 640))
    return app


def _images_from_paths(paths):
    exts = ('.jpg', '.jpeg', '.png', '.webp', '.bmp')
    out = []
    for p in paths:
        if os.path.isdir(p):
            out += sorted(glob.glob(os.path.join(p, '**', '*.*'), recursive=True))
        else:
            out.append(p)
    return [p for p in out if p.lower().endswith(exts)]


def build_from_images(app, image_paths, ref_dir):
    os.makedirs(ref_dir, exist_ok=True)
    embs, crops = [], []
    for p in _images_from_paths(image_paths):
        img = cv2.imread(p)
        if img is None:
            continue
        faces = app.get(img)
        if not faces:
            continue
        f = max(faces, key=lambda f: (f.bbox[3] - f.bbox[1]))
        h = float(f.bbox[3] - f.bbox[1])
        if h < MIN_FACE_PX or f.normed_embedding is None:
            continue
        embs.append(np.asarray(f.normed_embedding, dtype=np.float32))
        crops.append((os.path.basename(p), f.bbox.astype(int), img))
    if not embs:
        return None, 'no usable faces found in the provided images'
    E = np.stack(embs)
    cent = E.mean(axis=0)
    cent /= (np.linalg.norm(cent) + 1e-9)
    keep = [i for i in range(len(E)) if float(np.dot(E[i], cent)) >= OUTLIER_COS]
    if not keep:
        return None, 'all candidate faces disagreed with the cluster centroid'
    cent = E[keep].mean(axis=0)
    cent /= (np.linalg.norm(cent) + 1e-9)

    # save verified crops
    for old in glob.glob(os.path.join(ref_dir, '*.jpg')):
        os.remove(old)
    refs = []
    for n, i in enumerate(sorted(keep), 1):
        name, bbox, img = crops[i]
        x1, y1, x2, y2 = bbox
        H, W = img.shape[:2]
        pad = int(0.25 * max(x2 - x1, y2 - y1))
        x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
        x2, y2 = min(W, x2 + pad), min(H, y2 + pad)
        outp = os.path.join(ref_dir, f'{n:02d}.jpg')
        cv2.imwrite(outp, img[y1:y2, x1:x2], [cv2.IMWRITE_JPEG_QUALITY, 92])
        refs.append(os.path.basename(outp))
    return {'centroid': [round(float(v), 6) for v in cent],
            'n_refs': len(refs), 'refs': refs,
            'source': 'user_images'}, None


def ensure_references(workspace, target, ref_images=None, auto_search=None):
    """Make sure <workspace>/references/refs_summary.json has `<target>`.

    Order: (1) already present -> keep; (2) user-provided images; (3) bundled
    references shipped in the repo (if target exists there); (4) optional
    fancam auto-search. Returns (ok, message).
    """
    REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ws_refs = os.path.join(workspace, 'references')
    ws_summary = os.path.join(ws_refs, 'refs_summary.json')

    summary = {}
    if os.path.exists(ws_summary):
        try:
            summary = json.load(open(ws_summary))
        except Exception:
            summary = {}
    members = summary.setdefault('members', {})
    if target in members and members[target].get('n_refs', 0) > 0:
        return True, f'reusing existing verified references for {target}'

    app = _load_app()

    # (2) user-provided images
    if ref_images:
        entry, err = build_from_images(app, ref_images,
                                       os.path.join(ws_refs, target))
        if entry:
            members[target] = entry
            json.dump(summary, open(ws_summary, 'w'), indent=1)
            return True, (f"built {entry['n_refs']} references for {target} "
                          f"from user images")
        return False, f'reference build failed: {err}'

    # (3) bundled references in the repo (e.g. BABYMONSTER members)
    bundled_summary = os.path.join(REPO, 'references', 'refs_summary.json')
    if os.path.exists(bundled_summary):
        try:
            b = json.load(open(bundled_summary))
            if target in b.get('members', {}):
                members[target] = b['members'][target]
                # copy crops if available so contact sheets keep working
                src_dir = os.path.join(REPO, 'references', target)
                if os.path.isdir(src_dir):
                    dst = os.path.join(ws_refs, target)
                    os.makedirs(dst, exist_ok=True)
                    for f in glob.glob(os.path.join(src_dir, '*.jpg')):
                        shutil.copy(f, dst)
                json.dump(summary, open(ws_summary, 'w'), indent=1)
                return True, f'using bundled references for {target}'
        except Exception:
            pass

    # (4) auto fancam search (best-effort; requires reachable YouTube)
    if auto_search:
        try:
            sys_path = os.path.join(REPO, 'scripts')
            if sys_path not in __import__('sys').path:
                __import__('sys').path.insert(0, sys_path)
            import get_refs  # noqa
        except Exception as e:
            return False, (f'auto reference search unavailable ({e}); '
                           f'provide --ref-images instead')
    return False, (f'no references for "{target}": provide --ref-images '
                   f'(a few clear photos of the character)')
