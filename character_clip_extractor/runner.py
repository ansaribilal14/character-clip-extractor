"""Run the full character-centric clip pipeline inside a workspace.

Steps (scripts/ shipped alongside the package):
  download (inbuilt ytagent) -> 00 normalize -> 01 shot detection ->
  02 face analysis @2fps -> 03 RAW visibility -> 04 voice activity ->
  04b captions -> 05 scene continuity grouping -> 06 export (CRF16) ->
  06b contact sheet -> 07 QC -> 08 reports

Env contract with the scripts:
  CCE_BASE      workspace root          CCE_TARGET    character slug
  CCE_VIDEO_ID  youtube id              CCE_VIDEO_URL canonical url
  CCE_PAD       export padding seconds
"""
import json, os, subprocess, sys, time

PKG_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(PKG_DIR)
SCRIPTS = os.environ.get('CCE_SCRIPTS', os.path.join(REPO, 'scripts'))

PIPELINE = [
    ('00_normalize.py',   'NORMALIZE_OK'),
    ('01_detect_shots.py', 'DETECT_SHOTS_OK'),
    ('02_analyze_faces.py', 'ANALYZE_FACES_OK'),
    ('03_raw_visibility.py', 'RAW_VISIBILITY_OK'),
    ('04_audio_activity.py', 'AUDIO_OK'),
    ('04b_fetch_captions.py', None),          # may legitimately fail (bot check)
    ('05_group_scenes.py', 'GROUP_SCENES_OK'),
    ('06_export_clips.py', 'EXPORT_OK'),
    ('06b_contact_sheet.py', 'SHEET_OK'),
    ('07_qc.py', 'QC_OK'),
    ('08_reports.py', 'REPORTS_OK'),
    ('10_concat_full.py', 'FULL_VIDEO_OK'),
]


def log(msg):
    print(f'[runner] {msg}', flush=True)


def analysis_complete(base):
    """True when a previous run already produced usable analysis outputs."""
    an = os.path.join(base, 'output', 'analysis')
    need = ['shots.json', 'analysis.jsonl', 'raw_visibility.json',
            'grouped_scenes.json', 'export_plan.json', 'qc.json']
    return all(os.path.exists(os.path.join(an, f)) for f in need)


def run_step(script, env, expect=None, timeout=3600):
    t0 = time.time()
    log(f'>>> {script}')
    p = subprocess.run([sys.executable, os.path.join(SCRIPTS, script)],
                       capture_output=True, text=True, env=env, timeout=timeout)
    tail = '\n'.join((p.stdout or '').strip().splitlines()[-6:])
    if tail:
        print(tail, flush=True)
    if p.returncode != 0:
        raise RuntimeError(f'{script} failed rc={p.returncode}\n{(p.stderr or "")[-800:]}')
    if expect and expect not in (p.stdout or ''):
        raise RuntimeError(f'{script}: sentinel "{expect}" missing in output')
    log(f'<<< {script} done in {time.time()-t0:.0f}s')
    return p.stdout


def run_pipeline(base, target, video_id, video_url, pad=5.0,
                 skip_analysis=False, step_timeout=3600, maxh=1080):
    env = dict(os.environ)
    env.update({'CCE_BASE': base, 'CCE_TARGET': target,
                'CCE_VIDEO_ID': video_id, 'CCE_VIDEO_URL': video_url,
                'CCE_PAD': str(pad), 'CCE_MAXH': str(maxh)})
    os.makedirs(os.path.join(base, 'output', 'analysis'), exist_ok=True)
    os.makedirs(os.path.join(base, 'output', 'reports'), exist_ok=True)

    for script, sentinel in PIPELINE:
        if skip_analysis and script in ('01_detect_shots.py', '02_analyze_faces.py',
                                        '03_raw_visibility.py', '04_audio_activity.py',
                                        '04b_fetch_captions.py', '05_group_scenes.py'):
            log(f'--skip-analysis: {script} skipped (reusing existing outputs)')
            continue
        # 02 is the long CPU step; honor skip flag when analysis already complete
        if script == '02_analyze_faces.py' and skip_analysis:
            continue
        run_step(script, env, sentinel, timeout=step_timeout)
    return True
