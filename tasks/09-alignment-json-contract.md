# 09 - alignment.json Data Contract

## Background
`alignment.json` is the hand-off between the aligner and the packager (PRD section 3, Phase 2). Fixing it as a schema lets the two sides be built and tested separately.

## What to do
1. Define dataclasses or a JSON Schema for: chapter (`spine_item_id`, `xhtml_filename`, `audio_filename`, `timeline[]`) and entry (`element_id`, `text`, `start_ms`, `end_ms`).
2. Add the fields that the packager will need beyond the PRD sample: `block_xpath`, `char_start`, `char_end` (from task 06) and `confidence`.
3. Write `save_alignment()` and `load_alignment()` with validation: IDs unique, times in order, non-negative, `end_ms > start_ms`.
4. ID scheme: `mo_s_0001`, zero-padded and unique across the book.
5. Add a hand-written sample `tests/fixtures/alignment.sample.json`, so the packager can be built without running WhisperX.

## Acceptance Criteria
- [ ] Round trip (save then load) gives identical data.
- [ ] Validation rejects duplicate IDs, negative times and `end_ms <= start_ms`, each with a clear message.
- [ ] The sample file validates and matches the fixture EPUB.
- [ ] The schema is documented in `docs/alignment-format.md`.
