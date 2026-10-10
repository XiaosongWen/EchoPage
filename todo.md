# EchoPage TODO

## Telemetry & Metrics
- [ ] **Custom Telemetry Endpoint Support**:
  - Allow configuring a customized OpenTelemetry collector endpoint (e.g. self-hosted OTel collector, local observability stack, or corporate monitoring service) instead of pyannote's default or having it disabled.
  - Potential configuration options:
    - Environment variable: e.g. `ECHOPAGE_OTEL_ENDPOINT` or `OTEL_EXPORTER_OTLP_ENDPOINT`.
    - CLI flag: e.g. `--telemetry-endpoint <URL>`.
    - Config file: in `echopage` configuration settings.
  - Document supported traces/spans and data schema sent to the custom backend.
