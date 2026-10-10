# EchoPage TODO

## Telemetry & Metrics
- [ ] **Custom Telemetry Endpoint Support**:
  - Allow configuring a customized OpenTelemetry collector endpoint (e.g. self-hosted OTel collector, local observability stack, or corporate monitoring service) instead of pyannote's default or having it disabled.
  - Potential configuration options:
    - Environment variable: e.g. `ECHOPAGE_OTEL_ENDPOINT` or `OTEL_EXPORTER_OTLP_ENDPOINT`.
    - CLI flag: e.g. `--telemetry-endpoint <URL>`.
    - Config file: in `echopage` configuration settings.
  - Document supported traces/spans and data schema sent to the custom backend.

## Build Resilience & Performance
- [ ] **Chapter-level Alignment Resume / Checkpointing**:
  - Save intermediate alignment results per chapter into `work_dir` (e.g. `work_dir/checkpoints/` or incremental `alignment_checkpoint.json`) as each chapter finishes WhisperX transcription & alignment.
  - If a build is interrupted (e.g. Ctrl+C, system sleep, or crash), resuming the build (`echopage build` with the same `work_dir`) automatically loads finished chapters and resumes directly from the first incomplete chapter without re-transcribing finished audio.
  - Respect `--force` to bypass checkpoints and re-align from scratch when requested.
  - Clean up intermediate chapter checkpoints after the final packaged EPUB is successfully built (unless `--keep-temp` is set).
