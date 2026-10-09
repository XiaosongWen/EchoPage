# 03 - Audio Basics & Test Fixtures

## Background (audio crash course)
- **Container vs codec:** `.m4b` / `.mp3` / `.aax` are containers, and the audio inside is encoded (AAC, MP3). `-c:a copy` re-wraps the audio without re-encoding, so it is fast and lossless.
- **DRM:** AAX/AAXC are encrypted AAC. FFmpeg decrypts them with a key.
- **Chapter markers:** an `.m4b` can store chapter names and times in its metadata. `ffprobe` can read them.
- **Sample rate / mono:** speech models want 16 kHz mono WAV. This is the "downsample" step in the PRD.
- **Timestamps:** the final SMIL uses seconds (`clipBegin="0.120s"`), while our JSON uses milliseconds.

## What to do
1. Write `docs/audio-primer.md` with the notes above in your own words.
2. Create a tiny test fixture set under `tests/fixtures/`:
   - A short public-domain EPUB (2 chapters, a few paragraphs each, e.g. from Project Gutenberg).
   - A matching 30-60 second `.mp3` or `.m4b`. Use a LibriVox recording of the same text, or generate it with macOS `say -o out.aiff "text"` and convert with ffmpeg.
3. Add `tests/fixtures/README.md` saying where each file came from and its license.
4. Manually practice these commands and paste the output in the primer:
   - `ffprobe -show_format -show_chapters file.m4b`
   - `ffmpeg -i in.mp3 -ac 1 -ar 16000 out.wav`

## Acceptance Criteria
- [ ] `docs/audio-primer.md` exists and covers container/codec, DRM, chapters, 16 kHz mono and ms vs seconds.
- [ ] Fixture EPUB opens in an EPUB reader.
- [ ] Fixture audio plays and its text matches the EPUB text.
- [ ] Fixture sources and licenses are documented.
- [ ] No DRM-protected or copyrighted audio is committed to the repo.
