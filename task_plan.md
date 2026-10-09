# Task Plan: 04 - Decryptor Module (Phase 1)

## Goal
Implement `echopage/decryptor.py` to detect container formats (`.aax`, `.aaxc`, `.m4b`, `.mp3`) by extension and header using `ffprobe`, decrypt encrypted Audible files via FFmpeg stream copying without modifying inputs, support work dir caching, handle error cases cleanly with FFmpeg stderr, wire into the CLI, and verify all acceptance criteria.

## Current Phase
Phase 5 (Complete)

## Phases

### Phase 1: Requirements Analysis & Test Plan Design
- [x] Analyze `tasks/04-decryptor.md`, PRD specifications, and existing CLI wiring
- [x] Inspect container headers (`ftyp`, `major_brand`) and FFmpeg decryption flags (`-activation_bytes`, `-audible_key`, `-audible_iv`)
- [x] Establish test fixtures for `.aax` and `.aaxc` alongside existing `.m4b` and `.mp3`
- **Status:** complete

### Phase 2: Format Detection Implementation (`detect_format`)
- [x] Design `AudioFormat` string-compatible class allowing comparison with/without leading dot
- [x] Implement `detect_format(path)` using `ffprobe` format and tags (`major_brand`, `compatible_brands`, `format_name`)
- [x] Implement robust binary header sniffing fallback (`ID3`, `syncword`, `ftyp` box)
- [x] Ensure detection works on files with arbitrary / mismatched extensions
- **Status:** complete

### Phase 3: Decryption & Caching Implementation (`decrypt`)
- [x] Implement `decrypt(path, out_dir, activation_bytes=None, key=None, iv=None)` and `decrypt_file`
- [x] Bypass conversion for DRM-free `.m4b` and `.mp3` (return original input path untouched, write no files)
- [x] Construct exact FFmpeg commands:
  - `.aax`: `ffmpeg -activation_bytes <hex> -i in.aax -vn -c:a copy out.m4b`
  - `.aaxc`: `ffmpeg -audible_key <key> -audible_iv <iv> -i in.aaxc -vn -c:a copy out.m4b`
- [x] Implement cache checking: skip work if `out_path` exists in work dir
- [x] Implement error handling: missing keys, missing `ffmpeg`, non-zero return with stderr captured in `DecryptionError`
- **Status:** complete

### Phase 4: CLI Wiring & Parameter Compatibility
- [x] Support both single-path and list-of-paths in `decrypt` to cleanly support `cli.py` (`args.audio`)
- [x] Ensure keyword aliases (`audible_key`, `audible_iv`, `work_dir`) match CLI arguments
- [x] Gracefully catch `DecryptionError` in `cli.main` with user-friendly logging and exit code
- **Status:** complete

### Phase 5: Testing & Acceptance Verification
- [x] Write unit tests mocking `subprocess.run` to verify exact FFmpeg commands for `.aax` and `.aaxc`
- [x] Write tests verifying clear errors on missing key, missing ffmpeg, and non-zero ffmpeg exit code with stderr
- [x] Test format detection on fixtures with renamed/mismatched extensions
- [x] Test DRM-free untouched passthrough and no-file-written behavior
- [x] Test cache hit behavior
- [x] Test chapter metadata preservation on real remuxed output
- [x] Run full test suite with `pytest` (29 passed)
- [x] Check off acceptance criteria in `tasks/04-decryptor.md`
- **Status:** complete

## Key Questions
1. How does `detect_format` distinguish between `.aax`, `.aaxc`, and `.m4b` when files are renamed?
   - In ISO Base Media containers, the `ftyp` atom defines `major_brand` and `compatible_brands`. `ffprobe` extracts these tags: `aax ` indicates `.aax`, `aaxc` indicates `.aaxc`, and `M4A `/`M4B `/`mp42` indicates `.m4b`.
2. What happens if `out_dir` already contains the decrypted output?
   - Skip FFmpeg execution and immediately return the cached output path.

## Decisions Made
| Decision | Rationale |
|---|---|
| Use `AudioFormat(str)` subclass | Permits seamless comparisons `== ".m4b"` and `== "m4b"` without breaking string checks or callers expecting either convention |
| Support both single `Path` and `list[Path]` in `decrypt()` | Allows clean single-file API as per task 04 spec while maintaining CLI multi-file support without extra wrappers |
| `DecryptionError` inherits from `RuntimeError` | Provides specific exception type while adhering to standard Python exception hierarchies |
| Synthetic `.aax` / `.aaxc` fixtures created from valid audio containers | Tests run deterministic header detection using real `ffprobe` without needing pirated or copyrighted files |

## Errors Encountered
| Error | Attempt | Resolution |
|---|---|---|
| `NameError: name 'Path' is not defined` in `test_cli.py` | 1 | Imported `Path` from `pathlib` in `tests/test_cli.py` |
