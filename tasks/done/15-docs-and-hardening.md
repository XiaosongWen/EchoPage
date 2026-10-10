# 15 - Docs & Hardening

## What to do
1. README: install, prerequisites (FFmpeg, Java and EPUBCheck, optional WhisperX), a quick start with the example command, flags table and troubleshooting.
2. Explain how to get Audible activation bytes (link to the tool/community docs), and add a "personal use of content you own only" legal note about DRM.
3. Test on a real full-length book (about 10+ hours) that you own. Record memory use and time, and fix problems (chunk long audio, avoid loading everything in RAM).
4. Handle edge cases: no chapter markers, audio and chapter count mismatch, EPUB 2 input, front matter not in the audio (let the user skip spine items with `--skip-spine ID,...`).
5. Add `--dry-run`, which parses the EPUB and probes the audio and prints the planned chapter-to-audio mapping without aligning.

## Acceptance Criteria
- [x] A new user can follow the README from clone to first built EPUB.
- [x] The legal note is present.
- [x] A full-length book builds without running out of memory, and the time and RAM are noted in the docs.
- [x] `--skip-spine` and `--dry-run` work, with tests.
- [x] `pytest` passes and EPUBCheck passes on the final sample output.
