# 18 - Workspace Lifecycle & Smart Pruning (`echopage clean`)

## Background
EchoPage generates substantial intermediate artifacts during a build:
1. Unpacked EPUB folder with uncompressed XHTML documents, images, and fonts.
2. Uncompressed 16kHz mono WAV scratch files for each audiobook chapter (often 100MB~500MB per chapter, totaling 5GB~15GB for a full 12+ hour book).
3. Temporary Whisper/WhisperX scratch files.
4. Alignment metadata (`alignment.json`) and SMIL files.

Currently, `work_dir` is preserved by default to safeguard expensive GPU compute results. However, over time, multiple builds can silently consume tens or hundreds of gigabytes of disk space on the user's hard drive.

A structured workspace lifecycle manager, a dedicated `echopage clean` command, and post-build smart pruning are needed to keep disk usage efficient without sacrificing performance.

---

## What to do

1. **Dedicated CLI Command (`echopage clean`):**
   - Implement `echopage clean` with intuitive target flags:
     - `echopage clean --work-dir <path>`: Clean a specific workspace directory.
     - `echopage clean --all`: Scan default cache directories (e.g. `.echopage_cache_*`, `~/.cache/echopage`) and remove all stale workspaces after user confirmation (or with `-y / --yes`).
     - `echopage clean --older-than <days>`: Automatically evict workspaces older than a specified number of days (e.g. `--older-than 7`).
     - `echopage clean --dry-run`: Display directories and total disk space that would be freed without actually deleting.

2. **Smart Pruning Post-Build:**
   - After `echopage build` succeeds and the final `.epub` output file is generated:
     - Allow removing bulky temporary scratch files (specifically the generated `wav16k/` scratch audio files).
     - Preserve lightweight, high-value assets (`alignment.json`, chapter mapping metadata, and unpacked EPUB XHTML files) unless `--keep-temp` or a clean flag dictates otherwise.
     - Provide a CLI flag `--prune-audio` or make smart pruning the default behavior when building without `--keep-temp`.

3. **Workspace Policy Clarification:**
   - Clearly delineate between:
     - **Auto-generated temporary workspaces** (`.echopage_build_<book_stem>`): Cleaned up automatically upon successful build completion unless `--keep-temp` is passed.
     - **Explicit user workspaces** (`--work-dir <path>`): Retained for caching, inspection, or manual tuning, but subject to smart pruning of scratch audio files.

---

## Acceptance Criteria
- [ ] **CLI Subcommand `clean`:** `echopage clean` command implemented with `--work-dir`, `--all`, `--older-than`, and `--dry-run` options.
- [ ] **Dry-Run Reporting:** `echopage clean --dry-run` reports exact paths and human-readable space reclaimable (e.g. `Will free 12.4 GB across 3 workspaces`).
- [ ] **Smart Audio Pruning:** Bulky intermediate 16kHz WAV splits in `wav16k/` can be pruned automatically post-build while preserving `alignment.json`.
- [ ] **Safe Deletion Guard:** Safety checks prevent deleting arbitrary directories outside known cache patterns or non-EchoPage folders.
- [ ] **Automated Test Coverage:** Unit and integration tests covering directory discovery, age-based filtering, dry-run mode, and deletion safety.
