"""Package final deliverables into a ZIP the user can download/share.

ZIP layout:
  <target>_clips.zip
    clips/scene_XXX.mp4        (best-quality CRF16 exports)
    clips/scene_XXX.jpg        (peak-visibility thumbnails)
    reports/timeline.json      (RAW + GROUPED timestamp sets)
    reports/matches.json
    reports/report.csv
    reports/report.html
    reports/WORKLOG.md
    reports/clip_contact_sheet.jpg
    SUMMARY.txt                (human-readable run summary)
"""
import json, os, zipfile

PKG_DIR = os.path.dirname(os.path.abspath(__file__))


def summarize(base, target, video_url):
    an = os.path.join(base, 'output', 'analysis')
    lines = [f'Character-centric clip extraction — {target}',
             f'Video: {video_url}', '']
    try:
        raw = json.load(open(os.path.join(an, 'raw_visibility.json')))
        grouped = json.load(open(os.path.join(an, 'grouped_scenes.json')))
        qc = json.load(open(os.path.join(an, 'qc.json')))
        lines += [
            f'RAW {target.upper()} VISIBILITY: {len(raw["intervals"])} intervals, '
            f'{raw["total_visible_s"]:.1f}s total',
            f'GROUPED {target.upper()} SCENES: {len(grouped["scenes"])} scenes '
            f'-> {qc["n_ok"]} clips exported (5s padding)',
            '',
            'Scene timestamps:',
        ]
        for s in grouped['scenes']:
            lines.append(f"  {s['scene_id']}: {s['start']:.1f}s - {s['end']:.1f}s "
                         f"(visible {s['raw_visible_s']:.1f}s, conf {s['confidence']:.2f})")
        lines += ['', 'Notes:',
                  '- clips are re-encoded at CRF16/preset medium (visually lossless '
                  'vs the 720p source)',
                  '- voice activity evidence is energy-based only (no speaker identity)',
                  '- see reports/WORKLOG.md for honest limitations per run']
    except Exception as e:
        lines.append(f'(summary unavailable: {e})')
    return '\n'.join(lines)


def make_zip(base, target, video_url, out_path=None):
    clips_dir = os.path.join(base, 'output', 'clips', target)
    rep_dir = os.path.join(base, 'output', 'reports')
    if not out_path:
        dist = os.path.join(base, 'dist')
        os.makedirs(dist, exist_ok=True)
        out_path = os.path.join(dist, f'{target}_clips.zip')

    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_STORED) as z:  # STORED: mp4 already compressed
        for f in sorted(os.listdir(clips_dir)) if os.path.isdir(clips_dir) else []:
            if f.endswith(('.mp4', '.jpg')):
                z.write(os.path.join(clips_dir, f), arcname=f'clips/{f}')
        for f in sorted(os.listdir(rep_dir)) if os.path.isdir(rep_dir) else []:
            if f.endswith(('.json', '.csv', '.html', '.md', '.jpg')):
                z.write(os.path.join(rep_dir, f), arcname=f'reports/{f}')
        z.writestr('SUMMARY.txt', summarize(base, target, video_url))
    size_mb = os.path.getsize(out_path) / 1e6
    print(f'[packager] ZIP: {out_path} ({size_mb:.1f} MB)')
    return out_path
