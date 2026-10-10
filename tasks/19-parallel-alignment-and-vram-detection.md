# 19 - Hardware-Aware Parallel Alignment & Concurrency Auto-Detection

## Background
Currently, EchoPage processes chapter alignment strictly sequentially in `aligner.py` using a single-threaded loop over `mapped_pairs`. 

While sequential execution with internal batching (`batch_size=16`) is optimal for mid-tier GPUs like the RTX 3070 (8GB VRAM) running `large-v3`, users running on high-end hardware (e.g. 24GB RTX 3090/4090, 48GB RTX A6000, 80GB A100/H100, or multi-GPU workstations) have substantial idle compute and memory. On these machines, processing 2 to 8+ chapters concurrently could dramatically reduce overall build time from several hours down to tens of minutes.

However, concurrently loading multiple instances of large neural models can easily trigger catastrophic Out-Of-Memory (`CUDA OOM`) crashes if concurrency is improperly configured. EchoPage needs an intelligent, hardware-aware concurrency manager that allows explicit user control (`--workers N`) while providing safe, automatic VRAM-based detection (`--workers auto`).

---

## What to do

1. **CLI Parameter `--workers` / `--concurrency`:**
   - Add `--workers` (alias `--concurrency`) argument to `echopage build` and `echopage align`:
     - Default value: `auto`.
     - Explicit integer value: e.g. `--workers 1`, `--workers 2`, `--workers 4`.

2. **VRAM Detection & Safe Concurrency Estimation:**
   - Inspect GPU hardware via PyTorch (`torch.cuda.get_device_properties` or `torch.cuda.mem_get_info`):
     - Extract total VRAM and currently free VRAM.
     - Detect number of available CUDA devices (`torch.cuda.device_count()`).
   - Define baseline memory footprint per worker according to model size:
     - `large-v3` / `large-v2`: ~6.5 GB per worker
     - `medium`: ~4.0 GB per worker
     - `small`: ~2.5 GB per worker
     - `base` / `tiny`: ~1.5 GB per worker
     - CPU mode fallback: limit to `min(4, os.cpu_count() // 2)`.
   - Dynamic Calculation Formula for `--workers auto`:
     $$\text{workers} = \max\left(1, \left\lfloor \frac{\text{VRAM}_{\text{total}} - 1.5\text{GB}}{\text{WorkerVRAMCost}}\right\rfloor\right) \times \text{DeviceCount}$$
   - Safety Warning: If user explicitly specifies a `--workers` count exceeding estimated safe capacity, log a prominent warning alert detailing the risk of CUDA OOM.

3. **Multi-Worker Execution Engine:**
   - Implement concurrent execution for chapter alignment in `aligner.py`:
     - Distribute independent chapter pairs across a worker pool (e.g. `concurrent.futures.ThreadPoolExecutor` or `ProcessPoolExecutor`).
     - In multi-GPU setups (`DeviceCount > 1`), assign workers round-robin to dedicated GPU devices (`cuda:0`, `cuda:1`, etc.).
     - Concurrently execute: audio 16kHz conversion, WhisperX transcription, wav2vec2 forced alignment, and sentence word matching.
     - Re-aggregate completed `AlignedChapter` instances maintaining original EPUB spine sequence order.

4. **Integration with Checkpointing (Task 17):**
   - Ensure parallel workers seamlessly write and commit per-chapter checkpoints safely without race conditions.

---

## Acceptance Criteria
- [ ] **CLI Support:** `--workers` / `--concurrency` flag added to `echopage build` and `echopage align` (default: `auto`).
- [ ] **Hardware Auto-Detection:** `--workers auto` accurately detects GPU VRAM and chooses safe concurrency:
  - Selects `workers=1` on 8GB GPU with `large-v3` (preventing OOM).
  - Selects `workers=3` on 24GB GPU with `large-v3`.
  - Scales appropriately when smaller models (`medium`, `small`) are chosen.
- [ ] **Explicit Override & Safety Check:** Explicit `--workers N` is respected, with clear warning logged if user requests unsafe memory allocation.
- [ ] **Concurrent Speedup:** Verified multi-worker execution on capable hardware shows near-linear speedup across independent chapters.
- [ ] **Order Preservation:** Final output `AlignedChapter` list maintains exact original document spine order regardless of completion sequence.
- [ ] **Graceful Failure Propagation:** If any worker raises an exception or OOM, the scheduler cleanly aborts remaining tasks and reports diagnostic error context.
- [ ] **Automated Test Coverage:** Unit tests for concurrency calculation across simulated GPU configurations and parallel pipeline execution.
