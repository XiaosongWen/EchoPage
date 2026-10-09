# Test Fixtures

This directory contains lightweight, public-domain test fixtures used across the EchoPage test suite.

## Provenance & Licensing

All fixture assets in this directory are free of copyright restrictions and free of DRM:

| Asset | Source / Origin | License | Description |
|---|---|---|---|
| **Text Content** (`book.epub`) | *Aesop's Fables* ("The Tortoise and the Hare" & "The North Wind and the Sun") via Project Gutenberg | **Public Domain** | Traditional fables published widely and out of copyright. |
| **Audio Narration** (`book.m4b`, `book.mp3`, `ch*.mp3`, `sample_16k.wav`) | Synthesized locally using macOS speech synthesis (`say`, Samantha voice) and encoded via `ffmpeg` | **Public Domain / CC0 equivalent** | Synthetic speech generated directly from the public-domain text without third-party copyright or DRM. |

> **Note on DRM & Copyright**: No commercial, DRM-protected (AAX/AAXC), or copyrighted media is stored in this repository.

---

## Fixture Inventory

### 1. EPUB Fixtures
- [`book.epub`](file:///Users/tomaswen/workspace/EchoPage/tests/fixtures/book.epub) / [`sample.epub`](file:///Users/tomaswen/workspace/EchoPage/tests/fixtures/sample.epub)
  - Compliant EPUB 3 document structure.
  - Contains uncompressed `mimetype` (`application/epub+zip`) as the first entry in the zip archive.
  - Manifest and spine in `EPUB/package.opf` defining reading order:
    1. `chapter01.xhtml` ("Chapter 1: The Tortoise and the Hare")
    2. `chapter02.xhtml` ("Chapter 2: The North Wind and the Sun")
  - Navigation document `EPUB/nav.xhtml` and stylesheet `EPUB/styles.css`.
  - Content includes inline styling elements (`<em>`), dialogue quotes, and abbreviations (`Mr. Fox`) to exercise sentence tokenizers.

### 2. Audio Fixtures
- [`book.m4b`](file:///Users/tomaswen/workspace/EchoPage/tests/fixtures/book.m4b)
  - QuickTime / MP4 container (`.m4b`), AAC codec (22,050 Hz, mono).
  - Total duration: ~45.23 seconds.
  - Embedded metadata chapters:
    - **Chapter 1**: `0.000s` – `23.833s` ("Chapter 1: The Tortoise and the Hare")
    - **Chapter 2**: `23.833s` – `45.159s` ("Chapter 2: The North Wind and the Sun")
- [`book.mp3`](file:///Users/tomaswen/workspace/EchoPage/tests/fixtures/book.mp3)
  - MP3 container, MP3 audio codec (`libmp3lame`, 22,050 Hz, mono).
  - Total duration: ~45.23 seconds.
- [`ch01.mp3`](file:///Users/tomaswen/workspace/EchoPage/tests/fixtures/ch01.mp3) / [`chapter01.mp3`](file:///Users/tomaswen/workspace/EchoPage/tests/fixtures/chapter01.mp3)
  - Chapter 1 standalone audio (~23.83 seconds).
- [`ch02.mp3`](file:///Users/tomaswen/workspace/EchoPage/tests/fixtures/ch02.mp3) / [`chapter02.mp3`](file:///Users/tomaswen/workspace/EchoPage/tests/fixtures/chapter02.mp3)
  - Chapter 2 standalone audio (~21.33 seconds).
- [`sample_16k.wav`](file:///Users/tomaswen/workspace/EchoPage/tests/fixtures/sample_16k.wav)
  - Uncompressed PCM WAV (`pcm_s16le`, 16,000 Hz, mono, 16-bit).
  - Ideal input format for WhisperX forced alignment.

---

## Reproduction Commands

To reproduce these fixtures from scratch:

```bash
# 1. Synthesize chapter speech
say -v Samantha -r 175 "Chapter One. The Tortoise and the Hare. The Hare was once boasting of his speed before the other animals. \"I have never yet been beaten,\" said he, \"when I put forth my full speed. Mr. Fox can witness my victories.\" The Tortoise said quietly, \"I accept your challenge.\" \"That is a good joke,\" said the Hare; \"I could dance round you all the way.\" \"Keep your boasting till you have beaten me,\" answered the Tortoise. \"Shall we race?\"" -o ch01.aiff

say -v Samantha -r 175 "Chapter Two. The North Wind and the Sun. The North Wind and the Sun had a dispute as to which was the most powerful. While they were discussing it, a traveller came along wrapped in a warm cloak. They agreed that the one who first succeeded in making the traveller strip off his cloak should be considered the stronger. The North Wind tried first, but the harder he blew, the closer the traveller held his cloak." -o ch02.aiff

# 2. Encode MP3 chapters
ffmpeg -y -i ch01.aiff -c:a libmp3lame -q:a 2 ch01.mp3
ffmpeg -y -i ch02.aiff -c:a libmp3lame -q:a 2 ch02.mp3

# 3. Concatenate and encode M4B with chapters
ffmpeg -y -f concat -safe 0 -i <(echo "file 'ch01.mp3'"; echo "file 'ch02.mp3'") -c copy book.mp3
ffmpeg -y -i book.mp3 -c:a aac -b:a 128k book_raw.m4a
ffmpeg -y -i book_raw.m4a -i chapters_metadata.txt -map_metadata 1 -c copy book.m4b

# 4. Downsample to 16 kHz mono WAV for forced alignment
ffmpeg -y -i book.mp3 -ac 1 -ar 16000 sample_16k.wav
```
