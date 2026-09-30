"""Normalize source video to 720p H.264/AAC mp4 (uniform for analysis + export).

Usage: python3 00_normalize.py <source_file>
Output: output/analysis/normalized.mp4
"""
import sys, os, subprocess, json

BASE = os.environ.get('CCE_BASE', '/home/z/my-project/clipextractor')
SRC_DIR = f'{BASE}/output/source'
OUT = f'{BASE}/output/analysis/normalized.mp4'

def ffprobe(path):
    cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', path]
    return json.loads(subprocess.check_output(cmd))

def main(src):
    if not src or not os.path.exists(src):
        # pick the largest video file in source dir
        cands = [os.path.join(SRC_DIR, f) for f in os.listdir(SRC_DIR)]
        cands = [c for c in cands if os.path.isfile(c) and not c.endswith('.json')]
        if not cands:
            print('NO_SOURCE'); sys.exit(1)
        src = max(cands, key=os.path.getsize)
    print('SRC', src)
    info = ffprobe(src)
    v = next((s for s in info['streams'] if s['codec_type'] == 'video'), None)
    a = next((s for s in info['streams'] if s['codec_type'] == 'audio'), None)
    dur = float(info['format']['duration'])
    print(f"IN dur={dur:.1f}s {v['codec_name'] if v else '?'} {v.get('width')}x{v.get('height') if v else ''} audio={'yes' if a else 'no'}")

    # Best-quality strategy: if source is already <=720p H.264+AAC in mp4,
    # lossless remux (zero generational loss); otherwise re-encode once at CRF 18.
    ok_container = src.lower().endswith(('.mp4', '.mov', '.m4v'))
    ok_v = v and v['codec_name'] == 'h264' and int(v.get('height', 0)) <= 720
    ok_a = a and a['codec_name'] == 'aac'
    if ok_container and ok_v and ok_a:
        print('REMUX (lossless, source already <=720p h264/aac)')
        cmd = ['ffmpeg', '-y', '-i', src, '-c', 'copy', '-movflags', '+faststart', OUT]
        subprocess.run(cmd, check=True, capture_output=True)
    else:
        print('RE-ENCODE (source not <=720p h264/aac) at crf 18')
        vf = 'scale=-2:min(720\\,ih):flags=bicubic,format=yuv420p'
        cmd = ['ffmpeg', '-y', '-i', src, '-vf', vf,
               '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18',
               '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', OUT]
        subprocess.run(cmd, check=True, capture_output=True)
    info2 = ffprobe(OUT)
    v2 = next(s for s in info2['streams'] if s['codec_type'] == 'video')
    print(f"OUT dur={float(info2['format']['duration']):.1f}s {v2['codec_name']} {v2['width']}x{v2['height']} size={os.path.getsize(OUT)/1e6:.1f}MB")
    print('NORMALIZE_OK')

if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else None)
