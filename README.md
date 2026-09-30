# Character Clip Extractor

Turn a **video link + a character** (name or reference photos) into **scene-continuous
clips** of that character — at the **best available quality**, packaged as a **ZIP**.

Built for the hard problem: a naive "cut when the face appears, cut when it disappears"
pipeline produces dozens of sub-second fragments. This system separates **SHOT ≠ SCENE**:

1. **Download** — inbuilt [`ytagent`](https://github.com/Bilal140202/ytagent) engine
   (13-method fallback chain + BGutil POT provider) with spaced retries and
   ffprobe A/V-parity verification (truncated downloads are rejected and retried).
2. **Normalize** — lossless remux when the source is already ≤720p H.264/AAC,
   otherwise one CRF18 re-encode.
3. **Shot detection** — PySceneDetect `ContentDetector`.
4. **Face analysis** — InsightFace `buffalo_l` @ 2fps on CPU, matched against
   verified reference centroids (cosine ≥ 0.42).
5. **RAW visibility** — direct recognition intervals (≤0.5s miss-bridging, ≥1.0s minimum).
6. **Evidence** — ffmpeg silencedetect voice activity (energy only — **not** speaker
   identity) + YouTube captions when reachable.
7. **Scene continuity layer** — merges raw intervals into GROUPED scenes using
   multi-evidence scoring: temporal gap, shot adjacency, speech span, caption span,
   member continuity, position/size stability. Hard blocks: gap > 12s or > 2 shot cuts.
8. **Export** — ±5s padding (configurable), overlapping windows merged,
   **libx264 CRF 16 / preset medium / AAC 192k** (visually lossless vs source),
   `+faststart`, atomic writes with resume.
9. **QC + reports** — ffprobe every clip, contact sheet, `timeline.json`
   (RAW + GROUPED timestamp sets), `matches.json`, `report.csv`, `report.html`,
   `WORKLOG.md`.
10. **Package** — everything zipped: `clips/ + reports/ + SUMMARY.txt`.

## Quick start

```bash
pip install -r requirements.txt          # plus ffmpeg on PATH

# a) character with bundled/known references
python -m character_clip_extractor \
    --url https://youtu.be/9G3BYRKujo8 \
    --character ahyeon \
    --out ./workspace

# b) any character, from your own photos
python -m character_clip_extractor \
    --url "https://www.youtube.com/watch?v=XXXX" \
    --character "some_name" \
    --ref-images photo1.jpg photo2.jpg photo3.jpg \
    --out ./workspace

# resume an interrupted run, reusing existing analysis
python -m character_clip_extractor --url ... --character ... \
    --out ./workspace --skip-analysis
```

Output:

```
workspace/
├── output/clips/<character>/scene_XXX.mp4 (+ .jpg thumbnails)
├── output/reports/{timeline.json, matches.json, report.csv,
│                   report.html, WORKLOG.md, clip_contact_sheet.jpg}
└── dist/<character>_clips.zip
```

## CLI options

| Flag | Meaning |
|------|---------|
| `--url` | YouTube link (youtu.be, watch, shorts) |
| `--character` | character slug; must have references unless `--ref-images` |
| `--ref-images` | reference photo(s) or a directory |
| `--auto-refs` | best-effort fancam search (needs reachable YouTube) |
| `--out` | workspace directory |
| `--pad` | padding seconds around scenes (default 5, merged if overlapping) |
| `--max-height` | max download resolution (default 720 — disk/CPU friendly) |
| `--skip-analysis` | reuse existing analysis (resume long runs) |
| `--force-download` | re-download source even if present |
| `--no-zip` | skip packaging |
| `--tg-send` | deliver via Telegram bot (`CCE_TG_TOKEN`, `CCE_TG_CHAT`) |

## Honest limitations

- Voice-activity evidence is **energy-based only**; it never claims speaker identity.
- VLM affordance is not used in this CPU-constrained MVP (recorded as null in evidence).
- If YouTube captions are unreachable (bot checks), caption evidence is absent.
- Sub-threshold glimpses (side profile, backlight, blur) can be missed (FN risk).
- Borderline matches are flagged with their cosine confidence — check the contact
  sheet and `WORKLOG.md` produced per run.

## Layout

```
character_clip_extractor/   # package: cli, inbuilt ytagent downloader, refs, runner, packager
scripts/                    # pipeline steps 00-09 (env-parameterized: CCE_BASE/CCE_TARGET/...)
references/                 # verified face references + centroids (refs_summary.json)
```
