# 07 - WhisperX Environment Spike

## Background
WhisperX transcribes speech (Whisper) and then aligns words to exact times (wav2vec2). It is heavy: it needs PyTorch and downloads models. Apple Silicon (`mps`) support is partial, so `cpu` may be needed. Learn how it behaves before writing real code.

## What to do
1. Install WhisperX in the project environment as an optional extra (`pip install -e .[align]`).
2. Write `scripts/whisperx_spike.py` that:
   - Loads the fixture WAV.
   - Transcribes with the `small` model.
   - Aligns and prints word timings.
3. Try `--device cpu` and `--device mps`. Record what works, the speed and any errors.
4. Record the findings in `docs/whisperx-notes.md`: versions, model download size and location, speed on the fixture, and device compatibility. Say whether `compute_type` needs to be `int8`/`float32` on CPU.

## Acceptance Criteria
- [x] The spike script runs end to end on the fixture and prints word start/end times in seconds.
- [x] Timings roughly match the audio (spot-check 3 words by listening).
- [x] `docs/whisperx-notes.md` records versions, devices that work, speed and model sizes.
- [x] Heavy dependencies are optional extras, so `pip install -e .` stays light.
