# EchoPage Roadmap & TODO

This document tracks upcoming features and enhancements for EchoPage, organized by implementation priority.

---

## Priority 1: Production Resilience & Resource Management

- [ ] **Chapter-level Alignment Resume & Checkpointing** ([tasks/17-alignment-checkpoint-and-resume.md](file:///mnt/c/Users/242107/Desktop/Project/EchoPage/tasks/17-alignment-checkpoint-and-resume.md)):
  - Save intermediate alignment results per chapter into `work_dir` (e.g. `work_dir/checkpoints/ch_XXXX.json` or incremental `alignment_checkpoint.json`) as each chapter finishes WhisperX transcription and acoustic forced alignment.
  - If a build is interrupted (e.g. Ctrl+C, system sleep, crash, or OOM), running `echopage build` with the same `work_dir` automatically detects finished chapters and resumes directly from the first incomplete chapter without re-computing finished audio.
  - Provide `--force` flag to explicitly bypass checkpoints and re-align all chapters from scratch.
  - Automatically prune intermediate per-chapter checkpoints once the final EPUB 3 Media Overlays package is generated successfully (unless `--keep-temp` is specified).

- [ ] **Workspace Lifecycle & Smart Pruning (`echopage clean`)** ([tasks/18-workspace-lifecycle-and-clean.md](file:///mnt/c/Users/242107/Desktop/Project/EchoPage/tasks/18-workspace-lifecycle-and-clean.md)):
  - Currently, `work_dir` (including raw 16kHz mono audio splits, unpacked EPUB, and `alignment.json`) is preserved by default to prevent loss of expensive WhisperX compute.
  - Implement a dedicated cleanup CLI command:
    - `echopage clean --all` (purge all cached workspaces).
    - `echopage clean --older-than <days>` (evict stale build directories).
    - `echopage clean --work-dir <path>` (clean a specific workspace).
  - Implement **Smart Pruning**: allow removing bulky raw audio scratch WAV splits and temporary unpacked XHTML files after successful build packaging, while preserving lightweight metadata (`alignment.json` and chapter mapping) so subsequent packaging/CSS tweaks remain instantaneous.
  - Clarify lifecycle and naming policies between auto-generated workspaces (`.echopage_build_<stem>`) and user-specified explicit `--work-dir`.

- [ ] **Hardware-Aware Parallel Alignment & Concurrency Auto-Detection** ([tasks/19-parallel-alignment-and-vram-detection.md](file:///mnt/c/Users/242107/Desktop/Project/EchoPage/tasks/19-parallel-alignment-and-vram-detection.md)):
  - Add `--workers` / `--concurrency` flag (`auto` by default, or explicit integer `N`).
  - Automatically inspect available GPU VRAM (and multi-GPU count) to calculate safe concurrency based on model size (e.g. ~6.5GB for `large-v3`, ~4.0GB for `medium`, ~2.5GB for `small`).
  - Maintain safety boundaries (select `workers=1` on 8GB GPU to prevent OOM; select `workers=3` on 24GB GPU, etc.) with explicit override warning.
  - Implement multi-worker chapter alignment dispatch while strictly preserving original EPUB spine order in the final output.

- [ ] **Power Management, Sleep Prevention & Auto-Sleep on Finish** ([tasks/20-power-management-and-anti-sleep.md](file:///mnt/c/Users/242107/Desktop/Project/EchoPage/tasks/20-power-management-and-anti-sleep.md)):
  - Automatically inhibit system idle sleep during active builds across Windows, WSL2, macOS, and Linux (via OS-native power assertions / keep-awake heartbeats).
  - Add `--sleep-on-finish` flag (or `--post-action none|sleep|shutdown`) to optionally suspend/sleep the host machine upon successful EPUB build completion.
  - Ensure power locks are cleanly released in all exit paths and suppress sleep on build errors.

---

## Priority 2: Release & Engineering

- [ ] **PyPI Automated Publishing & Distribution**:
  - Set up automated GitHub Actions release workflow (e.g. utilizing GitHub Trusted Publishing with `uv build` / `twine`) triggered upon version tags (e.g. `v0.1.0`).
  - Publish wheel and sdist packages to PyPI.
  - Enable seamless single-command installation for end users via `uv tool install echopage` or `uv pip install echopage` without needing to clone the Git repository.

- [ ] **Docker Containerization with CUDA & FFmpeg**:
  - Provide official `Dockerfile` and automated container builds pre-configured with Python 3.10+, `uv`, FFmpeg, CUDA toolkit, and PyTorch / WhisperX dependencies.
  - Enable zero-setup batch processing in headless environments and cloud GPU instances (e.g. RunPod, AutoDL, Lambda Labs, AWS EC2).

---

## Priority 3: Interactive Workflow & Verification

- [ ] **Interactive Chapter Mapping & Mapping File Support**:
  - When heuristic chapter matching confidence is low, or when chapter counts between EPUB spine and audiobook tracks diverge significantly, offer an interactive CLI wizard before initiating heavy WhisperX GPU processing.
  - Allow users to review and manually adjust chapter pairings in terminal prompts.
  - Support exporting and importing chapter mapping configurations:
    - `echopage build ... --dry-run --export-mapping mapping.yaml`
    - `echopage build ... --mapping mapping.yaml` (bypasses heuristics and uses verified mapping directly).

- [ ] **Local Alignment Web Previewer (`echopage preview`)**:
  - Provide a lightweight local web preview command:
    - `echopage preview <path-to-epub>`
  - Launch a local HTTP server opening a browser window that renders the chapter XHTML alongside an audio player, synchronizing `<span id="mo_s_XXXX">` highlight states with audio playback.
  - Allows instant, frictionless quality inspection of alignment timing without requiring Thorium Reader or Apple Books sync.

---

## Priority 4: Capability Expansion

- [ ] **Bilingual EPUB with Media Overlays (Dual-text, Single-audio Sync)**:
  - Support inputs of one audiobook audio file, one primary language EPUB (e.g. English), and one translated target EPUB (e.g. Chinese).
  - Align audio to source text (WhisperX acoustic forced alignment), and align source text to translated text via bitext sentence alignment (multilingual sentence embeddings / paragraph anchors).
  - Synthesize unified bilingual XHTML chapters with selectable layouts (`--bilingual-layout interlinear|side-by-side`).
  - Generate synchronized EPUB 3 SMIL 3.0 Media Overlays and package into a single bilingual narrated EPUB.

- [ ] **Custom Telemetry Endpoint Support (OpenTelemetry)**:
  - Allow configuring a customized OpenTelemetry collector endpoint (e.g. self-hosted OTel collector, local observability stack, or corporate monitoring service) instead of pyannote's default or having it disabled.
  - Configuration channels:
    - Environment variable: `ECHOPAGE_OTEL_ENDPOINT` or `OTEL_EXPORTER_OTLP_ENDPOINT`.
    - CLI flag: `--telemetry-endpoint <URL>`.
    - Configuration file in `echopage` settings.
  - Document supported traces/spans and data schema sent to the custom backend.
