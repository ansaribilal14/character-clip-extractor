#!/bin/bash
# Single retry attempt + report. Exit 0 and print DOWNLOAD_SUCCESS if a video file exists.
cd /home/z/my-project
ytagent setup >/dev/null 2>&1
ytagent download "https://youtu.be/9G3BYRKujo8" \
  --out-dir /home/z/my-project/clipextractor/output/source \
  --format "bv*[ext=mp4][height<=720]+ba[ext=m4a]/bv*[height<=720]+ba/b[height<=720]/b" \
  --json --timeout 240 >/tmp/dl_last.json 2>&1
N=$(ls /home/z/my-project/clipextractor/output/source/ 2>/dev/null | grep -cE "\.(mp4|mkv|webm)$")
if [ "$N" -gt 0 ]; then echo DOWNLOAD_SUCCESS; ls -la /home/z/my-project/clipextractor/output/source/; else echo STILL_BLOCKED; grep -oE '"reason":[^,}]{0,80}' /tmp/dl_last.json | head -3; fi
