# WhisperX Environment Spike Notes

This document summarizes findings from spiking the WhisperX speech transcription and forced-alignment pipeline for EchoPage on Apple Silicon (macOS).

---

## 1. Environment & Package Versions

WhisperX relies on PyTorch, `ctranslate2` (via `faster-whisper`), and Hugging Face Transformers. 

> [!NOTE]
> **Python Version Compatibility:** Python 3.12 was used for this spike. Python 3.14 does not yet have prebuilt wheels for `ctranslate2 4.4.0` / pinned dependencies. Python 3.10–3.12 is recommended for alignment workloads.

### Installed Package Versions
| Package | Version | Role |
|---|---|---|
| **Python** | `3.12.15` | Runtime interpreter (macOS arm64) |
| **whisperx** | `3.8.6` | Transcription & wav2vec2 alignment orchestration |
| **faster-whisper** | `1.2.1` | Optimized Whisper inference engine |
| **ctranslate2** | `4.8.2` | Fast inference backend for Transformer models |
| **torch** | `2.8.0` | PyTorch runtime (CPU & MPS backends) |
| **torchaudio** | `2.8.0` | Audio I/O and tensor transforms |
| **transformers** | `4.57.6` | Hugging Face model architectures & tokenizers |

### Packaging Configuration
Heavy alignment dependencies are isolated under an optional extra in `pyproject.toml`:
```toml
[project.optional-dependencies]
dev = ["pytest"]
align = ["whisperx"]
```
- Running `pip install -e .` keeps the installation lightweight (~15MB of pure Python / standard parsing wheels: `lxml`, `beautifulsoup4`, `nltk`).
- Running `pip install -e ".[align]"` installs PyTorch and WhisperX only when alignment capabilities are required.

---

## 2. Models, Download Sizes & Locations

When executing WhisperX with the `small` model and English language alignment:

### 1. Whisper Model (`small`)
- **Repository / Architecture**: `Systran/faster-whisper-small` (ctranslate2 converted weights)
- **Disk Location**: `~/.cache/huggingface/hub/models--Systran--faster-whisper-small/`
- **Disk Footprint**: **464 MB**
- **Files**: `model.bin` (~461 MB), `config.json`, `vocabulary.json`, `tokenizer.json`

### 2. Forced Alignment Model (wav2vec2)
- **Architecture**: `wav2vec2_fairseq_base_ls960_asr_ls960.pth`
- **Disk Location**: `~/.cache/torch/hub/checkpoints/wav2vec2_fairseq_base_ls960_asr_ls960.pth`
- **Disk Footprint**: **377.7 MB** (directory total: ~369 MB)

### Combined Footprint
- **Total Initial Download**: **~833 MB**
- Once cached locally, subsequent executions load models directly from disk without re-downloading.

---

## 3. Device Compatibility (CPU vs MPS vs CUDA)

### Transcription (`ctranslate2` / `faster-whisper`)
- **`device="cpu"`**: **Supported and fully operational.** Highly optimized via CTranslate2 multi-threading and vector instructions (ARM NEON on Apple Silicon).
- **`device="mps"`**: **Unsupported.** Attempting `--device mps` raises:
  ```text
  ValueError: unsupported device mps
  ```
  `ctranslate2`'s C++ inference engine only supports `cpu` and `cuda` execution targets. It does not interface with Apple Metal / MPS.

### Forced Alignment (`whisperx.load_align_model` / `wav2vec2`)
- **`align_device="cpu"`**: **Supported and fastest on Apple Silicon.** Aligned 45 seconds of speech in 1.06s (~42x realtime).
- **`align_device="mps"`**: **Supported, but slower.** PyTorch successfully loads and runs the wav2vec2 model on Apple Silicon MPS (`torch.backends.mps.is_available() == True`). However, due to GPU dispatch and synchronization overhead on small batch sizes, alignment took 2.12s (21x realtime) on MPS versus 1.06s on CPU.

### Cross-Platform Hardware Auto-Detection (Mac vs PC)
To seamlessly support both macOS (Apple Silicon/Intel) and PC (Windows/Linux with optional NVIDIA CUDA GPUs):

```python
import torch

def get_optimal_device() -> tuple[str, str]:
    """Auto-detect optimal compute device and precision.
    
    - PC/Linux with NVIDIA GPU: ('cuda', 'float16')
    - macOS / PC without CUDA:  ('cpu', 'int8')
    """
    if torch.cuda.is_available():
        return "cuda", "float16"
    return "cpu", "int8"
```

| Environment | Detected Device | Recommended `compute_type` | Rationale |
|---|---|---|---|
| **PC / Linux with NVIDIA GPU** | `cuda` | `float16` | CTranslate2 and PyTorch leverage CUDA Tensor Cores for maximum throughput. |
| **PC / Linux without NVIDIA GPU** | `cpu` | `int8` | CTranslate2 utilizes AVX-512 / AVX2 integer instructions. |
| **Apple Silicon Mac** | `cpu` | `int8` | CTranslate2 lacks Metal/MPS support; CPU ARM NEON delivers ~9.5x realtime transcription; alignment is 2x faster on CPU than MPS. |

---

## 4. CPU `compute_type` Evaluation

`ctranslate2` supports multiple numerical representations for model weights and activations:

| `compute_type` | CPU Support | Transcription Time (45.23s audio) | Realtime Factor | Notes |
|---|---|---|---|---|
| `int8` | **Supported** (Recommended) | **4.95s** | **9.14x realtime** | Quantized 8-bit integer weights. Minimizes RAM footprint while maintaining high transcription quality. |
| `float32` | **Supported** | **4.60s** | **9.83x realtime** | Full 32-bit floating point. Slightly faster throughput on modern Apple Silicon CPUs with ample cache, but higher memory footprint. |
| `float16` | **Unsupported** | N/A (Fails) | N/A | Fails with: `ValueError: Requested float16 compute type, but the target device or backend do not support efficient float16 computation.` |

> [!TIP]
> **Summary on CPU Compute Type:**
> On CPU, `float16` is unsupported and will error. **`int8` is the recommended default** for reduced memory pressure, with `float32` as an acceptable alternative.

---

## 5. Benchmark Results on Test Fixture

**Input Audio**: `tests/fixtures/sample_16k.wav`  
**Audio Format**: 16,000 Hz, 16-bit PCM Mono  
**Duration**: 45.23 seconds  
**Model**: `small` (English)

### Detailed Timings (Warm Cache)

```
======================================================================
Stage                       CPU (int8)           CPU (float32)        CPU + MPS Align
======================================================================
Import (whisperx + torch)    0.46s                0.48s                0.36s
Whisper Model Load           3.20s                3.55s                2.80s
Transcription               4.95s (9.14x RT)     4.60s (9.83x RT)     4.97s (9.10x RT)
Align Model Load             0.40s                0.40s                0.88s
Alignment                   1.06s (42.66x RT)    1.12s (40.55x RT)    2.12s (21.32x RT)
----------------------------------------------------------------------
Total Wall-Clock Time       10.07s               10.21s               11.18s
======================================================================
```

*(Note: On cold cache / first run, initial model downloads added 53s for Whisper and 17s for wav2vec2.)*

---

## 6. Word Timing & Spot-Check Verification

The spike script aligned 154 words across the 45.23-second narrative.

### Word Spot-Checks Against Synthesized Audio
We verified the generated word timings against the source audio and chapter boundaries:

1. **Word 1 ("Chapter" - start of Chapter 1)**:
   - Start: `0.050s`, End: `0.431s`, Score: `0.85`
   - *Verification*: Matches the exact audio onset at the beginning of the file.
2. **Word 36 ("Fox" - mid Chapter 1: "Mr. Fox can witness my victories")**:
   - Start: `10.537s`, End: `10.837s`, Score: `0.79`
   - *Verification*: An audio slice extracted at `10.4s`–`10.9s` cleanly contains the word "Fox".
3. **Word 79 ("Chapter" - start of Chapter 2: "Chapter Two. The North Wind...")**:
   - Start: `23.926s`, End: `24.306s`, Score: `0.85`
   - *Verification*: Directly aligns with the chapter boundary between Chapter 1 (`23.833s`) and Chapter 2 (`23.926s`).
4. **Word 154 ("cloak." - final word of the audiobook)**:
   - Start: `44.855s`, End: `45.196s`, Score: `0.95`
   - *Verification*: Concludes cleanly right before file termination at `45.228s`.

---

## 7. Conclusions for Pipeline Architecture (Task 08 & Beyond)

1. **Keep CLI and default dependencies lightweight**: Keep `align` as an extra (`pip install -e .[align]`). The core EPUB parser, audio splitters, and packager do not require PyTorch.
2. **Apple Silicon default device**: Default to `device="cpu"` and `compute_type="int8"` on macOS. Attempting `device="mps"` fails for Whisper transcription.
3. **Audio format**: WhisperX expects 16 kHz mono WAV input. The existing `echopage to-wav` / `to_wav16k()` utility produces the exact format required.
4. **Alignment Output Schema**: The resulting segment and word structures (`word`, `start`, `end`, `score`) provide the necessary timestamps for Task 08 text-to-audio matching and Task 09 alignment JSON generation.
