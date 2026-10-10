# 17 - Chapter-level Alignment Resume & Checkpointing

## Background
Full-length audiobooks often span 10 to 30+ hours (such as *Horus Rising*, which is over 12 hours long across 25 chapters). Transcribing and force-aligning such books with WhisperX takes 1 to 3+ hours even on modern GPUs.

Currently, if an execution is interrupted halfway through (e.g. system sleep, manual `Ctrl+C`, network disconnection in SSH, terminal closure, or CUDA Out-Of-Memory on long chapters), the entire alignment loop in `aligner.py` is aborted. Re-running `echopage build` currently restarts alignment from chapter 1, discarding all previously computed GPU work.

A resilient per-chapter checkpointing and resume mechanism is critical for production reliability and developer experience.

---

## What to do

1. **Incremental Checkpoint Storage:**
   - In `work_dir`, maintain an incremental checkpoint directory or file:
     - e.g. `work_dir/checkpoints/chapter_<spine_id>.json` or an atomic update to `work_dir/alignment_checkpoint.json`.
   - As each chapter completes WhisperX transcription, wav2vec2 forced alignment, and sentence mapping, immediately flush its `AlignedChapter` data to disk.
   - Use atomic write operations (write to `.tmp` file and rename) to guarantee checkpoint files are never corrupted by unexpected terminations.

2. **Resume Detection on Build Start:**
   - When `echopage build` (or `echopage align`) is invoked with an existing `work_dir`:
     - Inspect the checkpoint directory for previously aligned chapters matching the current EPUB spine / audio pairs.
     - Validate checkpoint integrity and compatibility (check that model size, language, and chapter IDs match).
     - Log a clear resume banner:
       `[INFO ] [echopage.aligner] Resuming from checkpoint in '.echopage_cache': 8/25 chapters already completed. Resuming at chapter 9/25 ('id014')...`
     - Skip redundant audio downsampling, Whisper transcription, and wav2vec2 alignment for finished chapters.

3. **Force Override Flag (`--force`):**
   - Provide `--force` in CLI to explicitly bypass existing checkpoints and re-align from scratch when users intentionally want a fresh run.

4. **Post-Build Checkpoint Lifecycle:**
   - Once all chapters are aligned and the final EPUB package is successfully generated:
     - Automatically clean up temporary per-chapter checkpoint files unless `--keep-temp` is specified.
     - Keep the final `alignment.json` in `work_dir` so subsequent packaging or inspection remains instantaneous.

---

## Acceptance Criteria
- [ ] **Atomic Per-Chapter Saves:** Each chapter's `AlignedChapter` result is flushed to disk immediately upon completion.
- [ ] **Seamless Resume:** Killing a build halfway through (e.g., at chapter 5/25) and re-running `echopage build` with the same `work_dir` skips chapters 1-4 and resumes directly at chapter 5.
- [ ] **Final Output Parity:** A resumed run produces byte-equivalent or timeline-equivalent `alignment.json` and EPUB Media Overlays compared to an uninterrupted full run.
- [ ] **Bypass with `--force`:** Supplying `--force` ignores existing checkpoints and recomputes all chapters from chapter 1.
- [ ] **Clean Diagnostics:** Console logs clearly inform the user how many chapters were restored from checkpoint and which chapter is being resumed.
- [ ] **Automated Test Coverage:** Unit and integration tests covering interrupted runs, resume loading, corrupt checkpoint handling, and `--force` flag.
