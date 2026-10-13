"""Package final deliverables into a ZIP the user can download/share.

ZIP layout (full-video mode — the deliverable is ONE video per episode):
  <target>_clips.zip
    FULL_<target>_<video_id>.mp4   (complete character cut of the episode)
    thumbs/scene_XXX.jpg           (peak-visibility thumbnails)
    reports/timeline.json          (RAW + GROUPED timestamp sets)
    reports/matches.json
    reports/report.csv
    reports/report.html
    reports/WORKLOG.md
    reports/clip_contact_sheet.jpg
    SUMMARY.txt                    (human-readable run summary)
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
        fv = json.load(open(os.path.join(an, 'full_video.json')))
        lines += [
            f'RAW {target.upper()} VISIBILITY: {len(raw["intervals"])} intervals, '
            f'{raw["total_visible_s"]:.1f}s total',
            f'GROUPED {target.upper()} SCENES: {len(grouped["scenes"])} scenes '
            f'-> FULL video with {fv["n_windows"]} windows '
            f'({fv["duration_s"]:.0f}s, {fv["resolution"]}, {fv["size_mb"]:.0f}MB)',
            '',
            'Scene timestamps:',
        ]
        for s in grouped['scenes']:
            lines.append(f"  {s['scene_id']}: {s['start']:.1f}s - {s['end']:.1f}s "
                         f"(visible {s['raw_visible_s']:.1f}s, conf {s['confidence']:.2f})")
        lines += ['', 'Notes:',
                  '- ONE full video per episode: union of padded visibility windows, '
                  'chronological, nothing of the character cut',
                  '- exported at CRF16/preset medium (visually lossless vs source)',
                  '- voice activity evidence is energy-based only (no speaker identity)',
                  '- see reports/WORKLOG.md for honest limitations per run']
    except Exception as e:
        lines.append(f'(summary unavailable: {e})')
    return '\n'.join(lines)


def make_zip(base, target, video_url, out_path=None):
    clips_dir = os.path.join(base, 'output', 'clips', target)
    rep_dir = os.path.join(base, 'output', 'reports')
    an = os.path.join(base, 'output', 'analysis')
    if not out_path:
        dist = os.path.join(base, 'dist')
        os.makedirs(dist, exist_ok=True)
        out_path = os.path.join(dist, f'{target}_clips.zip')

    full = None
    fv_path = os.path.join(an, 'full_video.json')
    if os.path.exists(fv_path):
        fv = json.load(open(fv_path))
        p = os.path.join(clips_dir, fv['full_video'])
        if os.path.exists(p):
            full = p

    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_STORED) as z:  # STORED: mp4 already compressed
        if full:
            z.write(full, arcname=os.path.basename(full))
        for f in sorted(os.listdir(clips_dir)) if os.path.isdir(clips_dir) else []:
            if f.endswith('.jpg'):
                z.write(os.path.join(clips_dir, f), arcname=f'thumbs/{f}')
        for f in sorted(os.listdir(rep_dir)) if os.path.isdir(rep_dir) else []:
            if f.endswith(('.json', '.csv', '.html', '.md', '.jpg')):
                z.write(os.path.join(rep_dir, f), arcname=f'reports/{f}')
        z.writestr('SUMMARY.txt', summarize(base, target, video_url))
    size_mb = os.path.getsize(out_path) / 1e6
    print(f'[packager] ZIP: {out_path} ({size_mb:.1f} MB)')
    return out_path
