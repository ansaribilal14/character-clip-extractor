# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.3.0] - 2026-10-01

### Added
- **Full per-episode output mode** (`10_concat_full.py`): all padded Ahyeon
  windows are union-merged (no duplicated overlap content) and concatenated
  chronologically into ONE video per episode — the requested behaviour
  "a whole video each with ahyeon scenes, without cutting any scene".
- **Unified delivery module** (`character_clip_extractor/delivery.py`):
  every artifact travels one path. ≤ 49 MB → Telegram document; larger →
  storage.to anonymous upload (single PUT or multipart with per-part
  retries + ETag collection + abort on unrecoverable failure) and a
  Telegram message with filename, size, expiry and clickable link.
  Persistent X-Visitor-Token, never exposed. Local files deleted after
  confirm unless `--keep-files`. Files are never split into Telegram
  chunks and never transcoded just to fit a limit.
- **Auto-resume pipeline**: every step has an on-disk sentinel
  (`runner.step_complete`); `run_pipeline(resume=True)` (now the default)
  skips completed steps, so re-running the same CLI command continues an
  interrupted run without any manual staging.
- Bundled `LICENSE` (MIT) and this changelog; professional README rewrite
  with pipeline/quality/delivery/limitations documentation.

### Fixed
- `downloader.pot_alive()` now treats ANY HTTP answer from the BGutil POT
  provider (it returns 400 on `/`) as "running" — previously the provider
  was needlessly respawned every cycle and startup could stall 30 s.
- `09_telegram_send.py` no longer transcodes or drops large videos; it
  routes everything through the unified delivery path.

### Changed
- CLI: delivery is now on by default (`--no-deliver` to opt out);
  `--keep-files` added; `--tg-send` kept as a legacy alias.
- Version metadata and package description updated to match the
  per-episode output mode.

## [0.2.0] - 2026-10-01

### Added
- Generic character support: any character slug from user photos, bundled
  references, or auto-search (`refs.py`).
- Inbuilt ytagent downloader with BGutil POT provider auto-start, spaced
  retries, ffprobe A/V parity verification and truncated-file re-download.
- One-command CLI (`character-clip-extractor` / `python -m
  character_clip_extractor`) producing a ZIP (clips + reports + SUMMARY).
- HQ re-export standard: libx264 `-preset medium -crf 16` + AAC 192k
  everywhere (replacing ultrafast/CRF22), atomic writes, `.done` stamps.

### Changed
- All pipeline scripts parameterized via env (`CCE_BASE`, `CCE_TARGET`,
  `CCE_VIDEO_ID`, `CCE_VIDEO_URL`, `CCE_PAD`); output keys rename with the
  target character.

## [0.1.0] - 2026-09-30

### Added
- Initial MVP for a single video: PySceneDetect shots, InsightFace
  buffalo_l @ 2 fps matching, RAW visibility with bridging, YouTube captions
  fetch, multi-evidence scene-continuity grouping, CRF16 export, contact
  sheets, QC, HTML/CSV/JSON reports with RAW + GROUPED timestamps.
