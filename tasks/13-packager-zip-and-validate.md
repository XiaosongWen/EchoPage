# 13 - Packager: Zip & Validate

## Background
EPUB readers are strict about the zip layout. The `mimetype` file must be the first entry and must be stored uncompressed.

## What to do
1. Write `mimetype` first, containing exactly `application/epub+zip` (no trailing newline), using `ZIP_STORED`.
2. Add all other files (`META-INF/`, content, SMIL, audio) with `ZIP_DEFLATED`. Audio is already compressed, so `ZIP_STORED` is fine for audio and faster.
3. Write to the `--output` path, creating parent directories.
4. Validate with EPUBCheck (`epubcheck out.epub`; needs Java, `brew install epubcheck`). If it isn't installed, skip with a warning.
5. Report EPUBCheck errors in the CLI output. Exit non-zero on errors.

## Acceptance Criteria
- [ ] `unzip -v out.epub` shows `mimetype` first, with method `Stored`.
- [ ] The `mimetype` content is exact.
- [ ] EPUBCheck reports 0 errors on the fixture build.
- [ ] A missing EPUBCheck gives a warning, not a crash.
- [ ] Output contains no stray files (`.DS_Store`, temp files).
