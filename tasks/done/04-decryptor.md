# 04 - Decryptor Module (Phase 1)

## Background
`decryptor.py` turns every input audio file into a DRM-free file. It must also report chapter info for later steps (see task 05).

## What to do
1. `detect_format(path)`: identify `.aax`, `.aaxc`, `.m4b`, `.mp3` by extension and by file header (use `ffprobe`; don't trust the extension alone).
2. `decrypt(path, out_dir, activation_bytes=None, key=None, iv=None) -> Path`:
   - `.m4b` / `.mp3`: return the input path unchanged (no copy).
   - `.aax`: `ffmpeg -activation_bytes <hex> -i in.aax -vn -c:a copy out.m4b`.
   - `.aaxc`: same, using `-audible_key` and `-audible_iv`.
3. Fail with a clear error if the needed keys are missing, if `ffmpeg` is not installed, or if FFmpeg returns non-zero. Include FFmpeg's stderr in the error.
4. Never modify or delete the input file. Skip work if the output already exists in the work dir (cache).
5. Wire it into the CLI.

## Acceptance Criteria
- [x] DRM-free input is returned untouched and no new file is written.
- [x] Detection works on fixtures even when the extension is renamed.
- [x] A missing key for an `.aax` file gives a clear error.
- [x] A missing ffmpeg gives a clear error.
- [x] Unit tests mock `subprocess` and check the exact FFmpeg command line for `.aax` and `.aaxc`.
- [x] Output keeps chapter metadata (`ffprobe -show_chapters` still lists chapters) when the source had them.

