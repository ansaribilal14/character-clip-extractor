"""One-command entry point.

    python -m character_clip_extractor \
        --url https://youtu.be/XXXX \
        --character Ahyeon \
        [--ref-images photo1.jpg photo2.jpg | --ref-images refs_dir/] \
        [--out ./workspace] [--pad 5] [--max-height 720] \
        [--skip-analysis] [--auto-refs] [--no-zip] [--tg-send]

Give it a video link and a character (name with bundled references, or your
own reference photos) and it produces ONE full per-episode video containing
all of that character's scenes (nothing split, nothing cut) at the best
available quality, plus reports, and delivers it (Telegram <=49MB,
storage.to link above that). Safe to re-run: it resumes automatically.
"""
import argparse, json, os, re, sys, subprocess, time

from . import downloader, refs, runner, packager

PKG_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(PKG_DIR)


def slugify(name):
    s = re.sub(r'[^a-z0-9]+', '_', (name or '').strip().lower()).strip('_')
    return s or 'target'


def full_video_path(base, target):
    fj = os.path.join(base, 'output', 'analysis', 'full_video.json')
    if os.path.exists(fj):
        try:
            name = json.load(open(fj)).get('full_video')
            if name:
                return os.path.join(base, 'output', 'clips', target, name)
        except Exception:
            pass
    return None


def video_id_from_url(url):
    m = (re.search(r'(?:youtu\.be/|v=|shorts/|embed/)([A-Za-z0-9_-]{6,})', url or '')
         or re.fullmatch(r'[A-Za-z0-9_-]{6,}', (url or '').strip()))
    return m.group(1) if m else None


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog='character_clip_extractor',
        description='Video link + character -> scene-continuous clips (ZIP, best quality)')
    ap.add_argument('--url', required=True, help='YouTube video link (youtu.be / watch / shorts)')
    ap.add_argument('--character', default='target',
                    help='character name (slug); must have references available '
                         'unless --ref-images is given')
    ap.add_argument('--ref-images', nargs='+', default=None,
                    help='reference photo(s) or directory of the character')
    ap.add_argument('--auto-refs', action='store_true',
                    help='best-effort fancam search for references (needs reachable YouTube)')
    ap.add_argument('--out', default=os.path.join(REPO, 'workspaces', 'default'),
                    help='workspace directory (default: <repo>/workspaces/default)')
    ap.add_argument('--pad', type=float, default=5.0, help='padding seconds around scenes (default 5)')
    ap.add_argument('--max-height', type=int, default=1080,
                    help='max download height (default 1080; falls back to best available)')
    ap.add_argument('--skip-analysis', action='store_true',
                    help='reuse existing analysis outputs in the workspace (resume)')
    ap.add_argument('--force-download', action='store_true',
                    help='re-download even if the source video already exists')
    ap.add_argument('--no-zip', action='store_true', help='skip final ZIP packaging')
    ap.add_argument('--tg-send', action='store_true',
                    help='(legacy alias) same as the default delivery step')
    ap.add_argument('--no-deliver', dest='deliver', action='store_false',
                    help='skip the automatic delivery step')
    ap.add_argument('--keep-files', action='store_true',
                    help='do not delete local files after a storage.to upload '
                         'is confirmed (default: delete after confirm)')
    args = ap.parse_args(argv)

    t0 = time.time()
    target = slugify(args.character)
    base = os.path.abspath(args.out)
    vid = video_id_from_url(args.url)
    if not vid:
        print(f'ERROR: cannot parse a video id from {args.url!r}')
        return 2
    video_url = f'https://youtu.be/{vid}'
    norm = os.path.join(base, 'output', 'analysis', 'normalized.mp4')
    src_dir = os.path.join(base, 'output', 'source')
    os.makedirs(base, exist_ok=True)
    os.makedirs(os.path.join(base, 'output', 'analysis'), exist_ok=True)
    os.makedirs(src_dir, exist_ok=True)
    print(f'=== character_clip_extractor ===')
    print(f'url      : {video_url}')
    print(f'character: {target}')
    print(f'workspace: {base}')

    # 1) references
    ok, msg = refs.ensure_references(base, target, args.ref_images, args.auto_refs)
    print(f'references: {msg}')
    if not ok:
        return 2

    # 2) download (inbuilt ytagent) unless already present
    if args.force_download or not os.path.exists(norm):
        existing = downloader._pick_verified(src_dir) if os.path.isdir(src_dir) else None
        src = None if args.force_download else existing
        if src:
            print(f'source    : reusing {src}')
        else:
            print('source    : downloading with inbuilt ytagent (spaced retries)...')
            src = downloader.download(args.url, src_dir, args.max_height)
            if not src:
                print('ERROR: download failed after all retries (IP throttle may '
                      'persist; retry later or run with --attempts increased)')
                return 1
        if not os.path.exists(norm):
            env = dict(os.environ); env['CCE_BASE'] = base
            subprocess.run([sys.executable, os.path.join(runner.SCRIPTS, '00_normalize.py'), src],
                           env=env, check=True)

    # 3) pipeline (ends with the FULL per-episode video via 10_concat_full)
    runner.run_pipeline(base, target, vid, video_url, pad=args.pad,
                        skip_analysis=args.skip_analysis, maxh=args.max_height)

    # 4) zip
    zip_path = None
    if not args.no_zip:
        zip_path = packager.make_zip(base, target, video_url)

    # 5) delivery — ONE path for every artifact: files > 49MB are uploaded
    #    to storage.to (anonymous, multipart, link sent via Telegram),
    #    smaller files go out as Telegram documents. Nothing is ever split.
    if args.deliver or args.tg_send:
        from . import delivery
        full = full_video_path(base, target)
        what = zip_path or full
        if what:
            cap = f'character clips: {target} ({video_url})'
            res = delivery.deliver_auto(what, cap, keep=args.keep_files)
            print(f'delivery: {res}')
        else:
            print('delivery: nothing to deliver')

    print(f'=== DONE in {time.time()-t0:.0f}s ===')
    print(f'clips : {base}/output/clips/{target}/')
    print(f'reports: {base}/output/reports/')
    if zip_path:
        print(f'zip   : {zip_path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
