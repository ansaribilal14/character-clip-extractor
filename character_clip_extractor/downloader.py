"""INBUILT ytagent-based downloader.

ytagent (bilal140202/ytagent, MIT) is embedded as the primary download engine:
  1. ensure ytagent-cli is installed (auto pip-install if missing)
  2. ensure the BGutil POT provider is running on 127.0.0.1:4416
     (needed to bypass datacenter-IP "confirm you're not a bot" checks)
  3. run `ytagent download` with its internal 13-method fallback chain,
     with spaced retries
  4. verify every downloaded file with ffprobe stream-parity (a truncated
     A/V file is deleted and retried)
  5. last-resort fallback: direct yt-dlp with POT extractor args
"""
import json, os, shutil, subprocess, sys, time, urllib.request

POT_URL = 'http://127.0.0.1:4416'
# height cap protects constrained disks; mp4/m4a preferred for CPU decode speed
FMT = ("bv*[ext=mp4][height<={h}]+ba[ext=m4a]/bv*[height<={h}]+ba/"
       "b[height<={h}]/b")


def log(msg):
    print(f'[downloader] {msg}', flush=True)


def ensure_ytagent_cli():
    if shutil.which('ytagent'):
        return True
    log('ytagent-cli not found; installing...')
    r = subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', 'ytagent-cli'],
                       capture_output=True, text=True)
    return r.returncode == 0 and bool(shutil.which('ytagent'))


def pot_alive():
    """Provider answers on :4416 with ANY status (it returns 400 for GET /)."""
    try:
        with urllib.request.urlopen(f'{POT_URL}/', timeout=3) as r:
            return r.status in (200, 400)
    except urllib.error.HTTPError:
        return True          # any HTTP response means the server is up
    except Exception:
        return False


def ensure_pot():
    """Start BGutil POT provider if not already running (idempotent)."""
    if pot_alive():
        log('POT provider already running on :4416')
        return True
    if not shutil.which('ytagent'):
        return False
    log('starting BGutil POT provider via `ytagent setup`...')
    subprocess.Popen(['ytagent', 'setup'],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    for _ in range(15):
        time.sleep(2)
        if pot_alive():
            log('POT provider is UP')
            return True
    log('POT provider did not come up (continuing without it)')
    return False


def probe_streams(path):
    try:
        out = subprocess.check_output(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json',
             '-show_streams', '-show_format', path], text=True)
        info = json.loads(out)
        v = next((s for s in info['streams'] if s['codec_type'] == 'video'), None)
        a = next((s for s in info['streams'] if s['codec_type'] == 'audio'), None)
        dur = float(info['format'].get('duration', 0) or 0)
        return v, a, dur
    except Exception:
        return None, None, 0.0


def verify_file(path):
    """Catch truncated/corrupt downloads: size, streams, A/V duration parity."""
    if not os.path.exists(path) or os.path.getsize(path) < 1_000_000:
        return False, 'missing or too small'
    v, a, dur = probe_streams(path)
    if v is None:
        return False, 'no video stream'
    if a is None:
        return False, 'no audio stream'
    # per-stream duration parity catches A/V truncation seen with relay methods
    vd = float(v.get('duration', 0) or 0)
    ad = float(a.get('duration', 0) or 0)
    if vd and ad and abs(vd - ad) > 2.0:
        return False, f'A/V duration mismatch video={vd:.1f}s audio={ad:.1f}s'
    if dur and vd and abs(dur - vd) > 2.0:
        return False, 'container/video duration mismatch'
    return True, f'{dur:.1f}s OK'


def _video_files(out_dir):
    return [f for f in os.listdir(out_dir)
            if f.lower().endswith(('.mp4', '.mkv', '.webm', '.m4v'))]


def _pick_verified(out_dir):
    best = None
    for f in sorted(_video_files(out_dir),
                    key=lambda f: os.path.getsize(os.path.join(out_dir, f)),
                    reverse=True):
        path = os.path.join(out_dir, f)
        ok, why = verify_file(path)
        log(f'candidate {f}: {why}')
        if ok:
            return path
    return best


def _download_with_ytagent(url, out_dir, max_height, timeout):
    os.makedirs(out_dir, exist_ok=True)
    before = set(_video_files(out_dir))
    cmd = ['ytagent', 'download', url, '--out-dir', out_dir,
           '--format', FMT.format(h=max_height), '--json', '--timeout', str(timeout)]
    log(f'ytagent download (timeout={timeout}s): {url}')
    p = subprocess.run(cmd, capture_output=True, text=True)
    new = [f for f in _video_files(out_dir) if f not in before]
    if new:
        got = _pick_verified(out_dir)
        if got and os.path.basename(got) in new:
            return got
        if got:
            return got
    if p.stdout:
        try:
            j = json.loads(p.stdout.splitlines()[-1])
            for m in j.get('attempts', []):
                log(f"  ytagent attempt: {m.get('method')} ok={m.get('ok')} "
                    f"{(m.get('reason') or '')[:70]}")
        except Exception:
            pass
    return None


def _download_with_ytdlp(url, out_dir, max_height, timeout):
    os.makedirs(out_dir, exist_ok=True)
    out_tpl = os.path.join(out_dir, '%(id)s.%(ext)s')
    cmd = [sys.executable, '-m', 'yt_dlp', '--no-warnings', '-f',
           FMT.format(h=max_height), '--merge-output-format', 'mp4',
           '-o', out_tpl, '--socket-timeout', str(timeout),
           '--extractor-args',
           'youtube:player_skip=webpage,configs;player_client=android_vr,android,web;'
           'youtubepot-bgutilhttp:base_url=http://127.0.0.1:4416',
           url]
    log('fallback: direct yt-dlp with POT')
    subprocess.run(cmd, capture_output=True, text=True)
    return _pick_verified(out_dir)


def download(url, out_dir, max_height=720, attempts=4, spacing_s=30, timeout=240):
    """Download `url` with inbuilt ytagent; returns local path or None.

    Spaced retries matter: on throttled datacenter IPs attempts can start
    succeeding after the throttle window passes (observed ~35 min in testing).
    """
    if not ensure_ytagent_cli():
        log('WARNING: ytagent-cli unavailable; will try yt-dlp only')
    ensure_pot()
    for i in range(1, attempts + 1):
        log(f'=== attempt {i}/{attempts} ===')
        path = _download_with_ytagent(url, out_dir, max_height, timeout)
        if path:
            log(f'DOWNLOADED (ytagent): {path}')
            return path
        path = _download_with_ytdlp(url, out_dir, max_height, timeout)
        if path:
            log(f'DOWNLOADED (yt-dlp fallback): {path}')
            return path
        if i < attempts:
            log(f'all methods failed; sleeping {spacing_s}s before retry '
                f'(throttles often lift with spacing)')
            time.sleep(spacing_s)
    return None


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('url')
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--max-height', type=int, default=720)
    ap.add_argument('--attempts', type=int, default=4)
    a = ap.parse_args()
    got = download(a.url, a.out_dir, a.max_height, a.attempts)
    print('DOWNLOADED:', got)
    sys.exit(0 if got else 1)
