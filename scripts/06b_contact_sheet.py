"""Build labeled contact sheet of all clip thumbnails for manual verification."""
import os, glob, cv2, numpy as np

BASE = os.environ.get('CCE_BASE', '/home/z/my-project/clipextractor')
TARGET = os.environ.get('CCE_TARGET', 'ahyeon')
OUTDIR = f'{BASE}/output/clips/{TARGET}'
OUT = f'{BASE}/output/reports/clip_contact_sheet.jpg'
os.makedirs(os.path.dirname(OUT), exist_ok=True)

thumbs = sorted(glob.glob(f'{OUTDIR}/scene_*.jpg'))
CW, CH = 400, 225
cols = 3
rows = (len(thumbs) + cols - 1) // cols
if not thumbs:
    # zero-scene episode (target character not detected at all):
    # write an honest placeholder sheet instead of crashing on an empty image
    sheet = np.full((CH + 26, CW, 3), 250, np.uint8)
    cv2.putText(sheet, f'NO {TARGET.upper()} SCENES DETECTED',
                (20, CH // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                (0, 0, 160), 2, cv2.LINE_AA)
    cv2.imwrite(OUT, sheet, [cv2.IMWRITE_JPEG_QUALITY, 85])
    print('SHEET_OK 0 thumbs (placeholder) ->', OUT)
    raise SystemExit(0)
sheet = np.full((rows * (CH + 26), cols * CW, 3), 250, np.uint8)
for i, t in enumerate(thumbs):
    img = cv2.imread(t)
    if img is None:
        continue
    img = cv2.resize(img, (CW, CH))
    r, c = divmod(i, cols)
    y, x = r * (CH + 26), c * CW
    sheet[y:y + CH, x:x + CW] = img
    label = os.path.basename(t).replace('.jpg', '')
    cv2.putText(sheet, label, (x + 6, y + CH + 18), cv2.FONT_HERSHEY_SIMPLEX,
                0.55, (30, 30, 30), 1, cv2.LINE_AA)
cv2.imwrite(OUT, sheet, [cv2.IMWRITE_JPEG_QUALITY, 85])
print('SHEET_OK', len(thumbs), 'thumbs ->', OUT)
