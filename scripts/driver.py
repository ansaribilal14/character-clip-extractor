"""Budget-limited foreground batch driver for the [HELLO MONSTERS] BEHIND series.

The runtime kills long tool calls (~500s) and background daemons, so this
driver runs ONE budget-limited round per invocation: it keeps executing
resumable pipeline actions (each capped at 360s) until the round budget
expires, then exits cleanly. Re-invoking the same command continues exactly
where it stopped — every stage is sentinel-based and idempotent.

Per episode: download -> pipeline -> full_video.json -> deliver (storage.to
for >50MB, Telegram document below) -> Telegram status -> worklog ->
data-repo push -> disk cleanup.

Credentials come from /home/z/my-project/.secrets/tg.env (NEVER in git) and
are injected into the environment before the delivery module is imported.
"""
import json
import os
import shutil
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACES = os.path.join(REPO, 'workspaces')
STATUS_FILE = os.path.join(WORKSPACES, 'batch_status.json')
WORKLOG = '/home/z/my-project/worklog.md'
SECRETS = '/home/z/my-project/.secrets/tg.env'
BUDGET_S = 380
STEP_CAP = 320

EPISODES = [
    ('hm_01_ny3', 'iGjY31tyzUc', 'NY #3'),
    ('hm_02_japan1', 'RX5cXuenZ-Y', 'JAPAN #1'),
    ('hm_03_bonuspage', 'VOhQF_RNnis', 'BONUS PAGE'),
    ('hm_04_la1', 'HFLq5j8wU5Q', 'LA #1'),
    ('hm_05_japan2', 'Whlm77_E3Tg', 'JAPAN #2'),
    ('hm_06_sgp', 'xNF9Sru4IN4', 'SINGAPORE | BM TALKPAWON'),
    ('hm_07_la2', 'EiSPHqAQ28w', 'LA #2'),
    ('hm_08_hkgbkk', 'KCS_4REntgI', 'HONG KONG & BANGKOK | BM TALKPAWON'),
    ('hm_09_ny1', 'JW3t5Vua1-c', 'NY #1'),
    ('hm_10_seoul', 'qoDZQ3-CtCY', 'SEOUL'),
    ('hm_11_nadoc', 'xDx0SiYUw_o', 'NORTH AMERICA DOCUMENTARY'),
]


def _pick_cli_python():
    """Pick an interpreter that can actually import the full stack.
    The platform venv and /usr/bin/python3 may differ in site-packages."""
    cands = [os.environ.get('CCE_PY'), '/usr/bin/python3', sys.executable]
    check = ('import character_clip_extractor, insightface, cv2, requests')
    for c in cands:
        if not c:
            continue
        try:
            r = subprocess.run([c, '-c', check], capture_output=True, timeout=90)
            if r.returncode == 0:
                return c
        except Exception:
            continue
    return sys.executable


CLI_PY = _pick_cli_python()


def log(m):
    print(f'[driver] {m}', flush=True)


def load_secrets():
    """Load every .env file in the secrets dir (tg.env, gh.env, ...)."""
    vals = {}
    try:
        for fn in sorted(os.listdir(SECRETS)):
            if not fn.endswith('.env'):
                continue
            for line in open(os.path.join(SECRETS, fn)):
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    k = k.strip()
                    if k in ('TG_TOKEN', 'TG_CHAT'):
                        k = 'CCE_' + k
                    vals[k] = v.strip()
    except OSError:
        pass
    return vals


def _preload_env():
    """Inject env-only secrets BEFORE importing the delivery module (it
    reads CCE_TG_TOKEN / CCE_TG_CHAT / CCE_VISITOR_TOKEN_FILE at import)."""
    for k, v in load_secrets().items():
        os.environ.setdefault(k, v)
    os.environ.setdefault('CCE_VISITOR_TOKEN_FILE',
                          os.path.join(WORKSPACES, 'storage_visitor_token.txt'))


_preload_env()
sys.path.insert(0, REPO)
from character_clip_extractor import refs, delivery  # noqa: E402


def base_of(name):
    return os.path.join(WORKSPACES, name)


def full_video_json(base):
    p = os.path.join(base, 'output', 'analysis', 'full_video.json')
    if os.path.exists(p):
        try:
            return json.load(open(p))
        except Exception:
            return None
    return None


def full_video_path(base):
    fj = full_video_json(base)
    if fj and fj.get('full_video'):
        p = os.path.join(base, 'output', 'clips', 'ahyeon', fj['full_video'])
        if os.path.exists(p):
            return p
    return None


def save_status(s):
    os.makedirs(WORKSPACES, exist_ok=True)
    json.dump(s, open(STATUS_FILE, 'w'), indent=1, ensure_ascii=False)


def push_data(msg):
    try:
        subprocess.run(['git', 'add', '-A'], cwd=WORKSPACES, check=True, timeout=180)
        subprocess.run(['git', '-c', 'user.name=bot', '-c', 'user.email=bot@ansaribilal14.dev',
                        'commit', '-q', '-m', msg], cwd=WORKSPACES, check=True, timeout=180)
        subprocess.run(['git', 'push', '-q', 'data', 'HEAD:main', '--force'],
                       cwd=WORKSPACES, check=True, timeout=300)
        log(f'data repo pushed: {msg}')
    except Exception as e:
        log(f'data push failed: {e}')


def worklog_append(name, title, lines):
    stamp = time.strftime('%Y-%m-%d %H:%M')
    try:
        with open(WORKLOG, 'a') as f:
            f.write(f'\n---\nTask ID: hm-batch/{name}\nAgent: driver\nTask: '
                    f'{title} — process & deliver\n\nWork Log:\n')
            for ln in lines:
                f.write(f'- {ln}\n')
            f.write(f'\nStage Summary:\n- {title} completed and delivered ({stamp})\n')
    except OSError as e:
        log(f'worklog append failed: {e}')


def deliver_episode(name, vid, title, s):
    base = base_of(name)
    fvp = full_video_path(base)
    fj = full_video_json(base)
    if not fvp or not fj:
        log(f'{name}: full_video.json present but file missing — rerun 10_concat_full')
        return False
    size_mb = fj.get('size_mb') or os.path.getsize(fvp) / 1e6
    cap = (f'BABYMONSTER [HELLO MONSTERS] BEHIND — {title}\n'
           f'Ahyeon full-video cut · {fj.get("n_windows", "?")} windows · '
           f'{fj.get("duration_s", 0):.0f}s · {fj.get("resolution", "?")} · CRF16\n'
           f'https://youtu.be/{vid}')
    log(f'delivering {name} ({size_mb:.1f} MB) ...')
    res = delivery.deliver_auto(fvp, cap, keep=False)
    url = res.get('url') or ''
    ok = bool(res.get('ok'))
    log(f'delivery: kind={res.get("kind")} ok={ok} url={url}')
    if not ok:
        ep = s['episodes'].setdefault(name, {})
        ep['deliver_fail'] = int(ep.get('deliver_fail', 0)) + 1
        save_status(s)
        log(f'{name}: delivery NOT confirmed (attempt '
            f'{ep["deliver_fail"]}) — will retry next round')
        return False
    ep = s['episodes'].setdefault(name, {})
    ep.update({'title': title, 'delivered': True, 'kind': res.get('kind'),
               'url': url, 'expires_at': res.get('expires_at'),
               'size_mb': round(size_mb, 2),
               'delivered_at': time.strftime('%Y-%m-%d %H:%M')})
    save_status(s)
    try:
        json.dump(res, open(os.path.join(base, 'output', 'analysis',
                                         'delivery.json'), 'w'), indent=1)
    except OSError:
        pass
    worklog_append(name, title, [
        f'delivered via {res.get("kind")}: {url or "(no url returned)"}',
        f'{fj.get("n_windows")} windows, {fj.get("duration_s", 0):.0f}s, '
        f'{fj.get("resolution")}, {size_mb:.1f} MB',
        'source + normalized + clips deleted after confirm (disk reclaimed)',
    ])
    for p in (os.path.join(base, 'output', 'source'),
              os.path.join(base, 'output', 'analysis', 'normalized.mp4'),
              os.path.join(base, 'output', 'clips')):
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
            log(f'cleaned dir {p}')
        elif os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass
    push_data(f'batch data: {name} ({title}) DONE + delivered')
    return True


def run_cli(name, vid, left):
    base = base_of(name)
    os.makedirs(base, exist_ok=True)
    ok, msg = refs.ensure_references(base, 'ahyeon', None, False)
    log(f'references: {msg}')
    if not ok:
        raise RuntimeError('reference setup failed')
    env = dict(os.environ)
    env.update(load_secrets())
    env['CCE_VISITOR_TOKEN_FILE'] = os.path.join(
        WORKSPACES, 'storage_visitor_token.txt')
    cmd = [CLI_PY, '-m', 'character_clip_extractor',
           '--url', f'https://youtu.be/{vid}', '--character', 'ahyeon',
           '--out', base, '--pad', '5', '--max-height', '1080',
           '--no-zip', '--no-deliver']
    timeout = max(5, min(STEP_CAP, int(left)))
    log(f'>>> CLI round (timeout {timeout}s): {name} [py={CLI_PY}]')
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True,
                            start_new_session=True)
    try:
        out, errbuf = proc.communicate(timeout=timeout)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        # kill the whole process group: orphaned ffmpeg children would keep
        # the stdout pipe open and hang communicate() until the tool kill
        import signal
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            proc.kill()
        log('CLI round hit budget (process group killed; resumes next round)')
        try:
            proc.communicate(timeout=30)
        except Exception:
            pass
        return 0
    tail = '\n'.join((out or '').strip().splitlines()[-12:])
    if tail:
        print(tail, flush=True)
    if rc != 0:
        err = ' | '.join((errbuf or '').strip().splitlines()[-4:])
        log(f'CLI rc={rc}: {err}')
        return rc
    return 0


def status_table(s):
    print(f'{"episode":16} {"title":34} {"state":16} url')
    for name, vid, title in EPISODES:
        ep = s['episodes'].get(name, {})
        base = base_of(name)
        state = ('delivered' if ep.get('delivered')
                 else 'ready-to-deliver' if full_video_json(base)
                 else 'pending')
        print(f'{name:16} {title[:34]:34} {state:16} {ep.get("url") or "-"}')


def main():
    t0 = time.time()
    os.makedirs(WORKSPACES, exist_ok=True)
    s = json.load(open(STATUS_FILE)) if os.path.exists(STATUS_FILE) \
        else {'episodes': {}}
    for name, vid, title in EPISODES:
        s['episodes'].setdefault(name, {'title': title, 'delivered': False})
    if '--status' in sys.argv:
        status_table(s)
        return 0
    for name, vid, title in EPISODES:
        ep = s['episodes'].get(name, {})
        if ep.get('delivered'):
            continue
        base = base_of(name)
        left = BUDGET_S - (time.time() - t0)
        if left < 90:
            log('round budget exhausted; clean exit (re-run to continue)')
            return 0
        if full_video_json(base):
            if left < 300:
                log(f'{name}: full video ready, delivery deferred '
                    f'(need ~300s, have {left:.0f}s)')
                return 0
            deliver_episode(name, vid, title, s)
        else:
            fails = int(ep.get('fail_count', 0))
            if fails >= 4:
                log(f'{name}: {fails} consecutive failures — blocked, skipping '
                    f'to next episode this round')
                continue
            rc = run_cli(name, vid, left)
            if rc != 0:
                ep['fail_count'] = fails + 1
                save_status(s)
                log(f'{name}: failed ({fails + 1}/4) — ending round, retry next round')
                return 0                      # dedicated retry next round
            if 'fail_count' in ep:
                ep.pop('fail_count')
                save_status(s)
            if full_video_json(base):
                left = BUDGET_S - (time.time() - t0)
                if left >= 300:
                    deliver_episode(name, vid, title, s)
                else:
                    log(f'{name}: full video ready; delivery next round')
        if time.time() - t0 >= BUDGET_S:
            log('round budget exhausted; clean exit (re-run to continue)')
            return 0
    log('ALL EPISODES PROCESSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
