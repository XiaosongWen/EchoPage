# Findings & Decisions: Task 04 Decryptor

## Requirements Analysis
From `tasks/04-decryptor.md`:
1. `detect_format(path)`:
   - Identify `.aax`, `.aaxc`, `.m4b`, `.mp3` by extension and file header using `ffprobe`.
   - Never trust extension alone; must work on renamed files.
2. `decrypt(path, out_dir, activation_bytes=None, key=None, iv=None) -> Path`:
   - `.m4b` / `.mp3`: return input path unchanged (no copy, no files written).
   - `.aax`: `ffmpeg -activation_bytes <hex> -i in.aax -vn -c:a copy out.m4b`.
   - `.aaxc`: `ffmpeg -audible_key <key> -audible_iv <iv> -i in.aaxc -vn -c:a copy out.m4b`.
3. Error handling:
   - Missing required keys -> clear error.
   - Missing `ffmpeg` -> clear error.
   - Non-zero FFmpeg return -> clear error containing FFmpeg stderr.
4. Caching & Immutability:
   - Never modify or delete input file.
   - Skip work if output exists in work dir.
5. CLI wiring:
   - Wire `decryptor.decrypt` into CLI `echopage build`.

## Research Findings
- **Container Structure**:
  - MP4/MOV container files start with `ftyp` atom at offset 4.
  - Bytes 8..12 specify `major_brand`:
    - Audible AAX: `aax ` (or compatible brands containing `aax `)
    - Audible AAXC: `aaxc` (or compatible brands containing `aaxc`)
    - Standard M4B / M4A: `M4A `, `M4B `, `mp42`, `isom`
  - MP3 files start with ID3 tag `b"ID3"` or MPEG frame sync header `0xFF 0xFB/F3/F2`.
- **FFprobe Capabilities**:
  - `ffprobe -v error -show_format -of json <path>` returns:
    - `format_name`: `"mov,mp4,m4a,3gp,3g2,mj2"` for MP4 containers, `"mp3"` for MP3.
    - `tags.major_brand` & `tags.compatible_brands`: correctly exposed for all MP4-based formats including AAX/AAXC even when files are renamed to `.bin` or `.mp3`.
- **Stream Copying & Chapter Metadata**:
  - Executing `ffmpeg -i in -vn -c:a copy out.m4b` carries over all embedded chapter metadata without decoding/re-encoding audio.
  - Probing with `ffprobe -show_chapters -of json out.m4b` confirms identical chapter timestamps and titles are preserved.

## Technical Decisions
| Decision | Rationale |
|---|---|
| `AudioFormat` inherits from `str` | Supports `fmt == ".m4b"` and `fmt == "m4b"` seamlessly. |
| Multi-tier format detection: `ffprobe` -> binary header -> extension | Maximizes accuracy with `ffprobe` while gracefully handling synthetic/unit test files. |
| Strict command line construction | Exactly matches `ffmpeg -activation_bytes <hex> -i in.aax -vn -c:a copy out.m4b` and `-audible_key` / `-audible_iv`. |
| `DecryptionError(RuntimeError)` | Provides actionable error messages with FFmpeg stderr attached. |
| Output filename convention | `Path(out_dir) / f"{Path(path).stem}.m4b"`. Cache check uses `out_path.is_file()`. |
