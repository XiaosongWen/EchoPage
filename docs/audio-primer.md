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

## 6. Practical FFmpeg Command Reference

Below are the key commands used by EchoPage and how to interpret their results.

### 6.1 Inspecting Chapters & Duration with `ffprobe`
```bash
ffprobe -v error -show_chapters -show_entries format=duration:format_tags=title -of json input.m4b
```
**Key JSON Output Fields**:
- `format.duration`: Total audio file length in seconds (e.g. `45.227982`).
- `chapters`: Array of embedded chapter markers:
  - `start_time` / `end_time`: Chapter boundary in fractional seconds.
  - `tags.title`: Chapter name (e.g. `"Chapter 1: The Tortoise and the Hare"`).

### 6.2 Splitting Chapters with Stream Copy (Instant, Zero Quality Loss)
```bash
ffmpeg -y -ss <START_SECONDS> -to <END_SECONDS> -i input.m4b -c copy output_part.m4b
```
- `-c copy`: Copies the encoded AAC audio packets directly into the new container without decoding or re-encoding. Takes less than a second per chapter.

### 6.3 Resampling to 16 kHz Mono WAV (Speech Recognition Input)
```bash
ffmpeg -y -i input.m4b -ac 1 -ar 16000 output_16k.wav
```
- `-ac 1`: Downmixes stereo to 1-channel mono.
- `-ar 16000`: Sets audio clock to 16,000 Hz, matching Whisper and Wav2Vec2 acoustic models.

