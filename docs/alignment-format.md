# EchoPage alignment.json Data Contract

## 1. Overview

`alignment.json` serves as the intermediate contract and decoupling boundary between:
- **Phase 2 (Aligner)**: Ingests EPUB text and audiobook audio, runs WhisperX transcription and sequence alignment, and generates synchronized timestamps.
- **Phase 3 (Packager)**: Consumes the timestamps and XHTML DOM mapping to inject `<span id="...">` tags, synthesize SMIL 3.0 Media Overlays, and assemble the final EPUB 3 container.

By defining a strict, validated schema, the Packager can be developed and tested completely independently using canned alignment fixtures (`tests/fixtures/alignment.sample.json`) without requiring GPU execution or WhisperX inference.

---

## 2. JSON Structure

The root of `alignment.json` is a JSON array of **Chapter** objects ordered by the EPUB spine reading sequence.

```json
[
  {
    "spine_item_id": "chapter01",
    "xhtml_filename": "chapter01.xhtml",
    "audio_filename": "part_0.m4b",
    "timeline": [
      {
        "element_id": "mo_s_0001",
        "text": "Chapter 1: The Tortoise and the Hare",
        "start_ms": 31,
        "end_ms": 2014,
        "confidence": 1.0,
        "block_xpath": "/*/*[2]/*/*[1]",
        "char_start": 0,
        "char_end": 36
      },
      {
        "element_id": "mo_s_0002",
        "text": "The Hare was once boasting of his speed before the other animals.",
        "start_ms": 2295,
        "end_ms": 5360,
        "confidence": 1.0,
        "block_xpath": "/*/*[2]/*/*[2]",
        "char_start": 0,
        "char_end": 65
      }
    ]
  }
]
```

---

## 3. Chapter Schema

Each item in the root array represents an EPUB spine item mapped to an audio track:

| Field | Type | Required | Description |
|---|---|---|---|
| `spine_item_id` | `string` | **Yes** | Manifest `id` in the EPUB OPF package (e.g. `"chapter01"`). Non-empty. |
| `xhtml_filename` | `string` | **Yes** | Basename of the XHTML document file in EPUB (e.g. `"chapter01.xhtml"`). |
| `audio_filename` | `string` | **Yes** | Basename of the corresponding audio file (e.g. `"part_0.m4b"`). |
| `timeline` | `array` | **Yes** | Chronological list of sentence timing entries for this chapter. |

---

## 4. Timeline Entry Schema

Each item in `timeline` represents a single synchronized sentence or clause:

| Field | Type | Required | Description |
|---|---|---|---|
| `element_id` | `string` | **Yes** | Unique element identifier across the entire book. Format: `mo_s_NNNN` (e.g. `"mo_s_0001"`). |
| `text` | `string` | **Yes** | Exact text content of the sentence as extracted from EPUB. |
| `start_ms` | `integer` | **Yes** | Audio clip start offset in integer milliseconds (`>= 0`). |
| `end_ms` | `integer` | **Yes** | Audio clip end offset in integer milliseconds (`> start_ms`). |
| `confidence` | `float` | No | Alignment score between `0.0` and `1.0` (fraction of matched words). |
| `block_xpath` | `string` | No | Positional XPath to parent block element in the XHTML DOM (e.g. `/*/*[2]/*/*[1]`). |
| `char_start` | `integer` | No | 0-indexed start character offset within parent DOM block element text. |
| `char_end` | `integer` | No | 0-indexed end character offset within parent DOM block element text. |

---

## 5. Invariants and Validation Rules

The contract enforces the following invariants. Any violation raises `AlignmentValidationError` (inheriting from both `AlignmentError` and `ValueError`) with a specific, descriptive message:

1. **Global ID Uniqueness**:
   - Every `element_id` must be unique across the entire book (across all chapters).
   - Duplicate IDs are rejected with a message detailing the duplicated ID and the conflicting chapters.
2. **ID Scheme**:
   - IDs follow the zero-padded format: `mo_s_0001`, `mo_s_0002`, etc.
   - Zero-padding defaults to 4 digits (`mo_s_{index:04d}`).
3. **Non-negative Timestamps**:
   - Both `start_ms >= 0` and `end_ms >= 0`.
   - Negative values are rejected.
4. **Strictly Positive Durations**:
   - `end_ms > start_ms` is strictly enforced.
   - Zero durations (`end_ms == start_ms`) or inversions (`end_ms < start_ms`) are rejected.
5. **Chronological Ordering**:
   - Entries within a chapter timeline must appear in sequential time order (`start_ms >= prev.start_ms`).
   - By default, sequential clips must not overlap (`start_ms >= prev.end_ms`).
6. **Character Offset Guarantee**:
   - `parent_block_text[char_start:char_end] == text` allows the Packager to locate and wrap the exact sentence in `<span id="...">` tags without ambiguity.

---

## 6. Python API Reference

The `echopage.alignment` module provides typed dataclasses, serializers, deserializers, and validation functions:

### Dataclasses
```python
from echopage.alignment import TimelineEntry, AlignedChapter

# Dataclass with attribute and dict-like access
entry = TimelineEntry(
    element_id="mo_s_0001",
    text="Chapter 1: The Tortoise and the Hare",
    start_ms=31,
    end_ms=2014,
    confidence=1.0,
    block_xpath="/*/*[2]/*/*[1]",
    char_start=0,
    char_end=36,
)

# Attribute access
print(entry.element_id, entry.duration_ms)  # "mo_s_0001", 1983

# Dict access & serialization
print(entry["start_ms"])  # 31
d = entry.to_dict()
```

### Loading & Saving
```python
from echopage.alignment import load_alignment, save_alignment

# Save to file or stream (validates automatically)
save_alignment(chapters, "alignment.json", indent=2)

# Load from file, path, or string (validates automatically)
chapters = load_alignment("alignment.json")
```

### Direct Validation
```python
from echopage.alignment import validate_alignment

# Validate in-memory structures or dictionaries
validate_alignment(chapters)
```

### ID Helpers
```python
from echopage.alignment import format_element_id, is_valid_element_id, parse_element_id

formatted = format_element_id(42)  # "mo_s_0042"
valid = is_valid_element_id("mo_s_0042")  # True
idx = parse_element_id("mo_s_0042")  # 42
```

---

## 7. JSON Schema (Draft 7)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "EchoPage Alignment Format",
  "description": "Schema for alignment.json contract between aligner and packager",
  "type": "array",
  "items": {
    "type": "object",
    "required": ["spine_item_id", "xhtml_filename", "audio_filename", "timeline"],
    "properties": {
      "spine_item_id": { "type": "string", "minLength": 1 },
      "xhtml_filename": { "type": "string", "minLength": 1 },
      "audio_filename": { "type": "string", "minLength": 1 },
      "timeline": {
        "type": "array",
        "items": {
          "type": "object",
          "required": ["element_id", "text", "start_ms", "end_ms"],
          "properties": {
            "element_id": {
              "type": "string",
              "pattern": "^mo_s_\\d{4,}$"
            },
            "text": { "type": "string" },
            "start_ms": { "type": "integer", "minimum": 0 },
            "end_ms": { "type": "integer", "minimum": 1 },
            "confidence": { "type": "number", "minimum": 0.0, "maximum": 1.0 },
            "block_xpath": { "type": "string" },
            "char_start": { "type": "integer", "minimum": 0 },
            "char_end": { "type": "integer", "minimum": 0 }
          },
          "additionalProperties": true
        }
      }
    },
    "additionalProperties": true
  }
}
```
