#!/bin/bash
# Master pipeline runner — MODE B (Ahyeon scenes)
set -e
S=/home/z/my-project/clipextractor/scripts
A=/home/z/my-project/clipextractor/output/analysis
cd /home/z/my-project
echo "=== 00 normalize ==="; python3 $S/00_normalize.py | tee -a $A/../logs/pipeline.log
echo "=== 01 shots ===";    python3 $S/01_detect_shots.py | tee -a $A/../logs/pipeline.log
echo "=== 02 faces ===";    python3 $S/02_analyze_faces.py | tee -a $A/../logs/pipeline.log
echo "=== 03 raw vis ===";  python3 $S/03_raw_visibility.py | tee -a $A/../logs/pipeline.log
echo "=== 04 audio ===";    python3 $S/04_audio_activity.py | tee -a $A/../logs/pipeline.log
echo "=== 04b captions ===";python3 $S/04b_fetch_captions.py | tee -a $A/../logs/pipeline.log || true
echo "=== 05 group ===";    python3 $S/05_group_scenes.py | tee -a $A/../logs/pipeline.log
echo "=== 06 export ===";   python3 $S/06_export_clips.py | tee -a $A/../logs/pipeline.log
echo "=== 07 qc ===";       python3 $S/07_qc.py | tee -a $A/../logs/pipeline.log
echo "=== 08 reports ===";  python3 $S/08_reports.py | tee -a $A/../logs/pipeline.log
echo "PIPELINE_ALL_OK"
