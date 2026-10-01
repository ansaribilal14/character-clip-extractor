"""Run the full character-centric clip pipeline inside a workspace.

Steps (scripts/ shipped alongside the package):
  00 normalize -> 01 shot detection -> 02 face analysis @2fps ->
  03 RAW visibility -> 04 voice activity -> 04b captions ->
  05 scene continuity grouping -> 06 export (CRF16) -> 06b contact sheet ->
  07 QC -> 08 reports -> 10 concat into ONE full per-episode video

AUTO-RESUME: every step has an on-disk sentinel. run_pipeline(resume=True)
(default) skips any step whose sentinel already exists, so an interrupted
run continues where it stopped — just re-run the same command. Step 02 has
its own frame-level resume inside analysis.jsonl, so even multi-minute CPU
analysis survives interruption without losing work.

Env contract with the scripts:
  CCE_BASE      workspace root          CCE_TARGET    character slug
  CCE_VIDEO_ID  youtube id              CCE_VIDEO_URL canonical url
  CCE_PAD       export padding seconds  CCE_MAXH      max height
"""
import json
import os
import subprocess
import sys
import time

PKG_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(PKG_DIR)
SCRIPTS = os.environ.get('CCE_SCRIPTS', os.path.join(REPO, 'scripts'))

PIPELINE = [
    ('00_normalize.py', 'NORMALIZE_OK'),
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

# on-disk sentinels used for auto-resume
AN = 'output/analysis'
SENTINELS = {
    '00_normalize.py': [f'{AN}/normalized.mp4'],
    '01_detect_shots.py': [f'{AN}/shots.json'],
    '02_analyze_faces.py': [f'{AN}/analysis.jsonl'],      # frame-resume inside
    '03_raw_visibility.py': [f'{AN}/raw_visibility.json'],
    '04_audio_activity.py': [f'{AN}/audio_activity.json'],
    '05_group_scenes.py': [f'{AN}/grouped_scenes.json'],
    '06_export_clips.py': [f'{AN}/export_plan.json'],     # verified below
    '06b_contact_sheet.py': ['output/reports/clip_contact_sheet.jpg'],
    '07_qc.py': [f'{AN}/qc.json'],
    '08_reports.py': ['output/reports/report.html'],
    '10_concat_full.py': [f'{AN}/full_video.json'],
}


def log(msg):
    print(f'[runner] {msg}', flush=True)


def _s06_complete(base):
    """06 is complete only when every planned window was exported OK."""
    p = os.path.join(base, AN, 'export_plan.json')
    if not os.path.exists(p):
        return False
    try:
        d = json.load(open(p))
        return bool(d.get('clips')) and all(c.get('export_ok') for c in d['clips'])
    except Exception:
        return False


def step_complete(base, script):
    paths = SENTINELS.get(script)
    if not paths:
        return False
    if script == '06_export_clips.py':
        return _s06_complete(base)
    for rel in paths:
        p = os.path.join(base, rel)
        if not os.path.exists(p):
            return False
        if rel.endswith('analysis.jsonl') and os.path.getsize(p) == 0:
            return False
    return True


def analysis_complete(base):
    """True when a previous run already produced usable analysis outputs."""
    need = ['shots.json', 'analysis.jsonl', 'raw_visibility.json',
            'grouped_scenes.json', 'export_plan.json', 'qc.json']
    an = os.path.join(base, 'output', 'analysis')
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
                 skip_analysis=False, step_timeout=3600, maxh=1080,
                 resume=True):
    """Run all pending steps. resume=True (default) skips completed steps,
    so re-invoking after an interruption continues automatically."""
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
        if resume and step_complete(base, script):
            log(f'resume: {script} already complete — skipped')
            continue
        run_step(script, env, sentinel, timeout=step_timeout)
    return True
