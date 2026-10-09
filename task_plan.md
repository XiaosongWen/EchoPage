# Task Plan: 03 - Audio Basics & Test Fixtures

## Goal
Implement Task 03 by authoring `docs/audio-primer.md`, creating valid public-domain test fixtures (`tests/fixtures/`) with matching EPUB and audio files (including chapter metadata), documenting provenance and licensing in `tests/fixtures/README.md`, testing with real ffmpeg/ffprobe commands, and verifying all acceptance criteria.

## Current Phase
Phase 5 (Complete)

## Phases

### Phase 1: Requirements & Discovery
- [x] Analyze `tasks/03-audio-basics-and-test-fixtures.md` and related tasks (04, 05, 06)
- [x] Inspect existing repo structure, tools (`ffmpeg`, `ffprobe`, `say`), and test suites
- [x] Initialize planning files (`task_plan.md`, `findings.md`, `progress.md`)
- **Status:** complete

### Phase 2: Design & Text/Audio Content Selection
- [x] Select a short public-domain text (Aesop's Fables: "The Tortoise and the Hare" & "The North Wind and the Sun")
- [x] Determine exact chapter text for EPUB and spoken audio (~45.2s total narration)
- [x] Plan EPUB structure (standard EPUB 3: `mimetype`, `META-INF/container.xml`, `package.opf`, nav, XHTML chapters)
- [x] Plan audio assets (`.m4b` with chapter metadata, `.mp3`, 16kHz WAV downsampling)
- **Status:** complete

### Phase 3: Fixture Generation & Validation
- [x] Build valid public-domain EPUB 3 fixtures (`tests/fixtures/book.epub` and `tests/fixtures/sample.epub`)
- [x] Generate audio using macOS `say` and convert with `ffmpeg` into `.m4b` with chapters, `.mp3`, and per-chapter MP3s
- [x] Practice and capture actual `ffprobe` and `ffmpeg` outputs
- [x] Create `tests/fixtures/README.md` detailing sources, tools, and licenses
- **Status:** complete

### Phase 4: Audio Primer Authoring
- [x] Write `docs/audio-primer.md` covering:
  - Container vs Codec (`.m4b`, `.mp3`, `.aax`, AAC, MP3, `-c:a copy`)
  - DRM handling (AAX activation bytes, AAXC key & IV)
  - Chapter markers in `.m4b` and `ffprobe` inspection
  - Sample rate and channel requirements (16 kHz mono WAV for WhisperX/ASR)
  - Timestamps (milliseconds in JSON vs seconds in SMIL `clipBegin`/`clipEnd`)
  - Embedded real command outputs from the fixtures
- **Status:** complete

### Phase 5: Testing & Acceptance Verification
- [x] Write automated tests in `tests/test_fixtures.py` verifying EPUB structure and audio metadata
- [x] Verify EPUB validity and readability
- [x] Verify audio playback and exact text match
- [x] Run full test suite with `pytest` (12 passed)
- [x] Update `tasks/03-audio-basics-and-test-fixtures.md` checklist
- **Status:** complete

## Key Questions
1. What public-domain text provides clean 2-chapter structure under 60s total narration?
   - Two short Aesop fables ("The Tortoise and the Hare" and "The North Wind and the Sun"), yielding ~45.2s total.
2. How to embed chapter metadata in `.m4b` via FFmpeg?
   - Using an FFMETADATA file with `[CHAPTER]` markers (`TIMEBASE=1/1000`, `START`, `END`, `title`) and `-map_metadata`.

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Use macOS `say` (Samantha voice) + `ffmpeg` for audio fixture | 100% deterministic, royalty-free / public-domain, zero network dependency, exact match to EPUB text |
| Generate both `.m4b` (with 2 chapters) and `.mp3` | Directly serves Task 03, Task 04 (format detection), and Task 05 (chapter split) |
| Create valid EPUB 3 structure | Ensures standard EPUB readers can open and parse it; satisfies Task 06 requirements |
| Add comprehensive test suite `tests/test_fixtures.py` | Prevents future regressions and ensures all fixtures remain compliant |

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| Missing `lxml` in default system python | 1 | Ran fixture generation script using project virtualenv `.venv/bin/python3` |

## Notes
- All acceptance criteria in `tasks/03-audio-basics-and-test-fixtures.md` verified and satisfied.
