"""Voice-activity estimation via ffmpeg silencedetect (energy based).

IMPORTANT LIMITATION (by design): this provides voice ACTIVITY only.
It does NOT and CANNOT identify who is speaking, nor provide dialogue
understanding. Speaker identity is NOT claimed anywhere downstream.

Input : output/analysis/normalized.mp4
Output: output/analysis/audio_activity.json
  {speech_intervals:[{start,end}], silence_intervals:[{start,end}], params}
"""
import json, subprocess, re, os

BASE = os.environ.get('CCE_BASE', '/home/z/my-project/clipextractor')
VIDEO = f'{BASE}/output/analysis/normalized.mp4'
OUT = f'{BASE}/output/analysis/audio_activity.json'
NOISE_DB = -30      # speech threshold
MIN_SILENCE = 0.6   # silences shorter than this are ignored (kept as speech)

cmd = ['ffmpeg', '-hide_banner', '-nostats', '-vn', '-i', VIDEO,
       '-af', f'silencedetect=noise={NOISE_DB}dB:d={MIN_SILENCE}',
       '-f', 'null', '-']
p = subprocess.run(cmd, capture_output=True, text=True)
err = p.stderr

starts = [float(m) for m in re.findall(r'silence_start:\s*([\d.]+)', err)]
ends = [float(m) for m in re.findall(r'silence_end:\s*([\d.]+)', err)]

sil = []
for i, s in enumerate(starts):
    e = ends[i] if i < len(ends) else None
    sil.append([s, e])

# derive video duration
probe = subprocess.run(['ffprobe', '-v', 'quiet', '-print_format', 'json',
                        '-show_format', VIDEO], capture_output=True, text=True)
dur = float(json.loads(probe.stdout)['format']['duration'])

closed, open_s = [], None
for s, e in sil:
    if e is None:
        open_s = s
    else:
        closed.append([s, e])
if open_s is not None:
    closed.append([open_s, dur])

# speech = complement of silence
speech, prev = [], 0.0
for s, e in closed:
    if s - prev > 0.05:
        speech.append([round(prev, 2), round(s, 2)])
    prev = e
if dur - prev > 0.05:
    speech.append([round(prev, 2), round(dur, 2)])

speech = [[a, b] for a, b in speech if b - a >= 0.3]

with open(OUT, 'w') as f:
    json.dump({'speech_intervals': speech,
               'silence_intervals': [[round(a, 2), round(b, 2)] for a, b in closed],
               'params': {'noise_db': NOISE_DB, 'min_silence_s': MIN_SILENCE,
                          'video_duration': round(dur, 2)},
               'note': 'Energy-based voice activity ONLY. Does NOT identify '
                       'speakers or provide dialogue understanding.'}, f, indent=1)
sp = sum(b - a for a, b in speech)
print(f'AUDIO speech={len(speech)} intervals, {sp:.1f}s active of {dur:.1f}s')
print('AUDIO_OK')
