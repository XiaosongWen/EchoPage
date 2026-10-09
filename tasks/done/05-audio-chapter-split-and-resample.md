# 05 - Audio Chapter Split & Resample

## Background
The aligner needs 16 kHz mono WAV, and the final EPUB needs audio files that map to chapters. Audiobooks come as one big `.m4b` with chapters or as many files. This task defines the audio units used by the rest of the pipeline.

## What to do
1. `probe_chapters(path)`: use `ffprobe -show_chapters -of json` to return `[{title, start_s, end_s}]`. If there are no chapters, treat the file as one unit.
2. `split_audio(path, chapters, out_dir)`: cut with `ffmpeg -ss <start> -to <end> -i in -c copy part_N.m4b` (or mp3). Use stream copy where possible.
3. `to_wav16k(path, out_path)`: `ffmpeg -i in -ac 1 -ar 16000 out.wav`. Use scratch space under the work dir and delete the files after alignment unless `--keep-temp` is set.
4. Return a list of `AudioUnit(path, start_s, end_s, title)` objects.

## Acceptance Criteria
- [x] The fixture file with 2 chapters yields 2 units with correct start/end times (within 0.1 s).
- [x] A file without chapters yields 1 unit.
- [x] The WAV output reports 16000 Hz, 1 channel via `ffprobe`.
- [x] Split parts' total duration is within 0.5 s of the source duration.
- [x] Unit tests cover chapter parsing from canned `ffprobe` JSON.
