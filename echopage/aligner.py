"""Aligner module: Match EPUB sentences to audio using WhisperX and sequence alignment."""

from __future__ import annotations

import difflib
import logging
import re
import shutil
import time
from pathlib import Path
from typing import Any, Sequence, Union

from echopage.logger import format_duration

from echopage.alignment import (
    AlignedChapter,
    AlignmentError,
    AlignmentValidationError,
    TimelineEntry,
    format_element_id,
    is_valid_element_id,
    load_alignment,
    save_alignment,
    validate_alignment,
)
from echopage.audio import AudioUnit, prepare_audio_units, to_wav16k
from echopage.automap import (
    align_chapter_subsequence,
    detect_non_narrated_section,
    normalize_chapter_title,
    title_similarity,
)
from echopage.parser import Sentence, parse_epub

# Alias for external convenience
auto_map_chapters = align_chapter_subsequence

log = logging.getLogger("echopage.aligner")


class AlignmentMismatchError(AlignmentError, ValueError):
    """Raised when the number of EPUB spine chapters does not match the audio units."""


class HeardWord(dict):
    """Represents a timed word recognized by WhisperX."""

    @property
    def word(self) -> str:
        return str(self.get("word", ""))

    @property
    def start(self) -> float | None:
        val = self.get("start")
        return float(val) if val is not None else None

    @property
    def end(self) -> float | None:
        val = self.get("end")
        return float(val) if val is not None else None

    @property
    def score(self) -> float | None:
        val = self.get("score")
        return float(val) if val is not None else None


def normalize_word(text: str) -> str:
    """Normalize a word for alignment: lowercase and strip surrounding punctuation.

    Leaves alphanumeric characters and internal contractions intact.
    Examples:
        'Mr.' -> 'mr'
        '\"Hello,\"' -> 'hello'
        'don\\'t' -> 'don\\'t'
        '1.' -> '1'
    """
    if not text:
        return ""
    # Strip non-word characters from beginning and end
    cleaned = re.sub(r"^[^\w]+|[^\w]+$", "", text.lower())
    return cleaned


def tokenize_words(text: str) -> list[str]:
    """Split a sentence into whitespace/punctuation-separated words."""
    if not text:
        return []
    # Split by whitespace and dashes/em-dashes while preserving word tokens
    raw_tokens = re.split(r"[\s—–]+", text.strip())
    return [t for t in raw_tokens if t]


def match_words(
    epub_words: Sequence[str],
    heard_words: Sequence[Union[dict, HeardWord]],
) -> list[tuple[int, int]]:
    """Pure function: Match EPUB normalized words to heard normalized words.

    Parameters
    ----------
    epub_words : Sequence[str]
        List of raw or normalized EPUB words.
    heard_words : Sequence[Union[dict, HeardWord]]
        List of heard words with 'word' attribute or key.

    Returns
    -------
    list[tuple[int, int]]
        List of (epub_word_index, heard_word_index) pairs for all matched words.
    """
    norm_epub = [normalize_word(w) for w in epub_words]
    norm_heard = [
        normalize_word(w.get("word", "") if isinstance(w, dict) else getattr(w, "word", str(w)))
        for w in heard_words
    ]

    # Map only non-empty normalized tokens
    epub_indexed = [(i, w) for i, w in enumerate(norm_epub) if w]
    heard_indexed = [(j, w) for j, w in enumerate(norm_heard) if w]

    if not epub_indexed or not heard_indexed:
        return []

    epub_tokens = [w for _, w in epub_indexed]
    heard_tokens = [w for _, w in heard_indexed]

    # Sequence alignment with difflib (autojunk=False ensures frequent words like 'the' are matched)
    matcher = difflib.SequenceMatcher(None, epub_tokens, heard_tokens, autojunk=False)
    matches: list[tuple[int, int]] = []

    for block in matcher.get_matching_blocks():
        # block is (epub_sub_idx, heard_sub_idx, size)
        for k in range(block.size):
            orig_epub_idx = epub_indexed[block.a + k][0]
            orig_heard_idx = heard_indexed[block.b + k][0]
            matches.append((orig_epub_idx, orig_heard_idx))

    return matches


def align_sentence_words(
    sentences: Sequence[Union[dict, Sentence, str]],
    heard_words: Sequence[Union[dict, HeardWord]],
    audio_duration: float = 0.0,
    chapter_id: str = "",
    min_sentence_duration_s: float = 0.050,
) -> list[TimelineEntry]:
    """Pure function: Assign timestamps and confidence to each sentence from heard words.

    Parameters
    ----------
    sentences : Sequence[Union[dict, Sentence, str]]
        List of sentences (dict, Sentence object, or plain string).
    heard_words : Sequence[Union[dict, HeardWord]]
        List of heard word dicts with 'word', 'start', 'end', and optional 'score'.
    audio_duration : float, optional
        Total audio duration in seconds.
    chapter_id : str, optional
        Chapter ID or title for logging.
    min_sentence_duration_s : float, optional
        Minimum duration in seconds for each sentence (default 50ms).

    Returns
    -------
    list[TimelineEntry]
        List of aligned timeline entries with strict monotonic integer millisecond times:
        `start_ms < end_ms`, `next_start_ms >= prev_end_ms`.
    """
    parsed_sentences: list[dict] = []
    for i, s in enumerate(sentences):
        if isinstance(s, str):
            parsed_sentences.append({
                "element_id": f"mo_s_{i + 1:04d}",
                "text": s,
                "block_xpath": "",
                "char_start": 0,
                "char_end": len(s),
            })
        elif isinstance(s, dict):
            parsed_sentences.append({
                "element_id": str(s.get("element_id", s.get("element_id_placeholder", f"mo_s_{i + 1:04d}"))),
                "text": str(s.get("text", "")),
                "block_xpath": str(s.get("block_xpath", "")),
                "char_start": int(s.get("char_start", 0)),
                "char_end": int(s.get("char_end", len(str(s.get("text", ""))))),
            })
        else:
            raise TypeError(f"Unsupported sentence type: {type(s)}")

    if not parsed_sentences:
        return []

    # Flatten sentence words into continuous stream
    # Each item: (sentence_idx, word_idx_in_sent, word_text)
    epub_stream: list[tuple[int, int, str]] = []
    sentence_word_counts: list[int] = []

    for s_idx, sent in enumerate(parsed_sentences):
        words = tokenize_words(sent["text"])
        sentence_word_counts.append(len(words))
        for w_idx, w in enumerate(words):
            epub_stream.append((s_idx, w_idx, w))

    flat_epub_words = [item[2] for item in epub_stream]

    # Run sequence alignment
    matches = match_words(flat_epub_words, heard_words)

    # Collect matched timestamps and matched word count per sentence
    sentence_matched_times: list[list[tuple[float, float]]] = [[] for _ in parsed_sentences]
    sentence_matched_counts: list[int] = [0 for _ in parsed_sentences]

    for epub_idx, heard_idx in matches:
        s_idx, _, _ = epub_stream[epub_idx]
        hw = heard_words[heard_idx]
        w_start = hw.get("start") if isinstance(hw, dict) else getattr(hw, "start", None)
        w_end = hw.get("end") if isinstance(hw, dict) else getattr(hw, "end", None)

        sentence_matched_counts[s_idx] += 1
        if w_start is not None and w_end is not None:
            sentence_matched_times[s_idx].append((float(w_start), float(w_end)))

    # Initial time boundaries (None if unmatched)
    raw_spans: list[tuple[float | None, float | None]] = []
    for s_idx in range(len(parsed_sentences)):
        times = sentence_matched_times[s_idx]
        if times:
            first_start = min(t[0] for t in times)
            last_end = max(t[1] for t in times)
            raw_spans.append((first_start, last_end))
        else:
            raw_spans.append((None, None))

    # Gap interpolation for unmatched sentences
    interpolated_spans = _interpolate_unmatched_gaps(
        raw_spans,
        parsed_sentences,
        audio_duration=audio_duration,
        min_sentence_duration_s=min_sentence_duration_s,
    )

    # Enforce monotonic times: start <= end, next_start >= prev_end
    # and strictly start_ms < end_ms
    timeline: list[TimelineEntry] = []
    prev_end_ms = 0

    for s_idx, sent in enumerate(parsed_sentences):
        s_start, s_end = interpolated_spans[s_idx]
        total_words = sentence_word_counts[s_idx]
        matched_count = sentence_matched_counts[s_idx]
        confidence = (matched_count / total_words) if total_words > 0 else 1.0
        confidence = round(min(1.0, max(0.0, confidence)), 3)

        if confidence < 0.5:
            log.warning(
                "Low confidence alignment (%.2f) in %s: %s",
                confidence,
                chapter_id or "chapter",
                sent["text"],
            )

        start_ms = int(round(s_start * 1000))
        end_ms = int(round(s_end * 1000))

        # Enforce non-decreasing progression
        if start_ms < prev_end_ms:
            start_ms = prev_end_ms

        min_ms = int(round(min_sentence_duration_s * 1000))
        if min_ms < 1:
            min_ms = 1

        if end_ms <= start_ms:
            end_ms = start_ms + min_ms

        # never point past the end of the audio (SMIL would reference beyond EOF)
        duration_ms = int(round(audio_duration * 1000))
        if duration_ms > start_ms and end_ms > duration_ms:
            end_ms = duration_ms

        prev_end_ms = end_ms

        entry = TimelineEntry({
            "element_id": sent["element_id"],
            "text": sent["text"],
            "start_ms": start_ms,
            "end_ms": end_ms,
            "confidence": confidence,
            "block_xpath": sent["block_xpath"],
            "char_start": sent["char_start"],
            "char_end": sent["char_end"],
        })
        timeline.append(entry)

    return timeline


def _interpolate_unmatched_gaps(
    spans: list[tuple[float | None, float | None]],
    sentences: list[dict],
    audio_duration: float,
    min_sentence_duration_s: float,
) -> list[tuple[float, float]]:
    """Fill gaps in timestamps by interpolating between neighboring matched sentences."""
    n = len(spans)
    result: list[tuple[float, float]] = [(0.0, 0.0)] * n

    # Copy over existing matched spans
    for i in range(n):
        s, e = spans[i]
        if s is not None and e is not None:
            result[i] = (s, max(e, s + min_sentence_duration_s))

    i = 0
    while i < n:
        if spans[i][0] is not None:
            i += 1
            continue

        # Found the start of an unmatched run
        run_start = i
        while i < n and spans[i][0] is None:
            i += 1
        run_end = i  # exclusive

        # Determine left bound
        if run_start > 0:
            left_bound = result[run_start - 1][1]
        else:
            left_bound = 0.0

        # Determine right bound
        if run_end < n:
            right_bound = result[run_end][0]
        else:
            right_bound = audio_duration if audio_duration > left_bound else (left_bound + (run_end - run_start) * 2.0)

        # Distribute available time across run sentences proportionally to text length
        run_length = run_end - run_start
        char_counts = [max(1, len(sentences[idx]["text"])) for idx in range(run_start, run_end)]
        total_chars = sum(char_counts)

        avail_time = max(run_length * min_sentence_duration_s, right_bound - left_bound)
        curr_t = left_bound

        for offset, idx in enumerate(range(run_start, run_end)):
            dur = (char_counts[offset] / total_chars) * avail_time
            dur = max(dur, min_sentence_duration_s)
            result[idx] = (curr_t, curr_t + dur)
            curr_t += dur

    return result


def map_audio_units_to_chapters(
    chapters: Sequence[dict],
    audio_units: Sequence[AudioUnit],
    manual_mapping: dict[int, int] | None = None,
    auto_map: bool = False,
    return_skipped: bool = False,
) -> Union[list[tuple[dict, AudioUnit]], tuple[list[tuple[dict, AudioUnit]], list[tuple[dict, str]]]]:
    """Map EPUB spine chapters to audio units.

    Parameters
    ----------
    chapters : Sequence[dict]
        Parsed EPUB spine chapters.
    audio_units : Sequence[AudioUnit]
        List of audio units.
    manual_mapping : dict[int, int], optional
        Optional dictionary mapping chapter index -> audio unit index.
    auto_map : bool, optional
        Whether to run automatic subsequence alignment and auto-skip non-narrated pages.
    return_skipped : bool, optional
        If True, returns a tuple of (matched_pairs, skipped_chapters_with_reasons).

    Returns
    -------
    list[tuple[dict, AudioUnit]] or tuple[list[tuple[dict, AudioUnit]], list[tuple[dict, str]]]
        List of (chapter_dict, audio_unit) pairs, or tuple with skipped chapters.

    Raises
    ------
    AlignmentMismatchError
        If chapter count does not equal audio unit count and no manual mapping is provided.
    """
    if manual_mapping is not None:
        pairs = []
        for ch_idx, au_idx in manual_mapping.items():
            if ch_idx < 0 or ch_idx >= len(chapters):
                raise AlignmentMismatchError(f"Manual mapping invalid chapter index: {ch_idx}")
            if au_idx < 0 or au_idx >= len(audio_units):
                raise AlignmentMismatchError(f"Manual mapping invalid audio unit index: {au_idx}")
            pairs.append((chapters[ch_idx], audio_units[au_idx]))
        return (pairs, []) if return_skipped else pairs

    if auto_map:
        matched, skipped = align_chapter_subsequence(chapters, audio_units)
        if len(matched) == len(audio_units):
            return (matched, skipped) if return_skipped else matched
        log.warning(
            "Auto-map could only match %d of %d audio units against %d chapters",
            len(matched), len(audio_units), len(chapters),
        )

    if len(chapters) != len(audio_units):
        epub_names = [c.get("id", f"ch_{i}") for i, c in enumerate(chapters)]
        audio_names = [u.title or u.path.name for u in audio_units]
        raise AlignmentMismatchError(
            f"Chapter count mismatch: EPUB contains {len(chapters)} spine chapter(s), "
            f"but {len(audio_units)} audio unit(s) were found.\n"
            f"  EPUB chapters: {', '.join(epub_names)}\n"
            f"  Audio units:   {', '.join(audio_names)}\n"
            f"Please verify audio files match the EPUB chapters or provide a manual chapter mapping."
        )

    pairs = list(zip(chapters, audio_units))
    return (pairs, []) if return_skipped else pairs


def get_optimal_model_size(device: str | None = None) -> str:
    """Determine the largest suitable Whisper model based on available hardware.

    Returns
    -------
    str
        'large-v3' for high-memory GPUs (>= 7GB VRAM, e.g. RTX 3070+),
        'medium' for mid-range GPUs (>= 5GB VRAM),
        'small' for lower-memory GPUs (>= 3GB VRAM) or CPU/MPS fallback.
    """
    try:
        import torch

        target_device = device
        if target_device is None or target_device == "auto":
            target_device = "cuda" if torch.cuda.is_available() else "cpu"
        elif target_device == "mps":
            target_device = "cpu"

        if target_device.startswith("cuda") and torch.cuda.is_available():
            device_idx = 0
            if ":" in target_device:
                try:
                    device_idx = int(target_device.split(":", 1)[1])
                except ValueError:
                    device_idx = 0

            device_props = torch.cuda.get_device_properties(device_idx)
            vram_gb = device_props.total_memory / (1024**3)
            log.info(
                "Detected CUDA GPU '%s' with %.1f GB VRAM",
                device_props.name,
                vram_gb,
            )
            if vram_gb >= 7.0:
                return "large-v3"
            elif vram_gb >= 5.0:
                return "medium"
            elif vram_gb >= 3.0:
                return "small"
            else:
                return "base"
    except Exception as e:
        log.debug("Could not inspect GPU memory for model selection: %s", e)

    # CPU/MPS fallback: 'small' is the practical upper limit for CPU inference speed
    return "small"


def transcribe_and_align_audio(
    audio_path: Union[str, Path],
    model_size: str = "auto",
    device: str | None = None,
    compute_type: str | None = None,
    batch_size: int = 16,
    language: str = "en",
    whisper_model: Any = None,
    align_model: Any = None,
    align_metadata: Any = None,
) -> tuple[list[HeardWord], float, Any, Any, Any]:
    """Transcribe and align an audio unit using WhisperX.

    Returns
    -------
    tuple[list[HeardWord], float, Any, Any, Any]
        (heard_words, audio_duration, whisper_model, align_model, align_metadata)
    """
    try:
        import torch
        import whisperx
    except ImportError as e:
        raise AlignmentError(
            "WhisperX is required for audio transcription and forced alignment. "
            "Please install the optional align extra: uv pip install -e '.[align]'"
        ) from e

    audio_file = Path(audio_path).resolve()
    if not audio_file.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_file}")

    # Auto-detect device and compute type
    if device is None or device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    elif device == "mps":
        log.warning("device 'mps' is unsupported by ctranslate2 (and slower for alignment); using cpu")
        device = "cpu"

    align_device = device
    if compute_type is None:
        compute_type = "float16" if device == "cuda" else "int8"

    if model_size is None or model_size == "auto":
        model_size = get_optimal_model_size(device=device)
        log.info("Auto-selected Whisper model '%s' for device '%s'", model_size, device)

    log.debug("Loading audio: %s", audio_file)
    audio = whisperx.load_audio(str(audio_file))
    audio_duration = float(len(audio)) / 16000.0

    # Load Whisper model if not passed
    if whisper_model is None:
        log.info("Loading Whisper model '%s' (device=%s, compute_type=%s)...", model_size, device, compute_type)
        t_model = time.perf_counter()
        whisper_model = whisperx.load_model(
            model_size,
            device,
            compute_type=compute_type,
            language=language,
        )
        model_elapsed = time.perf_counter() - t_model
        log.info("Whisper model '%s' loaded (took %s)", model_size, format_duration(model_elapsed))

    log.info("Transcribing audio (%s, duration: %s)...", audio_file.name, format_duration(audio_duration))
    t_transcribe = time.perf_counter()
    result = whisper_model.transcribe(audio, batch_size=batch_size)
    transcribe_elapsed = time.perf_counter() - t_transcribe
    speed_factor = (audio_duration / transcribe_elapsed) if transcribe_elapsed > 0 else 0.0
    log.info(
        "Transcribed audio '%s' in %s (%.1fx real-time)",
        audio_file.name,
        format_duration(transcribe_elapsed),
        speed_factor,
    )
    segments = result.get("segments", [])

    # Load wav2vec2 alignment model if not passed
    detected_lang = result.get("language", language)
    if align_model is None or align_metadata is None:
        log.info("Loading alignment model for language '%s' (device=%s)...", detected_lang, align_device)
        t_align_load = time.perf_counter()
        align_model, align_metadata = whisperx.load_align_model(
            language_code=detected_lang,
            device=align_device,
        )
        align_load_elapsed = time.perf_counter() - t_align_load
        log.info("Loaded alignment model for '%s' (took %s)", detected_lang, format_duration(align_load_elapsed))

    log.info("Aligning words to audio with wav2vec2...")
    t_align_words = time.perf_counter()
    aligned_result = whisperx.align(
        segments,
        align_model,
        align_metadata,
        audio,
        align_device,
        return_char_alignments=False,
    )

    heard_words: list[HeardWord] = []
    for segment in aligned_result.get("segments", []):
        for w in segment.get("words", []):
            heard_words.append(
                HeardWord({
                    "word": w.get("word", ""),
                    "start": w.get("start"),
                    "end": w.get("end"),
                    "score": w.get("score"),
                })
            )

    align_words_elapsed = time.perf_counter() - t_align_words
    log.info("Aligned %d words to audio (took %s)", len(heard_words), format_duration(align_words_elapsed))

    return heard_words, audio_duration, whisper_model, align_model, align_metadata


def align(
    book: Union[str, Path, dict],
    audio: Union[str, Path, Sequence[Union[str, Path]], Sequence[AudioUnit]],
    granularity: str = "sentence",
    model_size: str = "auto",
    device: str | None = None,
    compute_type: str | None = None,
    work_dir: Union[str, Path, None] = None,
    manual_mapping: dict[int, int] | None = None,
    precomputed_heard_words: Sequence[Sequence[Union[dict, HeardWord]]] | None = None,
    skip_spine: Sequence[str] | None = None,
    auto_map: bool = True,
) -> list[AlignedChapter]:
    """High-level pipeline: Match EPUB sentences to audio narration.

    Parameters
    ----------
    book : Union[str, Path, dict]
        Path to source EPUB file, or already parsed EPUB dictionary from `parse_epub`.
    audio : Union[str, Path, Sequence[Union[str, Path]], Sequence[AudioUnit]]
        Audio file path(s) or pre-split `AudioUnit` objects.
    granularity : str, optional
        Alignment granularity (currently supports 'sentence').
    model_size : str, optional
        Whisper model size ('auto', 'small', 'medium', 'large-v3', etc. Default: 'auto').
    device : str, optional
        Execution device ('cpu', 'cuda', 'auto').
    compute_type : str, optional
        Compute precision ('int8', 'float32', 'float16').
    work_dir : Union[str, Path, None], optional
        Working directory for unpacked EPUB and temporary split audio files.
    manual_mapping : dict[int, int], optional
        Explicit chapter-to-audio index mapping.
    precomputed_heard_words : Sequence[Sequence[Union[dict, HeardWord]]], optional
        Optional precomputed heard words per audio unit (for testing and offline runs).
    skip_spine : Sequence[str], optional
        Optional list of spine item IDs to exclude from alignment.
    auto_map : bool, optional
        Automatically match audio units to EPUB chapters and auto-skip non-narrated pages.

    Returns
    -------
    list[AlignedChapter]
        List of aligned chapter dictionaries with spine item ID, audio filename,
        and timeline containing start_ms and end_ms for each sentence.
    """
    if granularity != "sentence":
        raise NotImplementedError(f"Granularity '{granularity}' is not yet supported. Use 'sentence'.")

    # Resolve model size if auto
    if model_size is None or model_size == "auto":
        model_size = get_optimal_model_size(device=device)
        log.info("Auto-selected Whisper model size '%s' based on hardware capabilities", model_size)

    # Step 1: Parse EPUB if needed
    if isinstance(book, (str, Path)):
        epub_data = parse_epub(book, work_dir=work_dir)
    elif isinstance(book, dict) and "chapters" in book:
        epub_data = book
    else:
        raise TypeError(f"Invalid book argument: expected path or parsed epub dict, got {type(book)}")

    chapters = epub_data.get("chapters", [])
    if skip_spine:
        skip_set = {s.strip() for s in skip_spine if s.strip()}
        chapters = [c for c in chapters if c.get("id") not in skip_set]
    if manual_mapping is None:
        # cover/title/copyright pages have no sentences and no narration
        chapters = [c for c in chapters if c.get("sentences")]
    if not chapters:
        log.warning("EPUB has no spine chapters to align.")
        return []

    # Step 2: Prepare audio units
    if audio and isinstance(audio, (list, tuple)) and all(isinstance(a, AudioUnit) for a in audio):
        audio_units: list[AudioUnit] = list(audio)
    else:
        audio_units = prepare_audio_units(audio, work_dir=work_dir)

    # Step 3: Map audio units to EPUB spine chapters
    use_automap = auto_map and (skip_spine is None or len(chapters) != len(audio_units))
    mapped_pairs = map_audio_units_to_chapters(
        chapters,
        audio_units,
        manual_mapping=manual_mapping,
        auto_map=use_automap,
    )

    # Step 4: Transcribe, align, and match sentences
    aligned_chapters: list[AlignedChapter] = []
    whisper_model = None
    align_model = None
    align_metadata = None
    total_pairs = len(mapped_pairs)

    log.info("Starting forced alignment for %d chapter pairs...", total_pairs)
    t_align_total = time.perf_counter()

    for pair_idx, (chapter, audio_unit) in enumerate(mapped_pairs):
        t_ch = time.perf_counter()
        sentences = chapter.get("sentences", [])
        ch_id = chapter.get("id", f"chapter_{pair_idx + 1}")
        xhtml_name = Path(chapter.get("href", chapter.get("file_path", f"{ch_id}.xhtml"))).name
        audio_name = Path(audio_unit.path).name

        log.info(
            "[%d/%d] Aligning chapter '%s' (%d sentences) with audio unit '%s'...",
            pair_idx + 1,
            total_pairs,
            ch_id,
            len(sentences),
            audio_name,
        )

        if precomputed_heard_words is not None and pair_idx < len(precomputed_heard_words):
            heard_words = precomputed_heard_words[pair_idx]
            duration = audio_unit.duration or 0.0
        else:
            # Downsample audio unit to 16kHz WAV if needed for optimal WhisperX processing
            wav_path = audio_unit.path
            if wav_path.suffix.lower() != ".wav":
                temp_wav_dir = Path(work_dir) / "wav16k" if work_dir else wav_path.parent / "wav16k"
                # parent dir name = source stem, so part_0 of two books never collide
                wav_path = to_wav16k(audio_unit.path, temp_wav_dir / f"{wav_path.parent.name}_{wav_path.stem}_16k.wav")

            heard_words, duration, whisper_model, align_model, align_metadata = transcribe_and_align_audio(
                audio_path=wav_path,
                model_size=model_size,
                device=device,
                compute_type=compute_type,
                whisper_model=whisper_model,
                align_model=align_model,
                align_metadata=align_metadata,
            )

        timeline = align_sentence_words(
            sentences=sentences,
            heard_words=heard_words,
            audio_duration=duration or audio_unit.duration,
            chapter_id=ch_id,
        )

        aligned_chapters.append(
            AlignedChapter({
                "spine_item_id": ch_id,
                "xhtml_filename": xhtml_name,
                "audio_filename": audio_name,
                "timeline": timeline,
            })
        )

        ch_elapsed = time.perf_counter() - t_ch
        log.info(
            "[%d/%d] Finished aligning chapter '%s' (took %s)",
            pair_idx + 1,
            total_pairs,
            ch_id,
            format_duration(ch_elapsed),
        )

    total_align_elapsed = time.perf_counter() - t_align_total
    log.info(
        "Completed forced alignment for %d chapters (total time: %s)",
        len(aligned_chapters),
        format_duration(total_align_elapsed),
    )
    return aligned_chapters
