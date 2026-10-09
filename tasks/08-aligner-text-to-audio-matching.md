# 08 - Aligner: Match EPUB Sentences to Audio

## Background
WhisperX gives timed words from what was *heard*. The EPUB gives the *known* text. We must match the two word sequences and assign each EPUB sentence a start and end time. The text will not match exactly (numbers, skipped parts, misheard words), so the match must tolerate differences.

## What to do
1. Run the WhisperX transcribe and align (task 07) on each audio unit and get timed words.
2. Normalize both sides: lowercase, strip punctuation, expand nothing fancy.
3. Match the EPUB word stream to the heard word stream with a sequence alignment (`difflib.SequenceMatcher`, or Needleman-Wunsch style). Write the matching as a pure function so it is testable without audio.
4. For each EPUB sentence, take the start of its first matched word and the end of its last matched word. Fill unmatched gaps by interpolating between neighbours.
5. Enforce monotonic times (`start <= end`, next `start >= previous end`).
6. Compute a per-sentence confidence (fraction of words matched). Log sentences below 0.5.
7. Map each audio unit to a spine chapter (by order, or by title similarity). If the counts differ, fail with a clear message asking for manual mapping.

## Acceptance Criteria
- [ ] The pure matching function has unit tests with fake word lists: exact match, one word misheard, one sentence missing in audio, extra words in audio.
- [ ] On the fixture, every sentence gets `start_ms < end_ms`, and all times are in order.
- [ ] Spot check: 3 sentences' timestamps line up with the audio when played.
- [ ] Low-confidence sentences are reported in the log with their chapter and text.
- [ ] A chapter/audio count mismatch gives an actionable error.
