"""Unit tests for the EchoPage alignment.json data contract and validation."""

import io
import json
from pathlib import Path

import pytest

from echopage.alignment import (
    ALIGNMENT_SCHEMA,
    AlignedChapter,
    AlignmentError,
    AlignmentValidationError,
    TimelineEntry,
    format_element_id,
    is_valid_element_id,
    load_alignment,
    parse_element_id,
    save_alignment,
    validate_alignment,
)
from echopage.parser import parse_epub


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def make_valid_chapter(
    spine_id: str = "chapter01",
    xhtml_name: str = "chapter01.xhtml",
    audio_name: str = "part_0.m4b",
    entries: list[dict] | None = None,
) -> AlignedChapter:
    """Helper to build a valid AlignedChapter."""
    if entries is None:
        entries = [
            {
                "element_id": "mo_s_0001",
                "text": "First sentence.",
                "start_ms": 100,
                "end_ms": 1500,
                "confidence": 0.98,
                "block_xpath": "/*/*[2]/*/*[1]",
                "char_start": 0,
                "char_end": 15,
            },
            {
                "element_id": "mo_s_0002",
                "text": "Second sentence.",
                "start_ms": 1600,
                "end_ms": 3200,
                "confidence": 0.95,
                "block_xpath": "/*/*[2]/*/*[2]",
                "char_start": 0,
                "char_end": 16,
            },
        ]
    return AlignedChapter(
        spine_item_id=spine_id,
        xhtml_filename=xhtml_name,
        audio_filename=audio_name,
        timeline=[TimelineEntry(e) for e in entries],
    )


# ---------------------------------------------------------------------------
# 1. Round-Trip Tests (Acceptance Criterion 1)
# ---------------------------------------------------------------------------

def test_save_and_load_round_trip_file(tmp_path: Path):
    """Test save_alignment to disk then load_alignment gives identical data."""
    ch1 = make_valid_chapter("ch1", "ch1.xhtml", "audio1.m4b")
    ch2 = make_valid_chapter(
        "ch2",
        "ch2.xhtml",
        "audio2.m4b",
        [
            {
                "element_id": "mo_s_0003",
                "text": "Third sentence in chapter 2.",
                "start_ms": 200,
                "end_ms": 1800,
                "confidence": 1.0,
                "block_xpath": "/*/*[2]/*/*[1]",
                "char_start": 0,
                "char_end": 28,
            }
        ],
    )
    original = [ch1, ch2]
    out_file = tmp_path / "test_align.json"

    # Save
    json_str = save_alignment(original, out_file)
    assert out_file.is_file()
    assert len(json_str) > 0

    # Load
    loaded = load_alignment(out_file)
    assert len(loaded) == len(original)

    for orig_ch, load_ch in zip(original, loaded):
        assert orig_ch.spine_item_id == load_ch.spine_item_id
        assert orig_ch.xhtml_filename == load_ch.xhtml_filename
        assert orig_ch.audio_filename == load_ch.audio_filename
        assert len(orig_ch.timeline) == len(load_ch.timeline)
        assert orig_ch.to_dict() == load_ch.to_dict()


def test_save_and_load_round_trip_stream():
    """Test save_alignment to StringIO and load_alignment from StringIO."""
    original = [make_valid_chapter()]
    stream = io.StringIO()

    save_alignment(original, stream)
    stream.seek(0)

    loaded = load_alignment(stream)
    assert len(loaded) == 1
    assert loaded[0].to_dict() == original[0].to_dict()


def test_save_and_load_round_trip_string():
    """Test save_alignment returning a string and load_alignment from raw JSON string."""
    original = [make_valid_chapter()]
    json_str = save_alignment(original, path_or_file=None)
    assert isinstance(json_str, str)

    loaded = load_alignment(json_str)
    assert len(loaded) == 1
    assert loaded[0].to_dict() == original[0].to_dict()


# ---------------------------------------------------------------------------
# 2. Validation Rejection Tests (Acceptance Criterion 2)
# ---------------------------------------------------------------------------

def test_validation_rejects_duplicate_ids_within_chapter():
    """Duplicate element_id within the same chapter must be rejected with a clear message."""
    bad_entries = [
        {"element_id": "mo_s_0001", "text": "First", "start_ms": 100, "end_ms": 200},
        {"element_id": "mo_s_0001", "text": "Duplicate", "start_ms": 300, "end_ms": 400},
    ]
    ch = make_valid_chapter(entries=bad_entries)

    with pytest.raises(AlignmentValidationError) as exc_info:
        validate_alignment([ch])

    msg = str(exc_info.value)
    assert "Duplicate element_id 'mo_s_0001'" in msg
    assert "All element IDs must be unique across the entire book" in msg


def test_validation_rejects_duplicate_ids_across_chapters():
    """Duplicate element_id across different chapters must be rejected with a clear message."""
    ch1 = make_valid_chapter(
        "ch1",
        entries=[{"element_id": "mo_s_0001", "text": "A", "start_ms": 100, "end_ms": 200}],
    )
    ch2 = make_valid_chapter(
        "ch2",
        entries=[{"element_id": "mo_s_0001", "text": "B", "start_ms": 100, "end_ms": 200}],
    )

    with pytest.raises(AlignmentValidationError) as exc_info:
        validate_alignment([ch1, ch2])

    msg = str(exc_info.value)
    assert "Duplicate element_id 'mo_s_0001'" in msg
    assert "ch1" in msg
    assert "ch2" in msg


def test_validation_rejects_negative_start_time():
    """Negative start_ms must be rejected with a clear message."""
    bad_entries = [
        {"element_id": "mo_s_0001", "text": "Text", "start_ms": -50, "end_ms": 200},
    ]
    ch = make_valid_chapter(entries=bad_entries)

    with pytest.raises(AlignmentValidationError) as exc_info:
        validate_alignment([ch])

    msg = str(exc_info.value)
    assert "Negative timestamp" in msg
    assert "mo_s_0001" in msg
    assert "-50" in msg
    assert "non-negative" in msg


def test_validation_rejects_negative_end_time():
    """Negative end_ms must be rejected with a clear message."""
    bad_entries = [
        {"element_id": "mo_s_0001", "text": "Text", "start_ms": -100, "end_ms": -50},
    ]
    ch = make_valid_chapter(entries=bad_entries)

    with pytest.raises(AlignmentValidationError) as exc_info:
        validate_alignment([ch])

    msg = str(exc_info.value)
    assert "Negative timestamp" in msg
    assert "non-negative" in msg


def test_validation_rejects_zero_duration_end_equals_start():
    """end_ms == start_ms must be rejected with a clear message."""
    bad_entries = [
        {"element_id": "mo_s_0001", "text": "Text", "start_ms": 500, "end_ms": 500},
    ]
    ch = make_valid_chapter(entries=bad_entries)

    with pytest.raises(AlignmentValidationError) as exc_info:
        validate_alignment([ch])

    msg = str(exc_info.value)
    assert "Invalid duration in element 'mo_s_0001'" in msg
    assert "end_ms (500) must be strictly greater than start_ms (500)" in msg


def test_validation_rejects_negative_duration_end_less_than_start():
    """end_ms < start_ms must be rejected with a clear message."""
    bad_entries = [
        {"element_id": "mo_s_0001", "text": "Text", "start_ms": 800, "end_ms": 400},
    ]
    ch = make_valid_chapter(entries=bad_entries)

    with pytest.raises(AlignmentValidationError) as exc_info:
        validate_alignment([ch])

    msg = str(exc_info.value)
    assert "Invalid duration" in msg
    assert "end_ms (400) must be strictly greater than start_ms (800)" in msg


def test_validation_rejects_out_of_order_timestamps():
    """Sequential entries with out-of-order timestamps must be rejected."""
    bad_entries = [
        {"element_id": "mo_s_0001", "text": "First", "start_ms": 1000, "end_ms": 2000},
        {"element_id": "mo_s_0002", "text": "Second", "start_ms": 500, "end_ms": 1500},
    ]
    ch = make_valid_chapter(entries=bad_entries)

    with pytest.raises(AlignmentValidationError) as exc_info:
        validate_alignment([ch])

    msg = str(exc_info.value)
    assert "out of order" in msg.lower()
    assert "mo_s_0002" in msg
    assert "mo_s_0001" in msg


def test_validation_rejects_overlapping_timestamps_by_default():
    """Overlapping sequential entries are rejected by default with a clear message."""
    bad_entries = [
        {"element_id": "mo_s_0001", "text": "First", "start_ms": 1000, "end_ms": 2000},
        {"element_id": "mo_s_0002", "text": "Second", "start_ms": 1800, "end_ms": 2800},
    ]
    ch = make_valid_chapter(entries=bad_entries)

    with pytest.raises(AlignmentValidationError) as exc_info:
        validate_alignment([ch])

    msg = str(exc_info.value)
    assert "out of order" in msg.lower() or "overlap" in msg.lower()


def test_validation_allows_overlap_when_flag_enabled():
    """When allow_overlap=True, monotonic start times with partial overlap are accepted."""
    overlapping_entries = [
        {"element_id": "mo_s_0001", "text": "First", "start_ms": 1000, "end_ms": 2000},
        {"element_id": "mo_s_0002", "text": "Second", "start_ms": 1800, "end_ms": 2800},
    ]
    ch = make_valid_chapter(entries=overlapping_entries)
    # Should not raise
    validate_alignment([ch], allow_overlap=True)


def test_validation_rejects_missing_required_fields():
    """Missing required fields in chapters and entries must raise clear errors."""
    with pytest.raises(AlignmentValidationError) as exc:
        validate_alignment("not a list")
    assert "expected list or sequence" in str(exc.value)

    with pytest.raises(AlignmentValidationError) as exc:
        validate_alignment([{"spine_item_id": "", "xhtml_filename": "a", "audio_filename": "b", "timeline": []}])
    assert "missing required non-empty field 'spine_item_id'" in str(exc.value)

    with pytest.raises(AlignmentValidationError) as exc:
        validate_alignment([{"spine_item_id": "c1", "xhtml_filename": "", "audio_filename": "b", "timeline": []}])
    assert "missing required non-empty field 'xhtml_filename'" in str(exc.value)

    with pytest.raises(AlignmentValidationError) as exc:
        validate_alignment([{"spine_item_id": "c1", "xhtml_filename": "a", "audio_filename": "", "timeline": []}])
    assert "missing required non-empty field 'audio_filename'" in str(exc.value)

    with pytest.raises(AlignmentValidationError) as exc:
        validate_alignment([{
            "spine_item_id": "c1",
            "xhtml_filename": "a.xhtml",
            "audio_filename": "a.mp3",
            "timeline": [{"element_id": "", "text": "hi", "start_ms": 0, "end_ms": 10}],
        }])
    assert "missing required field 'element_id'" in str(exc.value)


def test_validation_rejects_invalid_types():
    """Non-integer/non-numeric timestamps or boolean timestamps must be rejected."""
    bad_entry = {
        "spine_item_id": "c1",
        "xhtml_filename": "a.xhtml",
        "audio_filename": "a.mp3",
        "timeline": [{"element_id": "mo_s_0001", "text": "hi", "start_ms": True, "end_ms": 100}],
    }
    with pytest.raises(AlignmentValidationError) as exc:
        validate_alignment([bad_entry])
    assert "invalid 'start_ms'" in str(exc.value)


def test_validate_alignment_rejects_float_timestamps():
    """Verify float timestamps are rejected to enforce schema integer conformance."""
    bad_entry = {
        "spine_item_id": "c1",
        "xhtml_filename": "a.xhtml",
        "audio_filename": "a.mp3",
        "timeline": [{"element_id": "mo_s_0001", "text": "hi", "start_ms": 12.5, "end_ms": 100}],
    }
    with pytest.raises(AlignmentValidationError) as exc:
        validate_alignment([bad_entry])
    assert "invalid 'start_ms'" in str(exc.value)

    bad_entry2 = {
        "spine_item_id": "c1",
        "xhtml_filename": "a.xhtml",
        "audio_filename": "a.mp3",
        "timeline": [{"element_id": "mo_s_0001", "text": "hi", "start_ms": 0, "end_ms": 100.0}],
    }
    with pytest.raises(AlignmentValidationError) as exc:
        validate_alignment([bad_entry2])
    assert "invalid 'end_ms'" in str(exc.value)



# ---------------------------------------------------------------------------
# 3. ID Scheme & Helper Tests (Task Item 4)
# ---------------------------------------------------------------------------

def test_format_element_id():
    """format_element_id formats zero-padded IDs according to the specification."""
    assert format_element_id(1) == "mo_s_0001"
    assert format_element_id(42) == "mo_s_0042"
    assert format_element_id(999) == "mo_s_0999"
    assert format_element_id(1000) == "mo_s_1000"
    assert format_element_id(12345) == "mo_s_12345"

    with pytest.raises(ValueError):
        format_element_id(-1)


def test_is_valid_element_id():
    """is_valid_element_id checks standard EchoPage ID format."""
    assert is_valid_element_id("mo_s_0001") is True
    assert is_valid_element_id("mo_s_0042") is True
    assert is_valid_element_id("mo_s_12345") is True
    assert is_valid_element_id("mo_s_1") is False  # not zero-padded
    assert is_valid_element_id("mo_s_01") is False
    assert is_valid_element_id("span_0001") is False
    assert is_valid_element_id("") is False
    assert is_valid_element_id(123) is False  # type: ignore


def test_parse_element_id():
    """parse_element_id extracts integer index from valid IDs."""
    assert parse_element_id("mo_s_0001") == 1
    assert parse_element_id("mo_s_0042") == 42
    assert parse_element_id("mo_s_12345") == 12345
    assert parse_element_id("invalid") is None


# ---------------------------------------------------------------------------
# 4. Dataclass and Dict Compatibility Tests
# ---------------------------------------------------------------------------

def test_timeline_entry_attributes_and_dict_access():
    """TimelineEntry supports both attribute access and dict indexing."""
    entry = TimelineEntry(
        element_id="mo_s_0001",
        text="Sample text",
        start_ms=150,
        end_ms=950,
        confidence=0.92,
        block_xpath="/*/*[2]/*/*[1]",
        char_start=0,
        char_end=11,
    )
    # Attribute access
    assert entry.element_id == "mo_s_0001"
    assert entry.text == "Sample text"
    assert entry.start_ms == 150
    assert entry.end_ms == 950
    assert entry.duration_ms == 800
    assert entry.confidence == 0.92
    assert entry.block_xpath == "/*/*[2]/*/*[1]"
    assert entry.char_start == 0
    assert entry.char_end == 11

    # Dict access
    assert entry["element_id"] == "mo_s_0001"
    assert entry["start_ms"] == 150
    assert entry.get("end_ms") == 950
    assert "confidence" in entry

    # Mutation
    entry["start_ms"] = 200
    assert entry.start_ms == 200

    # Serialization
    d = entry.to_dict()
    assert d["start_ms"] == 200
    assert d["element_id"] == "mo_s_0001"


def test_aligned_chapter_attributes_and_dict_access():
    """AlignedChapter supports attribute access, dict indexing, and converts timeline dicts."""
    ch = AlignedChapter({
        "spine_item_id": "ch01",
        "xhtml_filename": "ch01.xhtml",
        "audio_filename": "part_0.m4b",
        "timeline": [
            {"element_id": "mo_s_0001", "text": "Hello", "start_ms": 0, "end_ms": 100}
        ],
    })
    assert ch.spine_item_id == "ch01"
    assert ch.xhtml_filename == "ch01.xhtml"
    assert ch.audio_filename == "part_0.m4b"
    assert len(ch.timeline) == 1
    assert isinstance(ch.timeline[0], TimelineEntry)
    assert ch.timeline[0].element_id == "mo_s_0001"

    assert ch["spine_item_id"] == "ch01"
    assert len(ch["timeline"]) == 1

    d = ch.to_dict()
    assert d["spine_item_id"] == "ch01"
    assert d["timeline"][0]["element_id"] == "mo_s_0001"


# ---------------------------------------------------------------------------
# 5. Fixture Alignment Sample Validation (Acceptance Criterion 3)
# ---------------------------------------------------------------------------

def test_sample_file_validates_and_matches_fixture_epub():
    """The sample file validates under load_alignment and matches tests/fixtures/book.epub."""
    sample_path = Path("tests/fixtures/alignment.sample.json")
    epub_path = Path("tests/fixtures/book.epub")

    assert sample_path.is_file(), f"Sample alignment fixture missing: {sample_path}"
    assert epub_path.is_file(), f"Fixture EPUB missing: {epub_path}"

    # 1. Load and validate sample file
    chapters = load_alignment(sample_path, validate=True)
    assert len(chapters) == 2

    # 2. Unpack and parse EPUB
    epub_data = parse_epub(epub_path)
    epub_chapters = epub_data["chapters"]
    assert len(epub_chapters) == 2

    total_sentences = 0
    # 3. Verify 100% exact match between sample alignment entries and EPUB sentences
    for ch_idx, (sample_ch, epub_ch) in enumerate(zip(chapters, epub_chapters)):
        assert sample_ch.spine_item_id == epub_ch["id"]
        assert sample_ch.xhtml_filename == epub_ch["href"]
        assert len(sample_ch.timeline) == len(epub_ch["sentences"])

        for entry, sent in zip(sample_ch.timeline, epub_ch["sentences"]):
            total_sentences += 1
            assert entry.element_id == sent["element_id"]
            assert entry.text == sent["text"]
            assert entry.block_xpath == sent["block_xpath"]
            assert entry.char_start == sent["char_start"]
            assert entry.char_end == sent["char_end"]
            assert entry.start_ms < entry.end_ms
            assert entry.confidence >= 0.8

    assert total_sentences == 13, f"Expected 13 fixture sentences, got {total_sentences}"


def test_schema_structure():
    """ALIGNMENT_SCHEMA is defined with draft-07 and all required properties."""
    assert ALIGNMENT_SCHEMA["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert ALIGNMENT_SCHEMA["type"] == "array"
    ch_props = ALIGNMENT_SCHEMA["items"]["properties"]
    assert "spine_item_id" in ch_props
    assert "xhtml_filename" in ch_props
    assert "audio_filename" in ch_props
    assert "timeline" in ch_props
    entry_props = ch_props["timeline"]["items"]["properties"]
    assert "element_id" in entry_props
    assert "text" in entry_props
    assert "start_ms" in entry_props
    assert "end_ms" in entry_props
    assert "confidence" in entry_props
    assert "block_xpath" in entry_props
    assert "char_start" in entry_props
    assert "char_end" in entry_props
