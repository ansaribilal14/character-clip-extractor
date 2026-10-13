#!/usr/bin/env python3
"""Invidious-bypass YouTube fetcher for datacenter-IP throttles.

Tries a list of live Invidious instances for /api/v1/videos/<id>, extracts a
progressive mp4 URL (itag 22 = 720p) or adaptive 1080p video + audio pair,
then downloads with HTTP Range resume — designed to survive being killed
mid-download by the runtime's tool-call SIGKILL: re-running the script
continues from the existing byte count.

Output lands in the workspace source dir so downloader._pick_verified()
finds it and the CLI skips its own download stage.
"""
import json
import os
import subprocess
import sys
import time

import requests

INSTANCES = [
    'https://inv.nadeko.net',
    'https://invidious.nerdvpn.de',
    'https://invidious.f5.si',
    'https://yewtu.be',
    'https://iv.melmac.space',
]
DYNAMIC_LIST = 'https://api.invidious.io/instances.json?sort_by=health'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')


def log(m):
    print(f'[inv] {m}', flush=True)


def live_instances():
    """Fetch healthy https instances from the official registry."""
    try:
        r = requests.get(DYNAMIC_LIST, timeout=15, headers={'User-Agent': UA})
        out = []
        for name, info in (r.json() or []):
            if info.get('type') == 'https' and info.get('uri'):
                out.append(info['uri'].rstrip('/'))
        log(f'registry: {len(out)} https instances')
        return out
    except Exception as e:
        log(f'registry failed: {type(e).__name__} {str(e)[:60]}')
        return []


def probe(vid):
    tried = 0
    for inst in INSTANCES + [u for u in live_instances() if u not in INSTANCES]:
        if tried >= 14:
            break
        tried += 1
        try:
            t0 = time.time()
            r = requests.get(f'{inst}/api/v1/videos/{vid}', params={'local': 'true'},
                             timeout=18, headers={'User-Agent': UA})
            if r.status_code != 200:
                log(f'{inst}: HTTP {r.status_code} ({time.time()-t0:.1f}s)')
                continue
            j = r.json()
            fmts = j.get('formatStreams') or []
            adp = j.get('adaptiveFormats') or []
            if not fmts and not adp:
                log(f'{inst}: empty stream lists')
                continue
            log(f'{inst}: OK title={j.get("title","")[:40]} '
                f'fmts={len(fmts)} adp={len(adp)}')
            return j, fmts, adp
        except Exception as e:
            log(f'{inst}: {type(e).__name__} {str(e)[:60]}')
    return None, None, None


def pick_streams(fmts, adp, maxh=1080):
    """Return list of (url, suffix, kind) to download."""
    prog = sorted((f for f in fmts if f.get('container') == 'mp4'
                   or 'mp4' in (f.get('type') or '')),
                  key=lambda f: int(f.get('itag') or 0))
    # progressive itag 22 (720p) preferred: single file with audio
    for f in prog:
        if f.get('itag') == '22':
            return [(f['url'], '.mp4', 'progressive')], f.get('resolution')
    best_res, best = 0, None
    for f in adp:
        res = str(f.get('resolution') or '0p')
        h = int(res.rstrip('p') or 0)
        if 'video/mp4' in (f.get('type') or '') and 0 < h <= maxh and h >= best_res:
            best_res, best = h, f
    if not best:
        return [], None
    audio = next((a for a in adp if a.get('itag') == '140'
                  or a.get('audioQuality')), None)
    out = [(best['url'], '.v.mp4', 'video'), ]
    if audio:
        out.append((audio['url'], '.a.m4a', 'audio'))
    return out, best.get('resolution')


def fetch(url, path):
    """Streaming download with byte-range resume; returns True when complete."""
    total_hdr = None
    for attempt in range(2):
        try:
            pos = os.path.getsize(path) if os.path.exists(path) else 0
            headers = {'User-Agent': UA}
            if pos:
                headers['Range'] = f'bytes={pos}-'
            with requests.get(url, headers=headers, stream=True, timeout=(20, 60)) as r:
                if r.status_code == 416:          # already complete
                    return True
                if r.status_code not in (200, 206):
                    log(f'  HTTP {r.status_code} (pos={pos})')
                    return False
                if r.status_code == 200 and pos:
                    pos = 0                        # server ignored Range
                cr = r.headers.get('Content-Range') or ''
                cl = r.headers.get('Content-Length')
                if cr and '/' in cr:
                    total_hdr = int(cr.split('/')[-1])
                elif cl:
                    total_hdr = int(cl) + pos
                mode = 'ab' if pos else 'wb'
                with open(path, mode) as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            if total_hdr and os.path.getsize(path) >= total_hdr:
                return True
            return os.path.getsize(path) > 0 and total_hdr is None
        except Exception as e:
            log(f'  chunk error: {type(e).__name__} {str(e)[:60]} '
                f'(have {os.path.getsize(path) if os.path.exists(path) else 0})')
            time.sleep(2)
    return False


def main():
    vid = sys.argv[1]
    out_dir = sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    j, fmts, adp = probe(vid)
    if j is None:
        print('INVIDIOUS_NO_INSTANCE')
        return 1
    streams, res = pick_streams(fmts, adp)
    if not streams:
        print('INVIDIOUS_NO_STREAMS')
        return 1
    log(f'selected {len(streams)} stream(s), resolution={res}')
    paths = []
    for url, suffix, kind in streams:
        p = os.path.join(out_dir, f'{vid}{suffix}')
        log(f'downloading {kind} -> {os.path.basename(p)}')
        if not fetch(url, p):
            log(f'{kind} download incomplete — will resume next run')
            return 1
        paths.append(p)
        log(f'{kind} complete: {os.path.getsize(p)/1e6:.1f} MB')
    if len(paths) == 1:
        final = paths[0]
        target = os.path.join(out_dir, f'{vid}.mp4')
        if final != target:
            os.replace(final, target)
        log(f'PROGRESSIVE_OK {target}')
        return 0
    # merge video+audio
    v, a = paths
    target = os.path.join(out_dir, f'{vid}.mp4')
    r = subprocess.run(['ffmpeg', '-y', '-i', v, '-i', a, '-c', 'copy',
                        '-movflags', '+faststart', target],
                       capture_output=True, text=True)
    if r.returncode == 0 and os.path.exists(target):
        os.remove(v)
        os.remove(a)
        log(f'MERGED_OK {target}')
        return 0
    log(f'ffmpeg merge failed: {(r.stderr or "")[-200:]}')
    return 1


if __name__ == '__main__':
    sys.exit(main())
