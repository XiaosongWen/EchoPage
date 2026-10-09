# Audio Basics Primer for EchoPage

This guide provides an overview of audio fundamentals, container formats, codecs, DRM handling, chapter metadata, and timestamp conventions relevant to EchoPage's automated pipeline.

---

## 1. Containers vs. Codecs

Digital audio files consist of two distinct layers:
1. **The Container**: The outer wrapper and file format (e.g., `.m4b`, `.mp3`, `.m4a`, `.aax`, `.wav`). The container holds audio streams, video streams, subtitle tracks, chapter marks, and tags (title, author, album art).
2. **The Codec**: The algorithm used to compress and encode the raw sound samples into binary data (e.g., AAC, MP3, Opus, FLAC, uncompressed PCM).

| File Extension | Typical Container | Encoded Audio Codec | Notes |
|---|---|---|---|
| `.m4b` | MP4 / QuickTime (`mov,mp4,m4a`) | AAC (`mp4a`) | Standard audiobook container; supports chapter markers and bookmarking. |
| `.mp3` | MPEG Audio Layer III (`mp3`) | MP3 (`mp3float`) | Universal audio format; metadata typically stored in ID3v2 tags. |
| `.aax` | MP4 / QuickTime variant | Encrypted AAC | Audible proprietary format encrypted with account-specific DRM. |
| `.aaxc` | MP4 / QuickTime variant | Encrypted AAC | Audible proprietary format encrypted with voucher key & IV. |
| `.wav` | RIFF WAVE | Uncompressed PCM (`pcm_s16le`) | Uncompressed, linear audio samples; standard input for acoustic models. |

### Stream Copying (`-c:a copy`)
When converting between compatible containers (or stripping DRM), re-encoding audio causes unnecessary generational loss and wastes CPU time. FFmpeg provides the stream copy flag:
```bash
ffmpeg -i input.aax -c:a copy output.m4b
```
`-c:a copy` extracts the compressed audio packets from the source container and muxes them directly into the destination container without running a decoder or encoder. This operation is **virtually instantaneous and 100% lossless**.

---

## 2. Audible DRM Decryption

Audible audiobooks arrive in encrypted containers (`.aax` and `.aaxc`). The underlying audio stream is standard AAC, but individual packets are encrypted using AES-CBC encryption.

### AAX Format (Activation Bytes)
- **Mechanism**: The stream is encrypted using a key derived from the user's Audible account activation bytes (an 8-character hexadecimal string, e.g., `1a2b3c4d`).
- **Decryption Command**:
  ```bash
  ffmpeg -activation_bytes 1a2b3c4d -i book.aax -vn -c:a copy book.m4b
  ```
  FFmpeg uses the activation bytes to decrypt the AES audio packets on the fly and repackages the stream into an unencrypted `.m4b` container with zero audio re-encoding.

### AAXC Format (Key & IV)
- **Mechanism**: Modern Audible apps deliver `.aaxc` files accompanied by a voucher containing a per-title encryption key and initialization vector (IV).
- **Decryption Command**:
  ```bash
  ffmpeg -audible_key <HEX_KEY> -audible_iv <HEX_IV> -i book.aaxc -vn -c:a copy book.m4b
  ```

---

## 3. Chapter Markers & Metadata

Audiobooks frequently ship as a single monolithic audio file containing hours of narration. Chapter markers embedded in the container metadata delineate individual sections, matching the spine order of the source EPUB.

### How Chapter Markers Work in `.m4b`
In MP4/M4B containers, chapter markers are stored in the file header (`moov` atom) using a chapter track or metadata list. Each chapter defines:
- **Start timestamp** (`start` / `start_time`)
- **End timestamp** (`end` / `end_time`)
- **Title tag** (`title`, e.g., "Chapter 1: The Tortoise and the Hare")

`ffprobe` reads this metadata and can output it in human-readable or machine-readable JSON format:
```bash
ffprobe -show_chapters -of json input.m4b
```

---

## 4. Sample Rate & Channel Normalization (16 kHz Mono)

Speech recognition and acoustic forced alignment models (such as Whisper, WhisperX, and Wav2Vec2) require audio pre-processed to a strict standard:
- **Sample Rate**: 16,000 Hz (16 kHz). Speech phoneme analysis does not require high ultrasonic frequencies above 8 kHz (Nyquist rate for 16 kHz).
- **Channels**: 1 channel (mono). Stereo spatial panning adds unnecessary complexity and redundant channel processing.
- **Format**: Uncompressed 16-bit Linear PCM WAV (`pcm_s16le`).

### Downsampling Command
```bash
ffmpeg -i input.mp3 -ac 1 -ar 16000 scratch/sample_16k.wav
```
- `-ac 1`: Downmixes stereo channels to mono.
- `-ar 16000`: Resamples audio clock frequency to 16 kHz.
- Output `.wav`: Stored in temporary work directories during alignment and discarded afterward to conserve disk space.

---

## 5. Timestamp Conventions: Milliseconds vs. Seconds

In EchoPage, timestamps are handled in two different formats depending on the pipeline stage:

1. **Pipeline & Intermediate JSON (`alignment.json`)**:
   - Time unit: **Integer Milliseconds (`ms`)**.
   - Example:
     ```json
     {
       "element_id": "mo_s_0001",
       "text": "It was the best of times.",
       "start_ms": 120,
       "end_ms": 2340
     }
     ```
   - **Rationale**: Integer millisecond arithmetic eliminates floating-point precision drift and rounding discrepancies during text segmentation and acoustic boundary matching.

2. **EPUB 3 Media Overlays (SMIL 3.0)**:
   - Time unit: **Seconds with metric suffix (`s`)** adhering to the SMIL 3.0 / EPUB 3 specification.
   - Example:
     ```xml
     <audio src="audio/chapter01.mp3" clipBegin="0.120s" clipEnd="2.340s"/>
     ```
   - **Conversion Rule**:
     $$\text{clipBegin} = \frac{\text{start\_ms}}{1000.0}\text{s}$$
     Format as seconds with 3 decimal digits and trailing `'s'` (e.g., `120 ms` $\to$ `0.120s`).

---

## 6. Practical Command Exercises & Real Outputs

Below are actual command executions performed against the test fixtures under [`tests/fixtures/`](file:///Users/tomaswen/workspace/EchoPage/tests/fixtures/).

### 6.1 Inspecting Chapters & Format with `ffprobe`

**Command**:
```bash
ffprobe -show_format -show_chapters tests/fixtures/book.m4b
```

**Output**:
```text
ffprobe version 8.1.2 Copyright (c) 2007-2026 the FFmpeg developers
  built with Apple clang version 21.0.0 (clang-2100.0.123.102)
  configuration: --prefix=/opt/homebrew/Cellar/ffmpeg/8.1.2_1 --enable-shared --enable-pthreads --enable-version3 --cc=clang --host-cflags= --host-ldflags= --enable-ffplay --enable-gpl --enable-libsvtav1 --enable-libopus --enable-libx264 --enable-libmp3lame --enable-libdav1d --enable-libvmaf --enable-libvpx --enable-libx265 --enable-openssl --enable-videotoolbox --enable-audiotoolbox --enable-neon
  libavutil      60. 26.102 / 60. 26.102
  libavcodec     62. 28.102 / 62. 28.102
  libavformat    62. 12.102 / 62. 12.102
  libavdevice    62.  3.102 / 62.  3.102
  libavfilter    11. 14.102 / 11. 14.102
  libswscale      9.  5.102 /  9.  5.102
  libswresample   6.  3.102 /  6.  3.102
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'tests/fixtures/book.m4b':
  Metadata:
    major_brand     : M4A 
    minor_version   : 512
    compatible_brands: M4A isomiso2
    title           : Aesop's Fables Sample
    artist          : Aesop
    album           : EchoPage Test Fixtures
    encoder         : Lavf62.12.102
  Duration: 00:00:45.23, start: 0.000000, bitrate: 104 kb/s
  Chapters:
    Chapter #0:0: start 0.000000, end 23.833000
      Metadata:
        title           : Chapter 1: The Tortoise and the Hare
    Chapter #0:1: start 23.833000, end 45.159000
      Metadata:
        title           : Chapter 2: The North Wind and the Sun
  Stream #0:0[0x1](und): Audio: aac (LC) (mp4a / 0x6134706D), 22050 Hz, mono, fltp, 103 kb/s (default)
    Metadata:
      handler_name    : SoundHandler
  Stream #0:1[0x2](eng): Data: bin_data (text / 0x74786574), 0 kb/s
    Metadata:
      handler_name    : SubtitleHandler
Unsupported codec with id 98314 for input stream 1
[CHAPTER]
id=0
time_base=1/1000
start=0
start_time=0.000000
end=23833
end_time=23.833000
TAG:title=Chapter 1: The Tortoise and the Hare
[/CHAPTER]
[CHAPTER]
id=1
time_base=1/1000
start=23833
start_time=23.833000
end=45159
end_time=45.159000
TAG:title=Chapter 2: The North Wind and the Sun
[/CHAPTER]
[FORMAT]
filename=tests/fixtures/book.m4b
nb_streams=2
nb_programs=0
nb_stream_groups=0
format_name=mov,mp4,m4a,3gp,3g2,mj2
format_long_name=QuickTime / MOV
start_time=0.000000
duration=45.227982
size=593451
bit_rate=104970
probe_score=100
TAG:major_brand=M4A 
TAG:minor_version=512
TAG:compatible_brands=M4A isomiso2
TAG:title=Aesop's Fables Sample
TAG:artist=Aesop
TAG:album=EchoPage Test Fixtures
TAG:encoder=Lavf62.12.102
[/FORMAT]
```

### 6.2 Resampling Audio to 16 kHz Mono WAV with `ffmpeg`

**Command**:
```bash
ffmpeg -i tests/fixtures/book.mp3 -ac 1 -ar 16000 tests/fixtures/sample_16k.wav
```

**Output**:
```text
ffmpeg version 8.1.2 Copyright (c) 2000-2026 the FFmpeg developers
  built with Apple clang version 21.0.0 (clang-2100.0.123.102)
  configuration: --prefix=/opt/homebrew/Cellar/ffmpeg/8.1.2_1 --enable-shared --enable-pthreads --enable-version3 --cc=clang --host-cflags= --host-ldflags= --enable-ffplay --enable-gpl --enable-libsvtav1 --enable-libopus --enable-libx264 --enable-libmp3lame --enable-libdav1d --enable-libvmaf --enable-libvpx --enable-libx265 --enable-openssl --enable-videotoolbox --enable-audiotoolbox --enable-neon
  libavutil      60. 26.102 / 60. 26.102
  libavcodec     62. 28.102 / 62. 28.102
  libavformat    62. 12.102 / 62. 12.102
  libavdevice    62.  3.102 / 62.  3.102
  libavfilter    11. 14.102 / 11. 14.102
  libswscale      9.  5.102 /  9.  5.102
  libswresample   6.  3.102 /  6.  3.102
Input #0, mp3, from 'tests/fixtures/book.mp3':
  Metadata:
    encoder         : Lavf62.12.102
  Duration: 00:00:45.23, start: 0.050113, bitrate: 73 kb/s
  Stream #0:0: Audio: mp3 (mp3float), 22050 Hz, mono, fltp, 72 kb/s, start 0.050113
Stream mapping:
  Stream #0:0 -> #0:0 (mp3 (mp3float) -> pcm_s16le (native))
Press [q] to stop, [?] for help
Output #0, wav, to 'tests/fixtures/sample_16k.wav':
  Metadata:
    ISFT            : Lavf62.12.102
  Stream #0:0: Audio: pcm_s16le ([1][0][0][0] / 0x0001), 16000 Hz, mono, s16, 256 kb/s
    Metadata:
      encoder         : Lavc62.28.102 pcm_s16le
[out#0/wav @ 0x93cc38180] video:0KiB audio:1413KiB subtitle:0KiB other streams:0KiB global headers:0KiB muxing overhead: 0.005389%
size=    1413KiB time=00:00:45.22 bitrate= 256.0kbits/s speed=2.19e+03x elapsed=0:00:00.02    
```
