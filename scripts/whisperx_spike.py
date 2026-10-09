#!/usr/bin/env python3
"""WhisperX environment spike and benchmark script.

Loads audio, transcribes with Whisper, aligns words to timestamps using wav2vec2,
and benchmarks execution stages across devices (cpu, mps) and compute types.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run WhisperX transcription and forced alignment spike."
    )
    parser.add_argument(
        "--audio",
        type=Path,
        default=Path("tests/fixtures/sample_16k.wav"),
        help="Path to input audio file (default: tests/fixtures/sample_16k.wav)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="small",
        help="Whisper model name (default: small)",
    )
    parser.add_argument(
        "--device",
        type=str,
        choices=["auto", "cpu", "mps", "cuda"],
        default="auto",
        help="Device for Whisper model (auto = cuda if available else cpu, default: auto)",
    )
    parser.add_argument(
        "--align-device",
        type=str,
        choices=["auto", "cpu", "mps", "cuda"],
        default=None,
        help="Device for wav2vec2 alignment model (default: same as --device)",
    )
    parser.add_argument(
        "--compute-type",
        type=str,
        default=None,
        help="Compute type for Whisper model (default: float16 on cuda, int8 on cpu)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=16,
        help="Batch size for transcription (default: 16)",
    )
    parser.add_argument(
        "--language",
        type=str,
        default="en",
        help="Audio language code (default: en)",
    )
    parser.add_argument(
        "--limit-words",
        type=int,
        default=0,
        help="Limit number of printed words (0 = print all, default: 0)",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional path to save full alignment result JSON",
    )
    return parser.parse_args()


def run_spike(args: argparse.Namespace) -> int:
    audio_path = args.audio.resolve()
    if not audio_path.exists():
        print(f"Error: audio file not found at {audio_path}", file=sys.stderr)
        return 1

    total_start = time.perf_counter()

    # Step 1: Import whisperx and resolve auto device
    t0 = time.perf_counter()
    print("Importing whisperx and torch...")
    try:
        import torch
        import whisperx
    except ImportError as e:
        print(f"ImportError: {e}", file=sys.stderr)
        print("Ensure whisperx is installed: pip install -e '.[align]'", file=sys.stderr)
        return 1

    t_import = time.perf_counter() - t0

    # Auto-detect device: CUDA if available (e.g. PC/Linux), otherwise CPU (macOS / PC without CUDA)
    device = ("cuda" if torch.cuda.is_available() else "cpu") if args.device == "auto" else args.device
    align_device = device if (args.align_device is None or args.align_device == "auto") else args.align_device
    compute_type = args.compute_type or ("float16" if device == "cuda" else "int8")

    print("=" * 70)
    print("EchoPage WhisperX Environment Spike")
    print("=" * 70)
    print(f"Audio file:      {audio_path} ({audio_path.stat().st_size:,} bytes)")
    print(f"Whisper Model:   {args.model}")
    print(f"Whisper Device:  {device} (CUDA available: {torch.cuda.is_available()})")
    print(f"Align Device:    {align_device}")
    print(f"Compute Type:    {compute_type}")
    print(f"Batch Size:      {args.batch_size}")
    print(f"Language:        {args.language}")
    print("-" * 70)

    print(f"Imported whisperx (v{getattr(whisperx, '__version__', 'unknown')}) and torch (v{torch.__version__}) in {t_import:.2f}s")
    print(f"PyTorch MPS available: {torch.backends.mps.is_available()}, built: {torch.backends.mps.is_built()}")

    # Step 2: Load audio
    t0 = time.perf_counter()
    print(f"\nLoading audio: {audio_path}...")
    audio = whisperx.load_audio(str(audio_path))
    audio_duration = len(audio) / 16000.0  # whisperx resamples audio to 16kHz
    t_audio = time.perf_counter() - t0
    print(f"Audio loaded in {t_audio:.2f}s (duration: {audio_duration:.2f}s, samples: {len(audio):,})")

    # Step 3: Load Whisper model
    t0 = time.perf_counter()
    print(f"\nLoading Whisper model '{args.model}' (device={device}, compute_type={compute_type})...")
    try:
        model = whisperx.load_model(
            args.model,
            device,
            compute_type=compute_type,
            language=args.language,
        )
    except Exception as e:
        print(f"\nERROR loading Whisper model: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    t_load_whisper = time.perf_counter() - t0
    print(f"Whisper model loaded in {t_load_whisper:.2f}s")

    # Step 4: Transcribe audio
    t0 = time.perf_counter()
    print(f"\nTranscribing audio (batch_size={args.batch_size})...")
    result = model.transcribe(audio, batch_size=args.batch_size)
    t_transcribe = time.perf_counter() - t0
    segments = result.get("segments", [])
    print(f"Transcription complete in {t_transcribe:.2f}s ({len(segments)} segments extracted)")
    for i, seg in enumerate(segments):
        print(f"  [{seg.get('start', 0.0):.2f}s -> {seg.get('end', 0.0):.2f}s] {seg.get('text', '').strip()}")

    # Step 5: Load alignment model
    t0 = time.perf_counter()
    print(f"\nLoading wav2vec2 alignment model for language '{result.get('language', args.language)}' (device={align_device})...")
    try:
        model_a, metadata = whisperx.load_align_model(
            language_code=result.get("language", args.language),
            device=align_device,
        )
    except Exception as e:
        print(f"\nERROR loading alignment model on {align_device}: {type(e).__name__}: {e}", file=sys.stderr)
        return 3
    t_load_align = time.perf_counter() - t0
    print(f"Alignment model loaded in {t_load_align:.2f}s")

    # Step 6: Align segments to word timestamps
    t0 = time.perf_counter()
    print(f"\nAligning words to audio...")
    try:
        aligned_result = whisperx.align(
            segments,
            model_a,
            metadata,
            audio,
            align_device,
            return_char_alignments=False,
        )
    except Exception as e:
        print(f"\nERROR during alignment on {align_device}: {type(e).__name__}: {e}", file=sys.stderr)
        return 4
    t_align = time.perf_counter() - t0
    print(f"Alignment complete in {t_align:.2f}s")

    # Step 7: Inspect and print word timings
    print("\n" + "=" * 70)
    print("WORD TIMINGS (start -> end seconds)")
    print("=" * 70)
    aligned_words = []
    for seg_idx, segment in enumerate(aligned_result.get("segments", [])):
        words = segment.get("words", [])
        for w in words:
            word_text = w.get("word", "")
            start = w.get("start")
            end = w.get("end")
            score = w.get("score")
            aligned_words.append((word_text, start, end, score, seg_idx))

    words_to_show = aligned_words if args.limit_words == 0 else aligned_words[:args.limit_words]
    print(f"{'INDEX':<6} {'START':<9} {'END':<9} {'DURATION':<10} {'SCORE':<8} {'WORD'}")
    print("-" * 70)
    for idx, (word_text, start, end, score, _seg_idx) in enumerate(words_to_show, start=1):
        if start is not None and end is not None:
            dur = end - start
            start_str = f"{start:.3f}s"
            end_str = f"{end:.3f}s"
            dur_str = f"{dur:.3f}s"
        else:
            start_str = "None"
            end_str = "None"
            dur_str = "None"
        score_str = f"{score:.2f}" if score is not None else "N/A"
        print(f"{idx:<6} {start_str:<9} {end_str:<9} {dur_str:<10} {score_str:<8} {word_text}")

    if args.limit_words > 0 and len(aligned_words) > args.limit_words:
        print(f"... and {len(aligned_words) - args.limit_words} more words (total: {len(aligned_words)})")

    total_time = time.perf_counter() - total_start

    # Save JSON if requested
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(aligned_result, f, indent=2, ensure_ascii=False)
        print(f"\nSaved alignment JSON to: {args.json_out}")

    # Summary metrics
    print("\n" + "=" * 70)
    print("BENCHMARK SUMMARY")
    print("=" * 70)
    print(f"Audio Duration:        {audio_duration:.2f}s")
    print(f"Total Words Aligned:   {len(aligned_words)}")
    print(f"Import Time:           {t_import:.2f}s")
    print(f"Whisper Model Load:    {t_load_whisper:.2f}s")
    print(f"Transcription Time:    {t_transcribe:.2f}s ({audio_duration / max(t_transcribe, 0.001):.2f}x realtime)")
    print(f"Align Model Load:      {t_load_align:.2f}s")
    print(f"Alignment Time:        {t_align:.2f}s ({audio_duration / max(t_align, 0.001):.2f}x realtime)")
    print(f"Total Wall Clock Time: {total_time:.2f}s")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(run_spike(parse_args()))
