"""Alignment data contract, validation, and serialization module for EchoPage."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator, Sequence, TextIO, Union

log = logging.getLogger("echopage.alignment")


class AlignmentError(RuntimeError):
    """Base exception for alignment-related errors."""


class AlignmentValidationError(AlignmentError, ValueError):
    """Raised when an alignment structure violates schema or validation invariants."""


# ---------------------------------------------------------------------------
# ID Formatting & Helpers
# ---------------------------------------------------------------------------

DEFAULT_ID_PREFIX = "mo_s_"
DEFAULT_ID_PADDING = 4
ELEMENT_ID_REGEX = re.compile(r"^mo_s_\d{4,}$")


def format_element_id(index: int, prefix: str = DEFAULT_ID_PREFIX, pad: int = DEFAULT_ID_PADDING) -> str:
    """Generate a standard zero-padded element ID.

    Parameters
    ----------
    index : int
        1-based integer index of the sentence.
    prefix : str, default='mo_s_'
        ID prefix string.
    pad : int, default=4
        Minimum zero-padding width.

    Returns
    -------
    str
        Formatted ID, e.g. 'mo_s_0001', 'mo_s_0042'.
    """
    if index < 0:
        raise ValueError(f"Element index cannot be negative: {index}")
    return f"{prefix}{index:0{pad}d}"


def is_valid_element_id(element_id: str) -> bool:
    """Return True if element_id matches the standard EchoPage ID scheme ('mo_s_NNNN')."""
    if not isinstance(element_id, str):
        return False
    return bool(ELEMENT_ID_REGEX.match(element_id))


def parse_element_id(element_id: str) -> int | None:
    """Extract integer index from a valid element ID, or return None if invalid."""
    if not is_valid_element_id(element_id):
        return None
    try:
        return int(element_id[len(DEFAULT_ID_PREFIX):])
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Dataclasses with Dict Interface
# ---------------------------------------------------------------------------

@dataclass
class TimelineEntry:
    """Represents an aligned sentence timeline entry within a chapter.

    Combines strong dataclass typing and fields with backward-compatible
    dict subscripting (`entry["start_ms"]`) and serialization.
    """

    element_id: str
    text: str
    start_ms: int
    end_ms: int
    confidence: float = 1.0
    block_xpath: str = ""
    char_start: int = 0
    char_end: int = 0

    def __init__(
        self,
        *args: Any,
        element_id: str = "",
        text: str = "",
        start_ms: int = 0,
        end_ms: int = 0,
        confidence: float = 1.0,
        block_xpath: str = "",
        char_start: int = 0,
        char_end: int = 0,
        **kwargs: Any,
    ) -> None:
        if len(args) == 1 and isinstance(args[0], (dict, TimelineEntry)):
            data = dict(args[0]) if isinstance(args[0], dict) else args[0].to_dict()
            self.element_id = str(data.get("element_id", element_id))
            self.text = str(data.get("text", text))
            self.start_ms = int(data.get("start_ms", start_ms))
            self.end_ms = int(data.get("end_ms", end_ms))
            self.confidence = float(data.get("confidence", confidence))
            self.block_xpath = str(data.get("block_xpath", block_xpath))
            self.char_start = int(data.get("char_start", char_start))
            self.char_end = int(data.get("char_end", char_end))
        elif args:
            fields = ["element_id", "text", "start_ms", "end_ms", "confidence", "block_xpath", "char_start", "char_end"]
            assigned = dict(zip(fields, args))
            self.element_id = str(assigned.get("element_id", element_id))
            self.text = str(assigned.get("text", text))
            self.start_ms = int(assigned.get("start_ms", start_ms))
            self.end_ms = int(assigned.get("end_ms", end_ms))
            self.confidence = float(assigned.get("confidence", confidence))
            self.block_xpath = str(assigned.get("block_xpath", block_xpath))
            self.char_start = int(assigned.get("char_start", char_start))
            self.char_end = int(assigned.get("char_end", char_end))
        else:
            self.element_id = str(kwargs.get("element_id", element_id))
            self.text = str(kwargs.get("text", text))
            self.start_ms = int(kwargs.get("start_ms", start_ms))
            self.end_ms = int(kwargs.get("end_ms", end_ms))
            self.confidence = float(kwargs.get("confidence", confidence))
            self.block_xpath = str(kwargs.get("block_xpath", block_xpath))
            self.char_start = int(kwargs.get("char_start", char_start))
            self.char_end = int(kwargs.get("char_end", char_end))

    @property
    def duration_ms(self) -> int:
        """Duration of this timeline entry in milliseconds."""
        return max(0, self.end_ms - self.start_ms)

    def to_dict(self) -> dict[str, Any]:
        """Convert entry to a clean dictionary matching alignment.json schema."""
        return {
            "element_id": self.element_id,
            "text": self.text,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "confidence": round(self.confidence, 4) if isinstance(self.confidence, float) else self.confidence,
            "block_xpath": self.block_xpath,
            "char_start": self.char_start,
            "char_end": self.char_end,
        }

    # Dict compatibility methods
    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

    def __setitem__(self, key: str, value: Any) -> None:
        if hasattr(self, key):
            setattr(self, key, value)
        else:
            object.__setattr__(self, key, value)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def keys(self) -> list[str]:
        return ["element_id", "text", "start_ms", "end_ms", "confidence", "block_xpath", "char_start", "char_end"]

    def values(self) -> list[Any]:
        return [getattr(self, k) for k in self.keys()]

    def items(self) -> list[tuple[str, Any]]:
        return [(k, getattr(self, k)) for k in self.keys()]

    def __iter__(self) -> Iterator[str]:
        return iter(self.keys())


@dataclass
class AlignedChapter:
    """Represents an aligned chapter linking spine item, audio file, and timeline.

    Combines strong dataclass typing and fields with backward-compatible
    dict subscripting (`chapter["timeline"]`) and serialization.
    """

    spine_item_id: str
    xhtml_filename: str
    audio_filename: str
    timeline: list[TimelineEntry] = field(default_factory=list)

    def __init__(
        self,
        *args: Any,
        spine_item_id: str = "",
        xhtml_filename: str = "",
        audio_filename: str = "",
        timeline: Sequence[Union[dict, TimelineEntry]] | None = None,
        **kwargs: Any,
    ) -> None:
        if len(args) == 1 and isinstance(args[0], (dict, AlignedChapter)):
            data = dict(args[0]) if isinstance(args[0], dict) else args[0].to_dict()
            self.spine_item_id = str(data.get("spine_item_id", spine_item_id))
            self.xhtml_filename = str(data.get("xhtml_filename", xhtml_filename))
            self.audio_filename = str(data.get("audio_filename", audio_filename))
            raw_tl = data.get("timeline", timeline or [])
        elif args:
            fields = ["spine_item_id", "xhtml_filename", "audio_filename", "timeline"]
            assigned = dict(zip(fields, args))
            self.spine_item_id = str(assigned.get("spine_item_id", spine_item_id))
            self.xhtml_filename = str(assigned.get("xhtml_filename", xhtml_filename))
            self.audio_filename = str(assigned.get("audio_filename", audio_filename))
            raw_tl = assigned.get("timeline", timeline or [])
        else:
            self.spine_item_id = str(kwargs.get("spine_item_id", spine_item_id))
            self.xhtml_filename = str(kwargs.get("xhtml_filename", xhtml_filename))
            self.audio_filename = str(kwargs.get("audio_filename", audio_filename))
            raw_tl = kwargs.get("timeline", timeline or [])

        # Normalize timeline items into TimelineEntry
        self.timeline = [
            t if isinstance(t, TimelineEntry) else TimelineEntry(t)
            for t in (raw_tl or [])
        ]

    def to_dict(self) -> dict[str, Any]:
        """Convert chapter to a clean dictionary matching alignment.json schema."""
        return {
            "spine_item_id": self.spine_item_id,
            "xhtml_filename": self.xhtml_filename,
            "audio_filename": self.audio_filename,
            "timeline": [entry.to_dict() for entry in self.timeline],
        }

    # Dict compatibility methods
    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

    def __setitem__(self, key: str, value: Any) -> None:
        if key == "timeline" and isinstance(value, (list, tuple)):
            self.timeline = [t if isinstance(t, TimelineEntry) else TimelineEntry(t) for t in value]
        elif hasattr(self, key):
            setattr(self, key, value)
        else:
            object.__setattr__(self, key, value)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def keys(self) -> list[str]:
        return ["spine_item_id", "xhtml_filename", "audio_filename", "timeline"]

    def values(self) -> list[Any]:
        return [getattr(self, k) for k in self.keys()]

    def items(self) -> list[tuple[str, Any]]:
        return [(k, getattr(self, k)) for k in self.keys()]

    def __iter__(self) -> Iterator[str]:
        return iter(self.keys())


# ---------------------------------------------------------------------------
# JSON Schema Definition (Draft 7 / 2020-12 compatible)
# ---------------------------------------------------------------------------

ALIGNMENT_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "EchoPage Alignment Format",
    "description": "Schema for alignment.json contract between aligner and packager",
    "type": "array",
    "items": {
        "type": "object",
        "required": ["spine_item_id", "xhtml_filename", "audio_filename", "timeline"],
        "properties": {
            "spine_item_id": {
                "type": "string",
                "minLength": 1,
                "description": "Unique manifest item ID of the chapter in EPUB OPF spine",
            },
            "xhtml_filename": {
                "type": "string",
                "minLength": 1,
                "description": "Basename of the XHTML document file",
            },
            "audio_filename": {
                "type": "string",
                "minLength": 1,
                "description": "Basename of the chapter's corresponding audio file",
            },
            "timeline": {
                "type": "array",
                "description": "Chronological sentence timing entries for the chapter",
                "items": {
                    "type": "object",
                    "required": ["element_id", "text", "start_ms", "end_ms"],
                    "properties": {
                        "element_id": {
                            "type": "string",
                            "pattern": r"^mo_s_\d{4,}$",
                            "description": "Zero-padded unique element ID (e.g. 'mo_s_0001')",
                        },
                        "text": {
                            "type": "string",
                            "description": "Exact textual content of the sentence",
                        },
                        "start_ms": {
                            "type": "integer",
                            "minimum": 0,
                            "description": "Start timestamp in milliseconds (non-negative)",
                        },
                        "end_ms": {
                            "type": "integer",
                            "minimum": 1,
                            "description": "End timestamp in milliseconds (strictly > start_ms)",
                        },
                        "confidence": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                            "description": "Alignment match confidence score between 0.0 and 1.0",
                        },
                        "block_xpath": {
                            "type": "string",
                            "description": "Canonical XPath to parent DOM block element",
                        },
                        "char_start": {
                            "type": "integer",
                            "minimum": 0,
                            "description": "0-indexed start character offset within parent block text",
                        },
                        "char_end": {
                            "type": "integer",
                            "minimum": 0,
                            "description": "0-indexed end character offset within parent block text",
                        },
                    },
                    "additionalProperties": True,
                },
            },
        },
        "additionalProperties": True,
    },
}


# ---------------------------------------------------------------------------
# Validation Engine
# ---------------------------------------------------------------------------

def validate_alignment(
    alignment: Any,
    allow_overlap: bool = False,
) -> None:
    """Validate alignment data against schema invariants and book-wide rules.

    Validates:
    - Structure: list of chapters containing required fields.
    - Global uniqueness: each `element_id` must be unique across the entire book.
    - Non-negative times: `start_ms >= 0` and `end_ms >= 0`.
    - Strict duration: `end_ms > start_ms` for every entry.
    - Chronological ordering: `entry[i].start_ms >= prev_entry.start_ms` (and
      `entry[i].start_ms >= prev_entry.end_ms` unless `allow_overlap` is True).
    - Clear, descriptive error messages for every violation.

    Parameters
    ----------
    alignment : Any
        List of AlignedChapter objects or raw chapter dictionaries.
    allow_overlap : bool, default=False
        If False, requires sequential entries to not overlap (`start_ms >= prev.end_ms`).

    Raises
    ------
    AlignmentValidationError
        When any validation invariant is violated.
    """
    if not isinstance(alignment, (list, tuple)):
        raise AlignmentValidationError(
            f"Invalid alignment structure: expected list or sequence of chapters, got {type(alignment).__name__}."
        )

    seen_ids: dict[str, str] = {}  # element_id -> spine_item_id

    for ch_idx, ch in enumerate(alignment):
        if not isinstance(ch, (dict, AlignedChapter)):
            raise AlignmentValidationError(
                f"Chapter at index {ch_idx} must be a dict or AlignedChapter, got {type(ch).__name__}."
            )

        spine_id = str(ch.get("spine_item_id", "")).strip()
        if not spine_id:
            raise AlignmentValidationError(
                f"Chapter at index {ch_idx} is missing required non-empty field 'spine_item_id'."
            )

        xhtml_name = str(ch.get("xhtml_filename", "")).strip()
        if not xhtml_name:
            raise AlignmentValidationError(
                f"Chapter '{spine_id}' (index {ch_idx}) is missing required non-empty field 'xhtml_filename'."
            )

        audio_name = str(ch.get("audio_filename", "")).strip()
        if not audio_name:
            raise AlignmentValidationError(
                f"Chapter '{spine_id}' (index {ch_idx}) is missing required non-empty field 'audio_filename'."
            )

        timeline = ch.get("timeline")
        if timeline is None or not isinstance(timeline, (list, tuple)):
            raise AlignmentValidationError(
                f"Chapter '{spine_id}' has invalid 'timeline': expected list, got {type(timeline).__name__}."
            )

        prev_entry: TimelineEntry | dict | None = None

        for entry_idx, entry in enumerate(timeline):
            if not isinstance(entry, (dict, TimelineEntry)):
                raise AlignmentValidationError(
                    f"Timeline entry {entry_idx} in chapter '{spine_id}' must be a dict or TimelineEntry, "
                    f"got {type(entry).__name__}."
                )

            # 1. Element ID validation & uniqueness
            element_id = str(entry.get("element_id", "")).strip()
            if not element_id:
                raise AlignmentValidationError(
                    f"Timeline entry {entry_idx} in chapter '{spine_id}' is missing required field 'element_id'."
                )

            if element_id in seen_ids:
                prev_ch = seen_ids[element_id]
                raise AlignmentValidationError(
                    f"Duplicate element_id '{element_id}' found in chapter '{spine_id}' "
                    f"(previously seen in chapter '{prev_ch}'). "
                    f"All element IDs must be unique across the entire book."
                )
            seen_ids[element_id] = spine_id

            # 2. Text validation
            text = entry.get("text")
            if text is None or not isinstance(text, str):
                raise AlignmentValidationError(
                    f"Timeline entry '{element_id}' in chapter '{spine_id}' has invalid 'text': "
                    f"expected string, got {type(text).__name__}."
                )

            # 3. Timestamp numeric & non-negative validation
            start_raw = entry.get("start_ms")
            end_raw = entry.get("end_ms")

            if start_raw is None or not isinstance(start_raw, (int, float)) or isinstance(start_raw, bool):
                raise AlignmentValidationError(
                    f"Timeline entry '{element_id}' in chapter '{spine_id}' has invalid 'start_ms': "
                    f"expected integer, got {repr(start_raw)}."
                )
            if end_raw is None or not isinstance(end_raw, (int, float)) or isinstance(end_raw, bool):
                raise AlignmentValidationError(
                    f"Timeline entry '{element_id}' in chapter '{spine_id}' has invalid 'end_ms': "
                    f"expected integer, got {repr(end_raw)}."
                )

            start_ms = int(start_raw)
            end_ms = int(end_raw)

            if start_ms < 0 or end_ms < 0:
                raise AlignmentValidationError(
                    f"Negative timestamp in element '{element_id}' of chapter '{spine_id}': "
                    f"start_ms={start_ms}, end_ms={end_ms}. Timestamps must be non-negative (>= 0)."
                )

            # 4. Strict duration validation (end_ms > start_ms)
            if end_ms <= start_ms:
                raise AlignmentValidationError(
                    f"Invalid duration in element '{element_id}' of chapter '{spine_id}': "
                    f"end_ms ({end_ms}) must be strictly greater than start_ms ({start_ms})."
                )

            # 5. Chronological ordering validation
            if prev_entry is not None:
                prev_id = str(prev_entry.get("element_id", "prev"))
                prev_start = int(prev_entry.get("start_ms", 0))
                prev_end = int(prev_entry.get("end_ms", 0))

                if start_ms < prev_start:
                    raise AlignmentValidationError(
                        f"Timeline entries out of order in chapter '{spine_id}': "
                        f"element '{element_id}' start_ms ({start_ms}) is earlier than "
                        f"previous element '{prev_id}' start_ms ({prev_start}). "
                        f"Timestamps must appear in chronological order."
                    )

                if not allow_overlap and start_ms < prev_end:
                    raise AlignmentValidationError(
                        f"Timeline entries out of order in chapter '{spine_id}': "
                        f"element '{element_id}' start_ms ({start_ms}) is earlier than "
                        f"previous element '{prev_id}' end_ms ({prev_end}). "
                        f"Sequential clips must not overlap."
                    )

            # 6. Optional fields type validation if present
            confidence = entry.get("confidence")
            if confidence is not None and (not isinstance(confidence, (int, float)) or isinstance(confidence, bool)):
                raise AlignmentValidationError(
                    f"Timeline entry '{element_id}' in chapter '{spine_id}' has invalid 'confidence': "
                    f"expected float/number, got {repr(confidence)}."
                )

            prev_entry = entry


# ---------------------------------------------------------------------------
# Save & Load Alignment Functions
# ---------------------------------------------------------------------------

def save_alignment(
    alignment: Sequence[Union[AlignedChapter, dict]],
    path_or_file: Union[str, Path, TextIO, None] = None,
    indent: int = 2,
    validate: bool = True,
    ensure_ascii: bool = False,
) -> str:
    """Save and validate an alignment structure to JSON.

    Parameters
    ----------
    alignment : Sequence[Union[AlignedChapter, dict]]
        List of AlignedChapter objects or chapter dictionaries.
    path_or_file : Union[str, Path, TextIO, None], optional
        Destination file path, writable stream, or None. If None, returns JSON string.
    indent : int, default=2
        JSON indentation formatting.
    validate : bool, default=True
        Whether to run schema validation before saving.
    ensure_ascii : bool, default=False
        Whether to escape non-ASCII characters.

    Returns
    -------
    str
        JSON formatted string.

    Raises
    ------
    AlignmentValidationError
        If validation fails.
    """
    if validate:
        validate_alignment(alignment)

    # Convert to clean dictionaries
    serialized: list[dict[str, Any]] = []
    for item in alignment:
        if isinstance(item, AlignedChapter):
            serialized.append(item.to_dict())
        elif isinstance(item, dict):
            # Clean copy ensuring timeline entries are also serialized dicts
            ch_copy = dict(item)
            if "timeline" in ch_copy and isinstance(ch_copy["timeline"], (list, tuple)):
                ch_copy["timeline"] = [
                    t.to_dict() if isinstance(t, TimelineEntry) else dict(t)
                    for t in ch_copy["timeline"]
                ]
            serialized.append(ch_copy)
        else:
            raise AlignmentValidationError(
                f"Cannot serialize item of type {type(item).__name__}: expected AlignedChapter or dict."
            )

    json_str = json.dumps(serialized, indent=indent, ensure_ascii=ensure_ascii)

    if path_or_file is not None:
        if isinstance(path_or_file, (str, Path)):
            out_path = Path(path_or_file)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json_str, encoding="utf-8")
        elif hasattr(path_or_file, "write"):
            path_or_file.write(json_str)
        else:
            raise TypeError(f"Invalid path_or_file destination: {type(path_or_file)}")

    return json_str


def load_alignment(
    source: Union[str, Path, TextIO, Sequence[dict], dict],
    validate: bool = True,
    allow_overlap: bool = False,
) -> list[AlignedChapter]:
    """Load and validate an alignment structure from JSON file, stream, string, or data.

    Parameters
    ----------
    source : Union[str, Path, TextIO, Sequence[dict], dict]
        Source file path, open text file, raw JSON string, or parsed Python data structure.
    validate : bool, default=True
        Whether to validate the data against alignment invariants.
    allow_overlap : bool, default=False
        If False, enforces that sequential timeline entries within a chapter do not overlap.

    Returns
    -------
    list[AlignedChapter]
        List of AlignedChapter objects containing validated TimelineEntry items.

    Raises
    ------
    AlignmentValidationError
        If validation fails or structure is invalid.
    """
    data: Any

    if isinstance(source, str) and source.strip().startswith(("[", "{")):
        data = json.loads(source)
    elif isinstance(source, (str, Path)):
        source_path = Path(source)
        try:
            if source_path.is_file():
                content = source_path.read_text(encoding="utf-8")
                data = json.loads(content)
            else:
                raise FileNotFoundError(f"Alignment file not found: {source}")
        except OSError:
            # Fallback if string was too long or invalid path
            try:
                data = json.loads(str(source))
            except Exception:
                raise FileNotFoundError(f"Alignment file not found: {source}")
    elif hasattr(source, "read"):
        content = source.read()
        data = json.loads(content)
    elif isinstance(source, (list, tuple, dict)):
        data = source
    else:
        raise TypeError(f"Unsupported alignment source type: {type(source)}")

    # Allow single chapter dictionary by wrapping in list
    if isinstance(data, dict):
        data = [data]

    if not isinstance(data, list):
        raise AlignmentValidationError(
            f"Invalid alignment root format: expected list of chapters, got {type(data).__name__}."
        )

    # Convert to AlignedChapter objects
    chapters: list[AlignedChapter] = []
    for idx, item in enumerate(data):
        if isinstance(item, AlignedChapter):
            chapters.append(item)
        elif isinstance(item, dict):
            chapters.append(AlignedChapter(item))
        else:
            raise AlignmentValidationError(
                f"Chapter at index {idx} has invalid type: expected dict or AlignedChapter, got {type(item).__name__}."
            )

    if validate:
        validate_alignment(chapters, allow_overlap=allow_overlap)

    return chapters
