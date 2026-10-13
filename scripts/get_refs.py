"""Download reference thumbnails for all BABYMONSTER members via yt-dlp search.

Strategy: search '<member> focus cam' fancams -> take top N video IDs ->
download i.ytimg.com/maxresdefault.jpg (fallback sd/hq) -> refs_raw/{member}_{i}.jpg
"""
import os, sys, json, urllib.request

MEMBERS = ['ahyeon', 'ruka', 'rami', 'rora', 'chiquita', 'pharita', 'asa']
N_PER = 8
RAW = '/home/z/my-project/clipextractor/refs_raw'
os.makedirs(RAW, exist_ok=True)

import yt_dlp

def search_ids(query, n):
    opts = {
        'quiet': True, 'no_warnings': True, 'skip_download': True,
        'extract_flat': True, 'default_search': 'ytsearch',
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f'ytsearch{n}:{query}', download=False)
    out = []
    for e in info.get('entries') or []:
        if e and e.get('id'):
            out.append({'id': e['id'], 'title': e.get('title', '')})
    return out

def fetch_thumb(vid, path):
    for name in ['maxresdefault', 'sddefault', 'hqdefault']:
        url = f'https://i.ytimg.com/vi/{vid}/{name}.jpg'
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            data = urllib.request.urlopen(req, timeout=20).read()
            if len(data) > 3000:  # placeholder jpgs are ~1-2KB
                with open(path, 'wb') as f:
                    f.write(data)
                return name, len(data)
        except Exception:
            continue
    return None, 0

manifest = {}
for m in MEMBERS:
    print(f'=== {m.upper()} ===', flush=True)
    try:
        vids = search_ids(f'BABYMONSTER {m} focus cam', N_PER)
    except Exception as e:
        print(f'  search failed: {e}', flush=True)
        vids = []
    manifest[m] = []
    for i, v in enumerate(vids):
        path = os.path.join(RAW, f'{m}_{i:02d}.jpg')
        kind, size = fetch_thumb(v['id'], path)
        ok = kind is not None
        print(f'  [{v["id"]}] {kind} {size}B  {v["title"][:60]}', flush=True)
        manifest[m].append({'id': v['id'], 'title': v['title'], 'thumb': kind,
                            'file': path if ok else None})

with open(os.path.join(RAW, 'manifest.json'), 'w') as f:
    json.dump(manifest, f, indent=1, ensure_ascii=False)

total = sum(1 for m in MEMBERS for r in manifest[m] if r['file'])
print(f'REFS_DOWNLOADED total={total}')
