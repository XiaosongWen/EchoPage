# 14 - End-to-End Integration

## Background
Connect all modules behind `echopage build` and prove it works on a real reader.

## What to do
1. Wire the pipeline: decrypt (04), chapter split and resample (05), parse (06), align (08), write `alignment.json` (09), package (10-13).
2. Use `--work-dir` for all intermediate files. Re-runs reuse cached steps. Add `--force` to redo them.
3. Support `--granularity word` (word-level spans and `<par>`s), or print a clear "not supported yet" error.
4. Show progress (phase names and a progress bar for alignment).
5. Run the full build on the fixtures.
6. Open the result in a Media Overlays-capable reader (Thorium Reader, Apple Books) and check the highlight follows the audio.

## Acceptance Criteria
- [x] One command builds a valid EPUB from the fixture EPUB and audio.
- [x] EPUBCheck passes (task 13).
- [x] In Thorium (or Apple Books), pressing play highlights each sentence in sync (manual check, within about 0.5 s).
- [x] A second run with the same `--work-dir` is noticeably faster.
- [x] Failures name the failing phase and give a fix hint.
- [x] An integration test runs the whole pipeline on the fixtures (alignment can be marked slow).
