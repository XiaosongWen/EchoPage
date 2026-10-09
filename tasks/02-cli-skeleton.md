# 02 - CLI Skeleton

## Background
The PRD defines one command: `EchoPage build ...`. Build the argument parsing first, with the pipeline steps stubbed, so the interface is fixed early.

## What to do
1. Implement the `build` subcommand with these flags:
   - Required: `--epub`, `--audio` (one or more paths), `--output`.
   - Optional: `--activation-bytes`, `--audible-key`, `--audible-iv`, `--granularity sentence|word` (default `sentence`), `--model-size small|medium|large-v3`, `--device cpu|cuda|mps`, `--work-dir`.
2. Validate arguments:
   - Files exist.
   - `--activation-bytes` is exactly 8 hex characters.
   - `--audible-key` and `--audible-iv` are given together.
3. Call the stub pipeline functions in order: decrypt, parse, align, package. Log each phase start and end.
4. Add `--verbose` for debug logging.

## Acceptance Criteria
- [ ] `echopage build --help` lists every flag with a description.
- [ ] A missing file gives a clear error and a non-zero exit code.
- [ ] A bad `--activation-bytes` value (e.g. `xyz`) is rejected with a clear error.
- [ ] A valid invocation prints the 4 phase messages (stubs) and exits 0.
- [ ] Unit tests cover argument validation.
