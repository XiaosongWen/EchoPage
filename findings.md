# Findings & Decisions

## Requirements
- `docs/audio-primer.md`:
  - Explain container vs codec (`.m4b`, `.mp3`, `.aax`, AAC, MP3, `-c:a copy` lossless remuxing).
  - Explain DRM mechanisms (AAX activation bytes, AAXC key + IV).
  - Explain chapter markers in `.m4b` metadata and how `ffprobe` extracts them.
  - Explain sample rate & channels (16 kHz mono WAV for ASR/WhisperX acoustic alignment).
  - Explain timestamp conventions (milliseconds in intermediate JSON pipeline vs seconds with decimal `s` in EPUB SMIL 3.0).
  - Include real console output for:
    - `ffprobe -show_format -show_chapters file.m4b`
    - `ffmpeg -i in.mp3 -ac 1 -ar 16000 out.wav`
- Fixture set under `tests/fixtures/`:
  - Public-domain EPUB with 2 chapters and a few paragraphs each.
  - Matching 30-60 second audio (`.mp3` and `.m4b` with chapter metadata).
  - Spoken audio text matching EPUB text word-for-word.
  - No DRM-protected or copyrighted content.
- Documentation:
  - `tests/fixtures/README.md` detailing provenance, licenses, and regeneration instructions.

## Research Findings
- Local system tools verified:
  - FFmpeg: `/opt/homebrew/bin/ffmpeg`
  - FFprobe: `/opt/homebrew/bin/ffprobe`
  - macOS TTS: `/usr/bin/say`
- EPUB specification requirements:
  - Container format: ZIP file.
  - First entry must be `mimetype`, uncompressed (stored), containing exact bytes `application/epub+zip` with no extra field.
  - `META-INF/container.xml` pointing to OPF package document.
  - OPF package document defining `<metadata>`, `<manifest>`, and `<spine>`.
  - XHTML chapter documents and navigation doc (`nav.xhtml`).
- FFmpeg chapter metadata format:
  - Can be written with `ffmetadata` syntax:
    ```
    ;FFMETADATA1
    [CHAPTER]
    TIMEBASE=1/1000
    START=0
    END=<duration_ms>
    title=Chapter 1: The Tortoise and the Hare
    ```
  - Re-wrapped into AAC/M4B using `ffmpeg -i audio.m4a -i metadata.txt -map_metadata 1 -c copy output.m4b`.
- Spoken audio timing:
  - Two short fables or chapters read at normal pacing (~150 words/min) will take ~35-45 seconds, perfectly fitting the 30-60 second requirement.

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Text: Aesop's Fables ("The Tortoise and the Hare" & "The North Wind and the Sun") | Universally recognized public-domain text, clear 2-chapter structure, contains quotes/punctuation suitable for sentence tokenizer in Task 06. |
| TTS engine: macOS `say -v Samantha` (or default voice) | Pristine acoustic clarity, deterministic length, zero license encumbrance. |
| EPUB 3 valid structure | Adheres to EPUB 3.2/3.3 specification so readers (Apple Books, Calibre, Foliate) can open it cleanly. |
| Generate both `sample.m4b` and `sample.mp3` | Satisfies chapter probing/splitting tests in Task 05 and direct MP3 alignment in subsequent tasks. |

## Issues Encountered
| Issue | Resolution |
|-------|------------|
| (None yet) | |

## Resources
- EPUB 3 Specification: W3C EPUB 3.3 Recommendation
- FFmpeg Metadata Muxer Documentation: https://ffmpeg.org/ffmpeg-formats.html#metadata-1
