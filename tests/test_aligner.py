"""Unit and integration tests for the EchoPage Aligner module."""

import json
import logging
from pathlib import Path

import pytest

from echopage.aligner import (
    AlignedChapter,
    AlignmentError,
    AlignmentMismatchError,
    HeardWord,
    TimelineEntry,
    align,
    align_sentence_words,
    map_audio_units_to_chapters,
    match_words,
    normalize_word,
    tokenize_words,
)
from echopage.audio import AudioUnit
from echopage.parser import Sentence


# ---------------------------------------------------------------------------
# 1. Normalization & Tokenization Unit Tests
# ---------------------------------------------------------------------------

def test_normalize_word():
    assert normalize_word("Hello") == "hello"
    assert normalize_word("world!") == "world"
    assert normalize_word('"Quoted,"') == "quoted"
    assert normalize_word("Mr.") == "mr"
    assert normalize_word("don't") == "don't"
    assert normalize_word("1.") == "1"
    assert normalize_word("---") == ""
    assert normalize_word("") == ""


def test_tokenize_words():
    tokens = tokenize_words("The quick brown fox—lazy dog.")
    assert tokens == ["The", "quick", "brown", "fox", "lazy", "dog."]
    assert tokenize_words("") == []
    assert tokenize_words("   \n\t  ") == []


# ---------------------------------------------------------------------------
# 2. Pure Matching Function Tests (Fake Word Lists)
# ---------------------------------------------------------------------------

def test_pure_match_exact_match():
    epub = ["The", "Tortoise", "and", "the", "Hare"]
    heard = [
        {"word": "The", "start": 0.1, "end": 0.3},
        {"word": "tortoise", "start": 0.3, "end": 0.7},
        {"word": "and", "start": 0.7, "end": 0.8},
        {"word": "the", "start": 0.8, "end": 0.9},
        {"word": "hare.", "start": 0.9, "end": 1.4},
    ]
    matches = match_words(epub, heard)
    assert len(matches) == 5
    assert matches == [(0, 0), (1, 1), (2, 2), (3, 3), (4, 4)]


def test_pure_matching_fake_word_lists_exact_match():
    """Acceptance criterion: exact match with fake word lists."""
    sentences = [
        "The tortoise walked slowly.",
        "The hare ran fast.",
    ]
    heard_words = [
        {"word": "The", "start": 0.10, "end": 0.25},
        {"word": "tortoise", "start": 0.30, "end": 0.75},
        {"word": "walked", "start": 0.80, "end": 1.10},
        {"word": "slowly.", "start": 1.15, "end": 1.60},
        {"word": "The", "start": 2.00, "end": 2.15},
        {"word": "hare", "start": 2.20, "end": 2.50},
        {"word": "ran", "start": 2.55, "end": 2.80},
        {"word": "fast.", "start": 2.85, "end": 3.20},
    ]

    timeline = align_sentence_words(sentences, heard_words, audio_duration=4.0)
    assert len(timeline) == 2

    s0 = timeline[0]
    assert s0.text == "The tortoise walked slowly."
    assert s0.start_ms == 100
    assert s0.end_ms == 1600
    assert s0.confidence == 1.0

    s1 = timeline[1]
    assert s1.text == "The hare ran fast."
    assert s1.start_ms == 2000
    assert s1.end_ms == 3200
    assert s1.confidence == 1.0

    assert s0.start_ms < s0.end_ms <= s1.start_ms < s1.end_ms


def test_pure_matching_fake_word_lists_one_word_misheard():
    """Acceptance criterion: one word misheard in audio."""
    sentences = [
        "The hare was boasting of his speed.",
    ]
    # 'rabbit' heard instead of 'hare'
    heard_words = [
        {"word": "The", "start": 0.20, "end": 0.35},
        {"word": "rabbit", "start": 0.40, "end": 0.75},  # misheard word
        {"word": "was", "start": 0.80, "end": 0.95},
        {"word": "boasting", "start": 1.00, "end": 1.45},
        {"word": "of", "start": 1.50, "end": 1.60},
        {"word": "his", "start": 1.65, "end": 1.80},
        {"word": "speed.", "start": 1.85, "end": 2.30},
    ]

    timeline = align_sentence_words(sentences, heard_words, audio_duration=3.0)
    assert len(timeline) == 1
    s = timeline[0]

    # 6 out of 7 words matched: confidence ~ 0.857
    assert s.confidence == pytest.approx(6 / 7, abs=0.01)
    # Timestamps still span from the first matched word (The: 0.20s) to last (speed: 2.30s)
    assert s.start_ms == 200
    assert s.end_ms == 2300
    assert s.start_ms < s.end_ms


def test_pure_matching_fake_word_lists_one_sentence_missing_in_audio():
    """Acceptance criterion: one sentence missing in audio, interpolated between neighbours."""
    sentences = [
        "First sentence was spoken.",
        "Second sentence was completely omitted by narrator.",
        "Third sentence was spoken clearly.",
    ]
    # Sentence 2 is absent from heard words
    heard_words = [
        {"word": "First", "start": 0.50, "end": 0.80},
        {"word": "sentence", "start": 0.85, "end": 1.20},
        {"word": "was", "start": 1.25, "end": 1.40},
        {"word": "spoken.", "start": 1.45, "end": 1.90},
        # gap between 1.90s and 4.00s
        {"word": "Third", "start": 4.00, "end": 4.30},
        {"word": "sentence", "start": 4.35, "end": 4.70},
        {"word": "was", "start": 4.75, "end": 4.90},
        {"word": "spoken", "start": 4.95, "end": 5.30},
        {"word": "clearly.", "start": 5.35, "end": 5.80},
    ]

    timeline = align_sentence_words(sentences, heard_words, audio_duration=6.5)
    assert len(timeline) == 3

    s0, s1, s2 = timeline

    # Sentence 0
    assert s0.confidence == 1.0
    assert s0.start_ms == 500
    assert s0.end_ms == 1900

    # Sentence 1: missed completely -> confidence 0.0
    assert s1.confidence == 0.0
    # Interpolated inside gap [1900ms, 4000ms]
    assert s1.start_ms >= s0.end_ms
    assert s1.end_ms <= s2.start_ms
    assert s1.start_ms < s1.end_ms

    # Sentence 2
    assert s2.confidence == 1.0
    assert s2.start_ms == 4000
    assert s2.end_ms == 5800

    # Strict monotonicity
    assert s0.start_ms < s0.end_ms <= s1.start_ms < s1.end_ms <= s2.start_ms < s2.end_ms


def test_pure_matching_fake_word_lists_extra_words_in_audio():
    """Acceptance criterion: extra words in audio (intro / chatter) do not disrupt sentence bounds."""
    sentences = [
        "The race began promptly at noon.",
    ]
    heard_words = [
        # Extra audio intro
        {"word": "Welcome", "start": 0.00, "end": 0.40},
        {"word": "everyone", "start": 0.45, "end": 0.85},
        {"word": "to", "start": 0.90, "end": 1.00},
        {"word": "the", "start": 1.05, "end": 1.15},
        {"word": "show.", "start": 1.20, "end": 1.60},
        # Actual sentence text
        {"word": "The", "start": 2.50, "end": 2.70},
        {"word": "race", "start": 2.75, "end": 3.05},
        {"word": "began", "start": 3.10, "end": 3.45},
        {"word": "promptly", "start": 3.50, "end": 3.90},
        {"word": "at", "start": 3.95, "end": 4.10},
        {"word": "noon.", "start": 4.15, "end": 4.60},
        # Extra trailing audio
        {"word": "End", "start": 5.00, "end": 5.30},
        {"word": "of", "start": 5.35, "end": 5.50},
        {"word": "recording.", "start": 5.55, "end": 6.00},
    ]

    timeline = align_sentence_words(sentences, heard_words, audio_duration=6.5)
    assert len(timeline) == 1
    s = timeline[0]

    assert s.confidence == 1.0
    assert s.start_ms == 2500
    assert s.end_ms == 4600
    assert s.start_ms < s.end_ms


def test_pure_matching_unmatched_at_beginning_and_end():
    """Verify gap filling when initial or trailing sentences are unmatched."""
    sentences = [
        "Chapter Title Not Read Aloud",
        "This sentence is spoken.",
        "Epilogue Text Not Read Aloud",
    ]
    heard_words = [
        {"word": "This", "start": 2.00, "end": 2.30},
        {"word": "sentence", "start": 2.35, "end": 2.70},
        {"word": "is", "start": 2.75, "end": 2.90},
        {"word": "spoken.", "start": 2.95, "end": 3.50},
    ]

    timeline = align_sentence_words(sentences, heard_words, audio_duration=5.0)
    assert len(timeline) == 3

    s0, s1, s2 = timeline
    assert s0.confidence == 0.0
    assert s1.confidence == 1.0
    assert s2.confidence == 0.0

    # First sentence starts at 0ms and ends before or at s1.start_ms
    assert 0 <= s0.start_ms < s0.end_ms <= s1.start_ms
    assert s1.start_ms == 2000
    assert s1.end_ms == 3500
    # Last sentence begins at or after s1.end_ms and ends at or before audio_duration
    assert s1.end_ms <= s2.start_ms < s2.end_ms


def test_pure_matching_all_sentences_unmatched():
    """Verify fallback interpolation when zero words match in audio."""
    sentences = [
        "Unrelated sentence one.",
        "Unrelated sentence two.",
    ]
    heard_words = [
        {"word": "something", "start": 0.5, "end": 1.0},
        {"word": "else", "start": 1.2, "end": 1.8},
    ]

    timeline = align_sentence_words(sentences, heard_words, audio_duration=10.0)
    assert len(timeline) == 2
    for s in timeline:
        assert s.confidence == 0.0
        assert s.start_ms < s.end_ms

    assert timeline[0].end_ms <= timeline[1].start_ms


# ---------------------------------------------------------------------------
# 3. Monotonicity & Quality Invariant Tests
# ---------------------------------------------------------------------------

def test_monotonic_timestamps_with_overlapping_words():
    """If speech word timings slightly overlap or go backwards, timeline must strictly order."""
    sentences = [
        "Sentence A.",
        "Sentence B.",
    ]
    heard_words = [
        {"word": "Sentence", "start": 1.0, "end": 1.5},
        {"word": "A.", "start": 1.5, "end": 2.2},
        # Sentence B word start overlaps earlier than sentence A's end
        {"word": "Sentence", "start": 2.0, "end": 2.4},
        {"word": "B.", "start": 2.3, "end": 2.7},
    ]

    timeline = align_sentence_words(sentences, heard_words, audio_duration=4.0)
    s0, s1 = timeline
    assert s0.start_ms < s0.end_ms
    assert s1.start_ms < s1.end_ms
    assert s1.start_ms >= s0.end_ms


# ---------------------------------------------------------------------------
# 4. Low-Confidence Logging Tests
# ---------------------------------------------------------------------------

def test_low_confidence_logged(caplog):
    """Acceptance criterion: Low-confidence sentences are reported in the log with chapter and text."""
    sentences = [
        {"element_id": "mo_s_0001", "text": "This sentence was almost entirely misheard and skipped."},
    ]
    heard_words = [
        {"word": "This", "start": 0.5, "end": 0.8},  # only 1 out of 8 words matches -> 0.125 confidence
    ]

    with caplog.at_level(logging.WARNING, logger="echopage.aligner"):
        timeline = align_sentence_words(sentences, heard_words, audio_duration=2.0, chapter_id="chapter01")

    assert len(timeline) == 1
    assert timeline[0].confidence < 0.5

    # Check log message
    assert any(
        "Low confidence" in record.message
        and "chapter01" in record.message
        and "This sentence was almost entirely misheard" in record.message
        for record in caplog.records
    )


# ---------------------------------------------------------------------------
# 5. Chapter to Audio Unit Mapping Tests
# ---------------------------------------------------------------------------

def test_chapter_audio_count_mismatch_raises_actionable_error():
    """Acceptance criterion: Chapter/audio count mismatch gives an actionable error."""
    chapters = [{"id": "ch1"}, {"id": "ch2"}]
    audio_units = [AudioUnit(path=Path("ch1.mp3"), start_s=0.0, end_s=10.0, title="Ch 1")]

    with pytest.raises(AlignmentMismatchError) as exc_info:
        map_audio_units_to_chapters(chapters, audio_units)

    msg = str(exc_info.value)
    assert "Chapter count mismatch" in msg
    assert "EPUB contains 2 spine chapter(s)" in msg
    assert "1 audio unit(s) were found" in msg
    assert "ch1, ch2" in msg
    assert "manual chapter mapping" in msg


def test_chapter_audio_mapping_success_and_manual_override():
    chapters = [{"id": "ch1"}, {"id": "ch2"}]
    audio_units = [
        AudioUnit(path=Path("ch1.mp3"), start_s=0.0, end_s=10.0, title="Ch 1"),
        AudioUnit(path=Path("ch2.mp3"), start_s=10.0, end_s=20.0, title="Ch 2"),
    ]

    mapped = map_audio_units_to_chapters(chapters, audio_units)
    assert len(mapped) == 2
    assert mapped[0][0]["id"] == "ch1" and mapped[0][1].title == "Ch 1"
    assert mapped[1][0]["id"] == "ch2" and mapped[1][1].title == "Ch 2"

    # Manual mapping reverse order
    manual = {0: 1, 1: 0}
    mapped_manual = map_audio_units_to_chapters(chapters, audio_units, manual_mapping=manual)
    assert mapped_manual[0][1].title == "Ch 2"
    assert mapped_manual[1][1].title == "Ch 1"


# ---------------------------------------------------------------------------
# 6. Integration Test on Fixtures & Spot Checks
# ---------------------------------------------------------------------------

def test_fixture_alignment_invariants_and_spot_checks():
    """Acceptance criteria:
    - On the fixture, every sentence gets start_ms < end_ms, and all times are in order.
    - Spot check: 3 sentences' timestamps line up with the audio when played.
    """
    epub_path = Path(__file__).parent / "fixtures" / "book.epub"
    audio_path = Path(__file__).parent / "fixtures" / "book.m4b"

    results = align(epub_path, audio_path, model_size="small", device="cpu")
    assert len(results) == 2

    ch1 = results[0]
    ch2 = results[1]

    assert ch1.spine_item_id == "chapter01"
    assert len(ch1.timeline) == 8

    assert ch2.spine_item_id == "chapter02"
    assert len(ch2.timeline) == 5

    # Acceptance criterion: every sentence gets start_ms < end_ms, and all times are in order
    for ch in (ch1, ch2):
        prev_end_ms = 0
        for entry in ch.timeline:
            assert entry.start_ms < entry.end_ms, f"{entry.element_id}: start_ms ({entry.start_ms}) >= end_ms ({entry.end_ms})"
            assert entry.start_ms >= prev_end_ms, f"{entry.element_id}: start_ms ({entry.start_ms}) < prev_end_ms ({prev_end_ms})"
            assert entry.confidence >= 0.8, f"{entry.element_id}: low confidence {entry.confidence}"
            prev_end_ms = entry.end_ms

    # Acceptance criterion: Spot check 3 sentences' timestamps against audio narration:
    # 1. Chapter 1 Title (mo_s_0001): "Chapter 1: The Tortoise and the Hare"
    # Narration runs ~0.03s - ~2.01s
    s1 = ch1.timeline[0]
    assert s1.element_id == "mo_s_0001"
    assert s1.start_ms <= 100
    assert 1800 <= s1.end_ms <= 2200

    # 2. Chapter 1 Dialogue (mo_s_0004): 'Mr. Fox can witness my victories."'
    # Narration runs ~10.18s - ~12.19s
    s4 = ch1.timeline[3]
    assert s4.element_id == "mo_s_0004"
    assert 9800 <= s4.start_ms <= 10400
    assert 11800 <= s4.end_ms <= 12400

    # 3. Chapter 2 Title (mo_s_0009): "Chapter 2: The North Wind and the Sun"
    # Narration runs ~0.11s - ~2.30s within Chapter 2 audio segment
    s9 = ch2.timeline[0]
    assert s9.element_id == "mo_s_0009"
    assert s9.start_ms <= 200
    assert 2000 <= s9.end_ms <= 2500
