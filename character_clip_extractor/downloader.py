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

# ---- GitHub Actions download farm (github_actions_farm path) ----
# When the local IP is bot-checked, download remotely on a GitHub runner
# (WARP + POT) and fetch the artifact. Config via env:
#   CCE_GH_TOKEN   GitHub token with actions:write on the farm repo
#   CCE_FARM_OWNER owner of the farm repo   (default ansaribilal14)
#   CCE_FARM_REPO  farm repo name           (default yt-farm)
FARM_OWNER = os.environ.get('CCE_FARM_OWNER', 'ansaribilal14')
FARM_REPO = os.environ.get('CCE_FARM_REPO', 'yt-farm')
FARM_WORKFLOW = 'yt-download-farm.yml'
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


def _gh_api(path, method='GET', body=None, timeout=30):
    token = os.environ.get('CCE_GH_TOKEN', '')
    if not token:
        return None
    req = urllib.request.Request(
        f'https://api.github.com{path}',
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Authorization': f'token {token}',
                 'Accept': 'application/vnd.github+json',
                 'User-Agent': 'cce-farm-client'},
        method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception:
        return None


def _farm_artifact(video_id):
    """Find a non-expired artifact video_<id> in the farm repo. Returns
    (artifact_id, archive_url) or None."""
    res = _gh_api(f'/repos/{FARM_OWNER}/{FARM_REPO}/actions/artifacts'
                  f'?name=video_{video_id}&per_page=10')
    if not res or res[0] != 200:
        return None
    for a in res[1].get('artifacts', []):
        if a.get('name') == f'video_{video_id}' and not a.get('expired'):
            return a
    return None


def _farm_download_artifact(video_id, out_dir):
    """Download + extract the artifact zip; return the video file path."""
    art = _farm_artifact(video_id)
    if not art:
        return None
    token = os.environ.get('CCE_GH_TOKEN', '')
    url = art.get('archive_download_url')
    if not url:
        return None
    zpath = os.path.join(out_dir, f'farm_{video_id}.zip')
    try:
        req = urllib.request.Request(url, headers={
            'Authorization': f'token {token}', 'User-Agent': 'cce-farm-client'})
        with urllib.request.urlopen(req, timeout=300) as r, open(zpath, 'wb') as f:
            shutil.copyfileobj(r, f)
    except Exception as e:
        log(f'farm artifact download failed: {e}')
        try:
            os.remove(zpath)
        except OSError:
            pass
        return None
    try:
        with __import__('zipfile').ZipFile(zpath) as z:
            z.extractall(out_dir)
        os.remove(zpath)
    except Exception as e:
        log(f'farm artifact extract failed: {e}')
        return None
    for f in sorted(_video_files(out_dir), key=lambda f: os.path.getsize(
            os.path.join(out_dir, f)), reverse=True):
        ok, why = verify_file(f)
        log(f'farm candidate {f}: {why}')
        if ok:
            return os.path.join(out_dir, f)
    return None


def _download_with_farm(url, out_dir, budget_s=540):
    """Remote download via GitHub Actions farm. Idempotent: if a previous
    round already dispatched a run for this video, we pick up its artifact
    instead of re-dispatching. Returns a local path or None."""
    video_id = url.rstrip('/').split('/')[-1].split('?v=')[-1][:11]
    if not os.environ.get('CCE_GH_TOKEN'):
        log('farm: no CCE_GH_TOKEN — skipping farm fallback')
        return None
    os.makedirs(out_dir, exist_ok=True)
    t0 = time.monotonic()
    # already-completed artifact from an earlier round/run?
    got = _farm_download_artifact(video_id, out_dir)
    if got:
        log(f'DOWNLOADED (farm artifact): {got}')
        return got
    log(f'farm: dispatching {FARM_OWNER}/{FARM_REPO} for {video_id}')
    res = _gh_api(
        f'/repos/{FARM_OWNER}/{FARM_REPO}/actions/workflows/'
        f'{FARM_WORKFLOW}/dispatches', method='POST',
        body={'ref': 'main',
              'inputs': {'video_url': f'https://www.youtube.com/watch?v={video_id}',
                         'video_id': video_id}})
    if not res or res[0] != 204:
        log(f'farm: dispatch failed ({res})')
        return None
    # wait for the run to conclude, then grab the artifact
    while time.monotonic() - t0 < budget_s:
        time.sleep(20)
        runs = _gh_api(f'/repos/{FARM_OWNER}/{FARM_REPO}/actions/runs'
                       f'?event=workflow_dispatch&per_page=5')
        if runs and runs[0] == 200:
            for r in runs[1].get('workflow_runs', []):
                if r.get('status') == 'completed':
                    log(f"farm: recent run {r['id']} conclusion="
                        f"{r.get('conclusion')}")
                    if r.get('conclusion') == 'success':
                        got = _farm_download_artifact(video_id, out_dir)
                        if got:
                            log(f'DOWNLOADED (farm): {got}')
                            return got
                    break
        # artifact may appear slightly after the run is marked complete
        got = _farm_download_artifact(video_id, out_dir)
        if got:
            log(f'DOWNLOADED (farm artifact): {got}')
            return got
    log('farm: budget exceeded waiting for artifact (will pick up next round)')
    return None


def download(url, out_dir, max_height=720, attempts=4, spacing_s=15, timeout=60):
    """Download `url` with inbuilt ytagent; returns local path or None.

    Spaced retries matter: on throttled datacenter IPs attempts can start
    succeeding after the throttle window passes (observed ~35 min in testing).
    timeout=60 keeps each attempt short so several full attempt cycles fit
    inside one budget-limited driver round (~360s).
    """
    if not ensure_ytagent_cli():
        log('WARNING: ytagent-cli unavailable; will try yt-dlp only')
    ensure_pot()
    # when the farm is available, don't burn the step budget on direct
    # retries that keep failing the same way — reach the farm sooner
    if os.environ.get('CCE_GH_TOKEN') and attempts > 2:
        attempts = 2
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
    # all direct methods failed — use the GitHub Actions download farm
    path = _download_with_farm(url, out_dir)
    if path:
        return path
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
