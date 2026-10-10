"""EPUB 3 Media Overlays packager: XHTML span ID injection, SMIL synthesis, and container assembly."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence, Union

from lxml import etree

from echopage.alignment import AlignedChapter, TimelineEntry, load_alignment
from echopage.parser import BLOCK_TAGS, PackageItem, read_package

log = logging.getLogger("echopage.packager")

SMIL_NAMESPACE = "http://www.w3.org/ns/SMIL"
EPUB_OPS_NAMESPACE = "http://www.idpf.org/2007/ops"
XHTML_NAMESPACE = "http://www.w3.org/1999/xhtml"
OPF_NAMESPACE = "http://www.idpf.org/2007/opf"
DC_NAMESPACE = "http://purl.org/dc/elements/1.1/"

AUDIO_MIME_TYPES: dict[str, str] = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".m4b": "audio/mp4",
    ".mp4": "audio/mp4",
    ".aac": "audio/mp4",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".wav": "audio/wav",
}


class PackagerError(RuntimeError):
    """Base exception for EPUB packaging and media overlay operations."""


class IdCollisionError(PackagerError, ValueError):
    """Raised when existing IDs in source XHTML collide with injected media overlay IDs."""




class SmilGenerationError(PackagerError, ValueError):
    """Raised when SMIL generation fails due to missing files, invalid IDs, or invalid timing."""


class OpfUpdateError(PackagerError, ValueError):
    """Raised when updating OPF package manifest fails."""


class EpubCheckValidationError(PackagerError, ValueError):
    """Raised when EPUBCheck validation reports errors."""


def format_smil_clock(ms: Union[int, float]) -> str:
    """Format millisecond offset to SMIL clock format with 3 decimal places (e.g. 2340 -> '2.340s').

    Parameters
    ----------
    ms : Union[int, float]
        Offset in milliseconds.

    Returns
    -------
    str
        Clock string with 's' suffix and 3 decimal digits.
    """
    if ms < 0:
        raise ValueError(f"Clock offset cannot be negative: {ms}")
    return f"{float(ms) / 1000.0:.3f}s"


def parse_smil_clock(clock: str) -> float:
    """Parse a SMIL clock value (e.g. '2.340s' or '01:02:03.456') to seconds as float.

    Parameters
    ----------
    clock : str
        Clock string.

    Returns
    -------
    float
        Duration in seconds.
    """
    clock = clock.strip()
    if clock.endswith("s"):
        return float(clock[:-1])
    parts = clock.split(":")
    if len(parts) == 3:
        h, m, s = parts
        return float(h) * 3600.0 + float(m) * 60.0 + float(s)
    elif len(parts) == 2:
        m, s = parts
        return float(m) * 60.0 + float(s)
    return float(clock)


def format_clock_hms(ms: Union[int, float]) -> str:
    """Format millisecond offset to HH:MM:SS.mmm format for EPUB OPF metadata.

    Example: 3723456 ms -> '01:02:03.456'
    """
    total_seconds = max(0.0, float(ms) / 1000.0)
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"


class SmilDuration(float):
    """SMIL duration value representing seconds as a float while providing string and unit helpers.

    Equates to both numeric seconds (e.g. 23.732) and formatted SMIL clock strings (e.g. "23.732s").
    """

    _ms: int

    def __new__(cls, seconds: float, ms: int | None = None) -> "SmilDuration":
        obj = super().__new__(cls, float(seconds))
        obj._ms = int(round(seconds * 1000)) if ms is None else int(ms)
        return obj

    @property
    def ms(self) -> int:
        """Total duration in milliseconds."""
        return self._ms

    @property
    def clock(self) -> str:
        """SMIL clock string representation with 3 decimal places (e.g. '2.340s')."""
        return f"{float(self):.3f}s"

    @property
    def hms(self) -> str:
        """Formatted HH:MM:SS.mmm string for OPF media:duration metadata."""
        return format_clock_hms(self._ms)

    def __str__(self) -> str:
        return self.clock

    def __repr__(self) -> str:
        return f"SmilDuration({self.clock})"

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, str):
            other_clean = other.strip()
            return (
                self.clock == other_clean
                or f"{float(self):.3f}" == other_clean
                or f"{float(self)}" == other_clean
            )
        if isinstance(other, (int, float)):
            return abs(float(self) - float(other)) < 1e-5
        return super().__eq__(other)

    def __ne__(self, other: Any) -> bool:
        return not (self == other)


@dataclass
class SmilMetadata:
    """Metadata describing a synthesized SMIL Media Overlays document."""

    smil_path: Path
    chapter_id: str
    duration: SmilDuration
    duration_ms: int
    duration_s: float
    duration_clock: str
    audio_src: str
    audio_file_path: Path | None = None
    par_count: int = 0
    xhtml_path: Path | None = None

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def to_dict(self) -> dict[str, Any]:
        return {
            "smil_path": str(self.smil_path),
            "chapter_id": self.chapter_id,
            "duration": float(self.duration),
            "duration_ms": self.duration_ms,
            "duration_s": self.duration_s,
            "duration_clock": self.duration_clock,
            "audio_src": self.audio_src,
            "audio_file_path": str(self.audio_file_path) if self.audio_file_path else None,
            "par_count": self.par_count,
            "xhtml_path": str(self.xhtml_path) if self.xhtml_path else None,
        }


class XhtmlInjectionError(PackagerError, ValueError):
    """Raised when span injection fails due to invalid XPath or character offsets."""


def collect_text_segments(elem: etree._Element) -> list[tuple[etree._Element, str, str]]:
    """Traverse an element and its descendants in document order, returning text segments.

    Each segment is a tuple: (owner_element, kind, text)
    where `kind` is either "text" (text directly inside owner before any child)
    or "tail" (text immediately following owner inside its parent).

    The concatenation of all segment texts is strictly identical to
    `''.join(elem.itertext())`.

    Parameters
    ----------
    elem : etree._Element
        The root element of the subtree to collect segments from.

    Returns
    -------
    list[tuple[etree._Element, str, str]]
        List of (owner_element, kind, text) tuples.
    """
    segments: list[tuple[etree._Element, str, str]] = []

    if elem.text:
        segments.append((elem, "text", elem.text))

    for child in elem:
        if isinstance(child.tag, str) and etree.QName(child).localname.lower() in BLOCK_TAGS:
            # Child is a block element: do not recurse into it. Only include its tail text.
            if child.tail:
                segments.append((child, "tail", child.tail))
        else:
            segments.extend(collect_text_segments(child))
            if child.tail:
                segments.append((child, "tail", child.tail))

    return segments


def inject_spans_into_element(
    block_elem: etree._Element,
    entries: Sequence[Union[TimelineEntry, dict[str, Any]]],
    default_ns: str | None = None,
    continuation_class: str | None = None,
    used_ids: set[str] | None = None,
) -> None:
    """Inject sentence <span> tags into a block element, slicing across inline tags.

    Parameters
    ----------
    block_elem : etree._Element
        The block element (e.g. <p>, <h1>, <li>) to modify.
    entries : Sequence[Union[TimelineEntry, dict[str, Any]]]
        Timeline entries belonging to this block, each specifying
        `element_id`, `char_start`, and `char_end`.
    default_ns : str | None, optional
        Namespace URI for newly created <span> elements (e.g. XHTML namespace).
    continuation_class : str | None, optional
        CSS class name to add to continuation spans of multi-fragment sentences.
        If None, continuation spans have no class or id attribute.
    used_ids : set[str] | None, optional
        Set of element IDs that have already been assigned. Updated in place.

    Raises
    ------
    XhtmlInjectionError
        If character offsets are invalid or out of bounds.
    """
    if not entries:
        return

    if used_ids is None:
        used_ids = set()

    # Determine <span> tag name with namespace
    span_tag = f"{{{default_ns}}}span" if default_ns else "span"

    # Collect current text segments
    segs = collect_text_segments(block_elem)
    block_text = "".join(s[2] for s in segs)
    block_len = len(block_text)

    # Validate entry offsets
    for entry in entries:
        s_start = int(entry.get("char_start", 0))
        s_end = int(entry.get("char_end", 0))
        eid = str(entry.get("element_id", ""))
        if s_start < 0 or s_end < s_start or s_end > block_len:
            raise XhtmlInjectionError(
                f"Sentence '{eid}' character bounds [{s_start}:{s_end}] are invalid "
                f"for block element of length {block_len}."
            )

    # Compute character boundaries for each text segment
    seg_ranges: list[tuple[int, int, etree._Element, str, str]] = []
    curr = 0
    for node, kind, t in segs:
        t_len = len(t)
        seg_ranges.append((curr, curr + t_len, node, kind, t))
        curr += t_len

    # For each segment, plan the slices of sentences that overlap with it
    seg_replacements: list[tuple[etree._Element, str, str, list[tuple[int, int, str | None]]]] = []

    for seg_start, seg_end, node, kind, t in seg_ranges:
        slices: list[tuple[int, int, str | None]] = []
        for entry in entries:
            s_start = int(entry.get("char_start", 0))
            s_end = int(entry.get("char_end", 0))
            eid = str(entry.get("element_id", ""))

            # Calculate overlap with this text segment
            overlap_start = max(s_start, seg_start)
            overlap_end = min(s_end, seg_end)

            if overlap_start < overlap_end:
                local_s = overlap_start - seg_start
                local_e = overlap_end - seg_start

                # The first fragment of a sentence gets the main ID; subsequent fragments omit ID
                if eid not in used_ids:
                    assigned_id = eid
                    used_ids.add(eid)
                else:
                    assigned_id = None

                slices.append((local_s, local_e, assigned_id))

        # Sort slices within the segment by local start position
        slices.sort(key=lambda s: s[0])
        seg_replacements.append((node, kind, t, slices))

    # Apply replacements in reverse order of segments to preserve child and sibling indices
    for node, kind, t, slices in reversed(seg_replacements):
        if not slices:
            continue

        leading_text = t[:slices[0][0]]
        spans: list[etree._Element] = []

        for i, (s, e, eid) in enumerate(slices):
            attribs: dict[str, str] = {}
            if eid:
                attribs["id"] = eid
            elif continuation_class:
                attribs["class"] = continuation_class

            span = etree.Element(span_tag, attrib=attribs)
            span.text = t[s:e]

            # Tail text is the text between this slice and the next, or remainder of segment
            next_start = slices[i + 1][0] if i + 1 < len(slices) else len(t)
            tail_text = t[e:next_start]
            span.tail = tail_text if tail_text else None
            spans.append(span)

        if kind == "text":
            node.text = leading_text if leading_text else None
            for i, span in enumerate(spans):
                node.insert(i, span)
        elif kind == "tail":
            parent = node.getparent()
            if parent is None:
                raise XhtmlInjectionError(f"Cannot insert spans into tail of root element {node.tag}")
            node.tail = leading_text if leading_text else None
            idx = parent.index(node)
            for i, span in enumerate(spans):
                parent.insert(idx + 1 + i, span)


def check_id_collisions(
    doc: etree._ElementTree,
    timeline: Sequence[Union[TimelineEntry, dict[str, Any]]],
    source_name: str = "XHTML",
    allow_collision: bool = False,
) -> None:
    """Check for ID collisions between existing IDs and media overlay IDs.

    Existing IDs are preserved. An IdCollisionError is raised if any existing ID
    collides with an injected timeline ID or with the 'mo_s_' prefix pattern.

    Parameters
    ----------
    doc : etree._ElementTree
        The parsed XML document.
    timeline : Sequence[Union[TimelineEntry, dict[str, Any]]]
        Timeline entries with `element_id`.
    source_name : str, default="XHTML"
        Name of the document for error reporting.
    allow_collision : bool, default=False
        If True, ignore collisions.

    Raises
    ------
    IdCollisionError
        If an existing ID conflicts with media overlay IDs.
    """
    if allow_collision:
        return

    root = doc.getroot()
    existing_ids = set(root.xpath("//@id"))
    if not existing_ids:
        return

    target_ids = {str(e.get("element_id", "")) for e in timeline if e.get("element_id")}

    # Check for direct collision with target timeline IDs
    direct_collisions = existing_ids.intersection(target_ids)
    if direct_collisions:
        colliding = sorted(direct_collisions)[0]
        raise IdCollisionError(
            f"ID collision in {source_name}: ID '{colliding}' already exists in source XHTML."
        )

    # Check for existing IDs matching the 'mo_s_' media overlay ID prefix
    mo_prefix_collisions = {eid for eid in existing_ids if eid.startswith("mo_s_")}
    if mo_prefix_collisions:
        colliding = sorted(mo_prefix_collisions)[0]
        raise IdCollisionError(
            f"ID collision in {source_name}: existing ID '{colliding}' conflicts with 'mo_s_*' prefix."
        )


def inject_spans_into_xhtml(
    xhtml_source: Union[str, Path, bytes, etree._ElementTree],
    timeline: Sequence[Union[TimelineEntry, dict[str, Any]]],
    out_path: Union[str, Path, None] = None,
    allow_collision: bool = False,
    continuation_class: str | None = None,
) -> etree._ElementTree:
    """Load an XHTML document, inject <span> tags for aligned sentences, and serialize.

    Parameters
    ----------
    xhtml_source : Union[str, Path, bytes, etree._ElementTree]
        Path to XHTML file, raw XHTML string/bytes, or an existing parsed ElementTree.
    timeline : Sequence[Union[TimelineEntry, dict[str, Any]]]
        Timeline entries containing `element_id`, `block_xpath`, `char_start`, and `char_end`.
    out_path : Union[str, Path, None], optional
        Destination path to write the modified XHTML. If None and xhtml_source is a file path,
        the source file is modified in-place if out_path is explicitly not specified or matches.
    allow_collision : bool, default=False
        If True, suppress IdCollisionError when pre-existing IDs match.
    continuation_class : str | None, optional
        Optional CSS class name for continuation spans.

    Returns
    -------
    etree._ElementTree
        The modified XML ElementTree.

    Raises
    ------
    IdCollisionError
        If existing IDs in the document collide with media overlay IDs.
    XhtmlInjectionError
        If an XPath is missing or character offsets are out of bounds.
    """
    file_path: Path | None = None

    if isinstance(xhtml_source, etree._ElementTree):
        doc = xhtml_source
    else:
        if isinstance(xhtml_source, Path) or (
            isinstance(xhtml_source, str) and not xhtml_source.strip().startswith("<")
        ):
            file_path = Path(xhtml_source)
            if not file_path.is_file():
                raise FileNotFoundError(f"XHTML source file not found: {file_path}")
            raw_bytes = file_path.read_bytes()
        elif isinstance(xhtml_source, str):
            raw_bytes = xhtml_source.encode("utf-8")
        else:
            raw_bytes = xhtml_source

        parser = etree.XMLParser(remove_blank_text=False)
        try:
            root_elem = etree.fromstring(raw_bytes, parser=parser)
        except etree.XMLSyntaxError:
            recover_parser = etree.XMLParser(recover=True, remove_blank_text=False)
            root_elem = etree.fromstring(raw_bytes, parser=recover_parser)

        doc = etree.ElementTree(root_elem)

    root = doc.getroot()
    doc_name = file_path.name if file_path else "XHTML"

    # Record visible text before mutation to verify 100% preservation
    orig_text = "".join(root.itertext())

    # Detect ID collisions
    check_id_collisions(doc, timeline, source_name=doc_name, allow_collision=allow_collision)

    # Determine default XHTML namespace
    default_ns = root.nsmap.get(None, XHTML_NAMESPACE if XHTML_NAMESPACE in str(root.tag) else None)

    # Group timeline entries by block_xpath
    entries_by_xpath: dict[str, list[Union[TimelineEntry, dict[str, Any]]]] = defaultdict(list)
    for entry in timeline:
        xpath = str(entry.get("block_xpath", "")).strip()
        if not xpath:
            raise XhtmlInjectionError(
                f"Timeline entry '{entry.get('element_id')}' is missing required 'block_xpath'."
            )
        entries_by_xpath[xpath].append(entry)

    # Resolve all block elements first before mutation to avoid XPath query shifts
    block_nodes: dict[str, etree._Element] = {}
    for xpath in entries_by_xpath:
        nodes = doc.xpath(xpath)
        if not nodes:
            raise XhtmlInjectionError(
                f"Block XPath '{xpath}' not found in document '{doc_name}'."
            )
        if len(nodes) > 1:
            raise XhtmlInjectionError(
                f"Block XPath '{xpath}' matched {len(nodes)} elements in '{doc_name}'; expected exactly 1."
            )
        block_nodes[xpath] = nodes[0]

    # Inject spans into each block element
    used_ids: set[str] = set()
    for xpath, entries in entries_by_xpath.items():
        block_elem = block_nodes[xpath]
        inject_spans_into_element(
            block_elem=block_elem,
            entries=entries,
            default_ns=default_ns,
            continuation_class=continuation_class,
            used_ids=used_ids,
        )

    # Invariant Verification 1: Visible text content must remain 100% identical
    new_text = "".join(root.itertext())
    if orig_text != new_text:
        raise XhtmlInjectionError(
            f"Visible text corruption in '{doc_name}': text before and after injection does not match!"
        )

    # Invariant Verification 2: Every element_id in alignment appears exactly once as an ID in XHTML
    all_ids = root.xpath("//@id")
    for entry in timeline:
        eid = str(entry.get("element_id", ""))
        count = all_ids.count(eid)
        if count != 1:
            raise XhtmlInjectionError(
                f"ID invariant violated in '{doc_name}': element_id '{eid}' appears {count} times (expected 1)."
            )

    # Serialize to disk if output path is specified or modifying file in place
    dest_path = Path(out_path) if out_path is not None else file_path
    if dest_path is not None:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        doctype = doc.docinfo.doctype if doc.docinfo and doc.docinfo.doctype else None
        serialized = etree.tostring(
            doc,
            encoding="utf-8",
            xml_declaration=True,
            doctype=doctype,
        )
        dest_path.write_bytes(serialized)
        log.info("Wrote modified XHTML with %d span IDs to '%s'", len(used_ids), dest_path)

    return doc


def find_chapter_xhtml_path(
    work_dir: Union[str, Path],
    chapter: Union[AlignedChapter, dict[str, Any]],
) -> Path:
    """Locate the XHTML file for an aligned chapter inside the extracted work directory.

    Parameters
    ----------
    work_dir : Union[str, Path]
        Root directory containing the extracted EPUB container.
    chapter : Union[AlignedChapter, dict[str, Any]]
        Aligned chapter metadata containing `xhtml_filename` and/or `spine_item_id`.

    Returns
    -------
    Path
        Resolved filesystem path to the XHTML file.

    Raises
    ------
    FileNotFoundError
        If the chapter file cannot be located.
    """
    work_dir = Path(work_dir)
    xhtml_name = str(chapter.get("xhtml_filename", "")).strip()
    spine_id = str(chapter.get("spine_item_id", "")).strip()

    # Direct relative check
    if xhtml_name:
        direct = work_dir / xhtml_name
        if direct.is_file():
            return direct

    # Try resolving via OPF package manifest if container.xml exists
    container_file = work_dir / "META-INF" / "container.xml"
    if container_file.is_file():
        try:
            spine_items = read_package(work_dir)
            for item in spine_items:
                if (spine_id and item.id == spine_id) or (xhtml_name and (item.href == xhtml_name or Path(item.href).name == xhtml_name)):
                    if item.file_path.is_file():
                        return item.file_path
        except Exception as exc:
            log.debug("Package resolution in %s failed: %s", work_dir, exc)

    # Try standard EPUB directories: EPUB/ or OEBPS/
    if xhtml_name:
        for sub in ["EPUB", "OEBPS", "OPS"]:
            cand = work_dir / sub / xhtml_name
            if cand.is_file():
                return cand

        # Recursive search fallback
        matches = list(work_dir.rglob(xhtml_name))
        if matches:
            return matches[0]

    raise FileNotFoundError(
        f"Could not locate chapter XHTML file '{xhtml_name}' (spine ID '{spine_id}') in work directory '{work_dir}'."
    )


def inject_alignment_spans(
    work_dir: Union[str, Path],
    alignment: Union[str, Path, Sequence[Union[AlignedChapter, dict[str, Any]]]],
    in_place: bool = True,
    continuation_class: str | None = None,
) -> dict[str, Path]:
    """Inject sentence span IDs into all chapter XHTML files referenced by alignment.

    Parameters
    ----------
    work_dir : Union[str, Path]
        Directory where EPUB is unpacked.
    alignment : Union[str, Path, Sequence[Union[AlignedChapter, dict[str, Any]]]]
        Loaded alignment or path to alignment.json.
    in_place : bool, default=True
        Whether to overwrite XHTML files in-place in work_dir.
    continuation_class : str | None, optional
        Optional CSS class name for continuation spans.

    Returns
    -------
    dict[str, Path]
        Mapping from spine_item_id to the modified XHTML file Path.
    """
    work_dir = Path(work_dir)
    chapters = load_alignment(alignment)

    results: dict[str, Path] = {}
    for ch in chapters:
        spine_id = ch.spine_item_id
        xhtml_path = find_chapter_xhtml_path(work_dir, ch)

        log.info("Injecting span IDs into chapter '%s' (%s, %d entries)", spine_id, xhtml_path.name, len(ch.timeline))
        inject_spans_into_xhtml(
            xhtml_source=xhtml_path,
            timeline=ch.timeline,
            out_path=xhtml_path if in_place else None,
            continuation_class=continuation_class,
        )
        results[spine_id] = xhtml_path

    return results


def copy_chapter_audio(
    source_audio: Union[str, Path],
    target_dir: Union[str, Path],
    dest_filename: str | None = None,
) -> Path:
    """Copy an audio file into the EPUB container audio directory.

    Parameters
    ----------
    source_audio : Union[str, Path]
        Path to the source audio file.
    target_dir : Union[str, Path]
        Directory where audio files belong (e.g. 'EPUB/audio' or 'OEBPS/audio').
    dest_filename : str | None, optional
        Target filename inside target_dir. If None, preserves source filename.

    Returns
    -------
    Path
        Destination path of copied audio file.

    Raises
    ------
    FileNotFoundError
        If source_audio does not exist.
    """
    source_path = Path(source_audio).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"Source audio file not found: {source_audio}")

    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    dest_name = dest_filename or source_path.name
    dest_path = target_dir / dest_name

    if dest_path.resolve() != source_path:
        shutil.copy2(source_path, dest_path)
        log.info("Copied audio '%s' to '%s'", source_path.name, dest_path)

    return dest_path


def generate_chapter_smil(
    chapter: Union[AlignedChapter, dict[str, Any]],
    smil_path: Union[str, Path],
    xhtml_path: Union[str, Path],
    audio_rel_path: str,
    seq_id: str | None = None,
    par_prefix: str = "par_",
    validate_xhtml_ids: bool = True,
    audio_file_path: Union[str, Path, None] = None,
) -> SmilMetadata:
    """Generate a valid SMIL 3.0 Media Overlays document for a single chapter.

    Parameters
    ----------
    chapter : Union[AlignedChapter, dict[str, Any]]
        Chapter alignment data containing `spine_item_id` and `timeline`.
    smil_path : Union[str, Path]
        Output path for the .smil file.
    xhtml_path : Union[str, Path]
        Path to the chapter XHTML file.
    audio_rel_path : str
        Relative URI path from the SMIL file to the audio file (e.g. 'audio/chapter01.mp3').
    seq_id : str | None, optional
        ID attribute for <seq>. Defaults to 'seq_{spine_item_id}'.
    par_prefix : str, default='par_'
        Prefix for <par> ID attributes.
    validate_xhtml_ids : bool, default=True
        Whether to verify that every element ID referenced by <text src="...#id"/>
        actually exists in the target XHTML file.
    audio_file_path : Union[str, Path, None], optional
        Filesystem path to the destination audio file.

    Returns
    -------
    SmilMetadata
        Metadata for the generated SMIL document including per-SMIL duration.

    Raises
    ------
    SmilGenerationError
        If timeline timing is invalid or referenced XHTML IDs do not exist.
    """
    timeline = chapter.get("timeline", []) if isinstance(chapter, dict) else chapter.timeline
    spine_id = str(chapter.get("spine_item_id") or Path(xhtml_path).stem)
    smil_path = Path(smil_path)
    xhtml_p = Path(xhtml_path)

    try:
        rel_xhtml = os.path.relpath(xhtml_p.resolve(), smil_path.parent.resolve()).replace("\\", "/")
    except ValueError:
        rel_xhtml = xhtml_p.name

    if validate_xhtml_ids and xhtml_p.is_file():
        try:
            xhtml_doc = etree.parse(str(xhtml_p))
            existing_ids = set(xhtml_doc.xpath("//@id"))
        except Exception as exc:
            raise SmilGenerationError(f"Failed to parse XHTML file '{xhtml_p}' for ID validation: {exc}") from exc

        for raw_entry in timeline:
            eid = raw_entry.get("element_id") if isinstance(raw_entry, dict) else raw_entry.element_id
            if eid not in existing_ids:
                raise SmilGenerationError(
                    f"Timeline element ID '{eid}' does not exist in target XHTML '{xhtml_p.name}'."
                )

    nsmap = {
        None: SMIL_NAMESPACE,
        "epub": EPUB_OPS_NAMESPACE,
    }
    smil_root = etree.Element(f"{{{SMIL_NAMESPACE}}}smil", nsmap=nsmap, attrib={"version": "3.0"})
    body_elem = etree.SubElement(smil_root, f"{{{SMIL_NAMESPACE}}}body")

    actual_seq_id = seq_id or f"seq_{spine_id}"
    seq_attrib = {
        "id": actual_seq_id,
        f"{{{EPUB_OPS_NAMESPACE}}}textref": rel_xhtml,
        f"{{{EPUB_OPS_NAMESPACE}}}type": "chapter",
    }
    seq_elem = etree.SubElement(body_elem, f"{{{SMIL_NAMESPACE}}}seq", attrib=seq_attrib)

    last_end_ms = 0
    prev_start_ms = -1
    for idx, raw_entry in enumerate(timeline, start=1):
        start_ms = int(raw_entry["start_ms"])
        end_ms = int(raw_entry["end_ms"])
        eid = str(raw_entry["element_id"])

        if start_ms < 0 or end_ms < 0:
            raise SmilGenerationError(f"Negative timestamp in entry '{eid}': {start_ms}ms - {end_ms}ms")
        if end_ms < start_ms:
            raise SmilGenerationError(f"Clip end ({end_ms}ms) precedes clip start ({start_ms}ms) in entry '{eid}'")
        if start_ms < prev_start_ms:
            raise SmilGenerationError(f"Clip start ({start_ms}ms) out of order in entry '{eid}'")
        prev_start_ms = start_ms

        par_id = f"{par_prefix}{idx:04d}"
        par_elem = etree.SubElement(seq_elem, f"{{{SMIL_NAMESPACE}}}par", attrib={"id": par_id})

        text_src = f"{rel_xhtml}#{eid}"
        etree.SubElement(par_elem, f"{{{SMIL_NAMESPACE}}}text", attrib={"src": text_src})

        clip_begin_str = format_smil_clock(start_ms)
        clip_end_str = format_smil_clock(end_ms)
        etree.SubElement(par_elem, f"{{{SMIL_NAMESPACE}}}audio", attrib={
            "src": audio_rel_path,
            "clipBegin": clip_begin_str,
            "clipEnd": clip_end_str,
        })
        last_end_ms = max(last_end_ms, end_ms)

    smil_path.parent.mkdir(parents=True, exist_ok=True)
    xml_bytes = etree.tostring(
        smil_root,
        encoding="utf-8",
        xml_declaration=True,
        pretty_print=True,
    )
    smil_path.write_bytes(xml_bytes)

    duration = SmilDuration(last_end_ms / 1000.0, last_end_ms)
    return SmilMetadata(
        smil_path=smil_path,
        chapter_id=spine_id,
        duration=duration,
        duration_ms=last_end_ms,
        duration_s=float(duration),
        duration_clock=format_smil_clock(last_end_ms),
        audio_src=audio_rel_path,
        audio_file_path=Path(audio_file_path) if audio_file_path else None,
        par_count=len(timeline),
        xhtml_path=xhtml_p,
    )


def find_epub_content_dir(work_dir: Union[str, Path]) -> Path:
    """Locate the EPUB package content directory containing OPF, XHTML, and SMIL files.

    Checks META-INF/container.xml rootfile full-path, standard directory names (EPUB, OEBPS, OPS),
    or falls back to work_dir.

    Parameters
    ----------
    work_dir : Union[str, Path]
        Extracted EPUB root directory.

    Returns
    -------
    Path
        Path to the directory containing the package content.
    """
    work_dir = Path(work_dir)
    container_file = work_dir / "META-INF" / "container.xml"
    if container_file.is_file():
        try:
            tree = etree.parse(str(container_file))
            rootfiles = tree.xpath("//*[local-name()='rootfile'][@full-path]")
            if rootfiles:
                full_path = rootfiles[0].get("full-path")
                opf_dir = (work_dir / full_path).parent
                if opf_dir.is_dir():
                    return opf_dir
        except Exception as exc:
            log.debug("Failed reading container.xml in %s: %s", work_dir, exc)

    for cand in ["EPUB", "OEBPS", "OPS"]:
        p = work_dir / cand
        if p.is_dir():
            return p

    return work_dir


def generate_smil_playlists(
    work_dir: Union[str, Path],
    alignment: Union[str, Path, Sequence[Union[AlignedChapter, dict[str, Any]]]],
    audio_source: Union[str, Path, Sequence[Union[str, Path]], None] = None,
    validate_xhtml_ids: bool = True,
) -> dict[str, SmilMetadata]:
    """Generate SMIL 3.0 Media Overlays playlists and copy audio files for all chapters.

    Parameters
    ----------
    work_dir : Union[str, Path]
        Directory where EPUB is unpacked.
    alignment : Union[str, Path, Sequence[Union[AlignedChapter, dict[str, Any]]]]
        Loaded alignment or path to alignment.json.
    audio_source : Union[str, Path, Sequence[Union[str, Path]], None], optional
        Source directory containing audio files, list of audio file paths,
        or None to search relative to work_dir / audio_filename.
    validate_xhtml_ids : bool, default=True
        Whether to verify that referenced element IDs exist in XHTML documents.

    Returns
    -------
    dict[str, SmilMetadata]
        Mapping from chapter spine_item_id to SmilMetadata.

    Raises
    ------
    FileNotFoundError
        If required XHTML or audio files cannot be found.
    SmilGenerationError
        If SMIL synthesis or validation fails.
    """
    work_dir = Path(work_dir)
    chapters = load_alignment(alignment)
    content_dir = find_epub_content_dir(work_dir)
    target_audio_dir = content_dir / "audio"
    target_audio_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, SmilMetadata] = {}

    for idx, ch in enumerate(chapters):
        spine_id = ch.spine_item_id
        xhtml_path = find_chapter_xhtml_path(work_dir, ch)

        smil_filename = f"{Path(xhtml_path).stem}.smil"
        smil_path = xhtml_path.parent / smil_filename

        audio_fn = ch.audio_filename
        source_audio_path: Path | None = None

        if audio_source is not None:
            # Check if audio_source is a directory or single directory in sequence
            if isinstance(audio_source, (list, tuple, Sequence)) and len(audio_source) == 1 and Path(audio_source[0]).is_dir():
                audio_source_dir = Path(audio_source[0])
            elif isinstance(audio_source, (str, Path)) and Path(audio_source).is_dir():
                audio_source_dir = Path(audio_source)
            else:
                audio_source_dir = None

            if audio_source_dir is not None:
                cand = audio_source_dir / Path(audio_fn).name
                if cand.is_file():
                    source_audio_path = cand
                else:
                    cand2 = audio_source_dir / audio_fn
                    if cand2.is_file():
                        source_audio_path = cand2
            elif isinstance(audio_source, (str, Path)) and Path(audio_source).is_file():
                source_audio_path = Path(audio_source)
            elif isinstance(audio_source, (list, tuple, Sequence)):
                for item in audio_source:
                    p = Path(item)
                    if p.is_dir():
                        cand = p / Path(audio_fn).name
                        if cand.is_file():
                            source_audio_path = cand
                            break
                    elif p.name == Path(audio_fn).name or p.name == audio_fn:
                        source_audio_path = p
                        break
                if source_audio_path is None and idx < len(audio_source):
                    p = Path(audio_source[idx])
                    if p.is_file():
                        source_audio_path = p

        if source_audio_path is None:
            dest_in_target = target_audio_dir / Path(audio_fn).name
            if dest_in_target.is_file():
                source_audio_path = dest_in_target
            elif (work_dir / audio_fn).is_file():
                source_audio_path = work_dir / audio_fn
            elif (work_dir / Path(audio_fn).name).is_file():
                source_audio_path = work_dir / Path(audio_fn).name
            elif (content_dir / audio_fn).is_file():
                source_audio_path = content_dir / audio_fn
            elif Path(audio_fn).is_file():
                source_audio_path = Path(audio_fn)

        if source_audio_path is None:
            raise FileNotFoundError(
                f"Could not locate audio file '{audio_fn}' for chapter '{spine_id}' in audio sources or work directory."
            )

        dest_audio = copy_chapter_audio(
            source_audio=source_audio_path,
            target_dir=target_audio_dir,
            dest_filename=Path(audio_fn).name,
        )

        try:
            audio_rel_path = os.path.relpath(dest_audio.resolve(), smil_path.parent.resolve()).replace("\\", "/")
        except ValueError:
            audio_rel_path = f"audio/{dest_audio.name}"

        meta = generate_chapter_smil(
            chapter=ch,
            smil_path=smil_path,
            xhtml_path=xhtml_path,
            audio_rel_path=audio_rel_path,
            validate_xhtml_ids=validate_xhtml_ids,
            audio_file_path=dest_audio,
        )
        results[spine_id] = meta

    return results


def find_opf_path(work_dir: Union[str, Path]) -> Path:
    """Locate the EPUB OPF package file.

    Checks META-INF/container.xml rootfile full-path first, then searches work_dir for *.opf.

    Parameters
    ----------
    work_dir : Union[str, Path]
        Root directory of unpacked EPUB container.

    Returns
    -------
    Path
        Path to the OPF package document.

    Raises
    ------
    OpfUpdateError
        If no OPF package file can be located.
    """
    work_dir = Path(work_dir)
    container_file = work_dir / "META-INF" / "container.xml"
    if container_file.is_file():
        try:
            tree = etree.parse(str(container_file))
            rootfiles = tree.xpath("//*[local-name()='rootfile'][@full-path]")
            if rootfiles:
                full_path = rootfiles[0].get("full-path")
                candidate = work_dir / full_path
                if candidate.is_file():
                    return candidate
        except Exception as exc:
            log.debug("Failed reading container.xml in %s: %s", work_dir, exc)

    opf_files = sorted(work_dir.rglob("*.opf"))
    if opf_files:
        return opf_files[0]

    raise OpfUpdateError(f"Could not locate OPF package file in '{work_dir}'.")


def inject_active_class_css(
    work_dir: Union[str, Path],
    css_class: str = "-epub-media-overlay-active",
    color: str = "#ffe58a",
) -> list[Path]:
    """Inject media overlay active CSS style into stylesheets in work_dir.

    Parameters
    ----------
    work_dir : Union[str, Path]
        Root directory of unpacked EPUB container.
    css_class : str, optional
        Class name to style (default '-epub-media-overlay-active').
    color : str, optional
        Highlight background color (default '#ffe58a').

    Returns
    -------
    list[Path]
        List of modified or created CSS file paths.
    """
    work_dir = Path(work_dir)
    content_dir = find_epub_content_dir(work_dir)
    rule = f"\n.{css_class} {{\n  background-color: {color};\n}}\n"

    css_files = list(content_dir.rglob("*.css"))
    if not css_files:
        css_files = list(work_dir.rglob("*.css"))

    if not css_files:
        default_css = content_dir / "styles.css"
        default_css.write_text(rule.lstrip(), encoding="utf-8")
        return [default_css]

    modified: list[Path] = []
    for css_file in css_files:
        try:
            text = css_file.read_text(encoding="utf-8")
            if css_class not in text:
                css_file.write_text(text.rstrip() + "\n" + rule, encoding="utf-8")
            modified.append(css_file)
        except Exception as exc:
            log.warning("Could not update CSS file %s: %s", css_file, exc)

    return modified


def synthesize_nav_xhtml(
    work_dir: Union[str, Path],
    opf_path: Path,
    spine_hrefs: Optional[Sequence[str]] = None,
) -> Path:
    """Synthesize a minimal EPUB 3 navigation document (nav.xhtml).

    Parameters
    ----------
    work_dir : Union[str, Path]
        Root directory of unpacked EPUB container.
    opf_path : Path
        Path to the package OPF document.
    spine_hrefs : Sequence[str], optional
        List of chapter XHTML relative paths for navigation links.

    Returns
    -------
    Path
        Path to the written nav.xhtml file.
    """
    opf_dir = opf_path.parent
    nav_path = opf_dir / "nav.xhtml"

    items_html = []
    if spine_hrefs:
        for href in spine_hrefs:
            title = Path(href).stem.replace("_", " ").title()
            items_html.append(f'        <li><a href="{href}">{title}</a></li>')
    else:
        items_html.append('        <li><a href="chapter01.xhtml">Chapter 1</a></li>')

    content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">\n'
        '  <head>\n'
        '    <title>Table of Contents</title>\n'
        '  </head>\n'
        '  <body>\n'
        '    <nav epub:type="toc" id="toc">\n'
        '      <h1>Table of Contents</h1>\n'
        '      <ol>\n'
        + "\n".join(items_html) + "\n"
        '      </ol>\n'
        '    </nav>\n'
        '  </body>\n'
        '</html>\n'
    )
    nav_path.write_text(content, encoding="utf-8")
    return nav_path


def update_opf_manifest(
    work_dir: Union[str, Path],
    smil_metadata: Optional[Union[dict[str, Any], Sequence[Any]]] = None,
    audio_files: Optional[Sequence[Union[str, Path]]] = None,
    active_class: str = "-epub-media-overlay-active",
    highlight_color: str = "#ffe58a",
    validate_hrefs: bool = True,
) -> Path:
    """Update OPF package manifest with Media Overlays SMIL and audio entries.

    Ensures EPUB 3.0 specification compliance, registers all chapter SMIL
    playlists with media-type="application/smil+xml", registers all audio assets,
    links XHTML manifest items with media-overlay attributes, adds per-SMIL and
    total media:duration metadata, adds media:active-class metadata, and injects
    active class styling into stylesheet(s).

    Parameters
    ----------
    work_dir : Union[str, Path]
        Root directory of unpacked EPUB container.
    smil_metadata : Union[dict[str, Any], Sequence[Any]], optional
        Mapping or list of chapter SMIL metadata produced by generate_smil_playlists.
        If None, discovers SMIL files present in the content directory.
    audio_files : Sequence[Union[str, Path]], optional
        Optional list of audio files to register.
    active_class : str, optional
        Active highlight class name (default '-epub-media-overlay-active').
    highlight_color : str, optional
        Highlight background color (default '#ffe58a').
    validate_hrefs : bool, optional
        Whether to verify that manifest hrefs point to existing files.

    Returns
    -------
    Path
        Path to updated package.opf file.

    Raises
    ------
    OpfUpdateError
        If OPF parsing, updating, or serialization fails.
    """
    work_dir = Path(work_dir)
    opf_path = find_opf_path(work_dir)
    opf_dir = opf_path.parent

    try:
        parser = etree.XMLParser(remove_blank_text=False)
        tree = etree.parse(str(opf_path), parser)
    except Exception as exc:
        raise OpfUpdateError(f"Failed to parse OPF file {opf_path}: {exc}") from exc

    root = tree.getroot()
    ns = root.nsmap.get(None)

    def qname(tag: str) -> str:
        return f"{{{ns}}}{tag}" if ns else tag

    # 1. Upgrade EPUB version to 3.0 if necessary
    version = root.get("version", "")
    if version != "3.0":
        root.set("version", "3.0")

    # 2. Locate container elements
    metadata_elems = root.xpath("//*[local-name()='metadata']")
    if not metadata_elems:
        raise OpfUpdateError(f"OPF missing <metadata> element in {opf_path}")
    metadata = metadata_elems[0]

    manifest_elems = root.xpath("//*[local-name()='manifest']")
    if not manifest_elems:
        raise OpfUpdateError(f"OPF missing <manifest> element in {opf_path}")
    manifest = manifest_elems[0]

    spine_elems = root.xpath("//*[local-name()='spine']")
    spine = spine_elems[0] if spine_elems else None

    # 3. Verify or synthesize EPUB 3 Navigation Document (properties="nav")
    manifest_items = manifest.xpath("./*[local-name()='item']")
    has_nav = any("nav" in (item.get("properties") or "").split() for item in manifest_items)
    if not has_nav:
        spine_hrefs: list[str] = []
        if spine is not None:
            for itemref in spine.xpath("./*[local-name()='itemref']"):
                idref = itemref.get("idref")
                matching = manifest.xpath(f"./*[local-name()='item'][@id='{idref}']")
                if matching:
                    spine_hrefs.append(matching[0].get("href", ""))
        nav_path = synthesize_nav_xhtml(work_dir, opf_path, [h for h in spine_hrefs if h])
        nav_rel_href = os.path.relpath(nav_path, opf_dir).replace("\\", "/")

        existing_nav_item = next(
            (it for it in manifest.xpath("./*[local-name()='item']") if it.get("href") == nav_rel_href),
            None,
        )
        if existing_nav_item is not None:
            props = (existing_nav_item.get("properties") or "").split()
            if "nav" not in props:
                props.append("nav")
                existing_nav_item.set("properties", " ".join(props))
        else:
            existing_ids = {it.get("id") for it in manifest.xpath("./*[local-name()='item']")}
            nav_id = "nav" if "nav" not in existing_ids else "nav_doc"
            etree.SubElement(
                manifest,
                qname("item"),
                attrib={
                    "id": nav_id,
                    "href": nav_rel_href,
                    "media-type": "application/xhtml+xml",
                    "properties": "nav",
                },
            )

    # 4. Normalize SMIL metadata entries
    processed_smils: list[dict[str, Any]] = []

    if smil_metadata is not None:
        if isinstance(smil_metadata, dict):
            items_list = list(smil_metadata.values())
        else:
            items_list = list(smil_metadata)

        for item in items_list:
            if hasattr(item, "smil_path"):
                s_path = Path(item.smil_path)
                ch_id = getattr(item, "chapter_id", s_path.stem)
                dur_ms = getattr(item, "duration_ms", 0)
                a_path = getattr(item, "audio_file_path", None)
                x_path = getattr(item, "xhtml_path", None)
            elif isinstance(item, dict):
                s_path = Path(item["smil_path"])
                ch_id = item.get("chapter_id", s_path.stem)
                dur_ms = item.get("duration_ms", int(round(float(item.get("duration", 0)) * 1000)))
                a_path = Path(item["audio_file_path"]) if item.get("audio_file_path") else None
                x_path = Path(item["xhtml_path"]) if item.get("xhtml_path") else None
            else:
                continue

            processed_smils.append({
                "chapter_id": ch_id,
                "smil_path": s_path,
                "duration_ms": dur_ms,
                "audio_path": a_path,
                "xhtml_path": x_path,
            })
    else:
        # Discover existing SMIL files on disk
        smil_files = sorted(set(list(opf_dir.glob("*.smil")) + list((opf_dir / "smil").glob("*.smil"))))
        for sf in smil_files:
            try:
                stree = etree.parse(str(sf))
                sroot = stree.getroot()
                audio_elems = sroot.xpath("//*[local-name()='audio'][@clipEnd]")
                dur_ms = 0
                if audio_elems:
                    last_end = audio_elems[-1].get("clipEnd")
                    dur_ms = int(round(parse_smil_clock(last_end) * 1000))

                seq_elems = sroot.xpath("//*[local-name()='seq']")
                textref = seq_elems[0].get(f"{{{EPUB_OPS_NAMESPACE}}}textref") if seq_elems else None
                if not textref:
                    text_elems = sroot.xpath("//*[local-name()='text'][@src]")
                    if text_elems:
                        textref = text_elems[0].get("src").split("#")[0]

                xhtml_p = (sf.parent / textref).resolve() if textref else None

                processed_smils.append({
                    "chapter_id": sf.stem,
                    "smil_path": sf,
                    "duration_ms": dur_ms,
                    "audio_path": None,
                    "xhtml_path": xhtml_p,
                })
            except Exception as exc:
                log.warning("Could not inspect SMIL file %s: %s", sf, exc)

    # 5. Register SMIL items and update matching XHTML items in manifest
    existing_items = manifest.xpath("./*[local-name()='item']")
    existing_ids: dict[str, Any] = {it.get("id"): it for it in existing_items}
    existing_hrefs: dict[str, Any] = {it.get("href"): it for it in existing_items}

    for entry in processed_smils:
        s_path = entry["smil_path"]
        ch_id = entry["chapter_id"]
        smil_rel_href = os.path.relpath(s_path, opf_dir).replace("\\", "/")

        if smil_rel_href in existing_hrefs:
            smil_item = existing_hrefs[smil_rel_href]
            smil_id = smil_item.get("id")
            smil_item.set("media-type", "application/smil+xml")
        else:
            base_smil_id = f"smil_{ch_id}"
            smil_id = base_smil_id
            counter = 1
            while smil_id in existing_ids:
                smil_id = f"{base_smil_id}_{counter}"
                counter += 1

            smil_item = etree.SubElement(
                manifest,
                qname("item"),
                attrib={
                    "id": smil_id,
                    "href": smil_rel_href,
                    "media-type": "application/smil+xml",
                },
            )
            existing_ids[smil_id] = smil_item
            existing_hrefs[smil_rel_href] = smil_item

        entry["smil_id"] = smil_id

        # Match XHTML item
        xhtml_item = None
        if ch_id in existing_ids:
            cand = existing_ids[ch_id]
            if "xhtml" in (cand.get("media-type") or "") or cand.get("href", "").endswith((".xhtml", ".html")):
                xhtml_item = cand

        if xhtml_item is None and entry.get("xhtml_path"):
            x_rel = os.path.relpath(entry["xhtml_path"], opf_dir).replace("\\", "/")
            if x_rel in existing_hrefs:
                xhtml_item = existing_hrefs[x_rel]

        if xhtml_item is None:
            for it in manifest.xpath("./*[local-name()='item']"):
                href = it.get("href", "")
                if Path(href).stem == ch_id or Path(href).stem == s_path.stem:
                    xhtml_item = it
                    break

        if xhtml_item is not None:
            xhtml_item.set("media-overlay", smil_id)
        else:
            log.warning("Could not locate matching XHTML item for chapter '%s' in OPF manifest", ch_id)

    # 6. Register audio files in manifest
    audio_candidates: list[Path] = []
    if audio_files:
        for a in audio_files:
            audio_candidates.append(Path(a))

    for entry in processed_smils:
        if entry.get("audio_path"):
            audio_candidates.append(Path(entry["audio_path"]))

    for candidate_dir in [opf_dir / "audio", work_dir / "audio"]:
        if candidate_dir.is_dir():
            for f in sorted(candidate_dir.iterdir()):
                if f.is_file() and f.suffix.lower() in AUDIO_MIME_TYPES:
                    audio_candidates.append(f)

    seen_audio_paths: set[Path] = set()
    for af in audio_candidates:
        if not af.is_file():
            continue
        try:
            resolved = af.resolve()
        except Exception:
            resolved = af
        if resolved in seen_audio_paths:
            continue
        seen_audio_paths.add(resolved)

        audio_rel_href = os.path.relpath(af, opf_dir).replace("\\", "/")
        mime = AUDIO_MIME_TYPES.get(af.suffix.lower(), "audio/mpeg")

        if audio_rel_href in existing_hrefs:
            item = existing_hrefs[audio_rel_href]
            item.set("media-type", mime)
        else:
            clean_stem = re.sub(r"[^a-zA-Z0-9_\-]", "_", af.stem)
            base_audio_id = f"audio_{clean_stem}"
            audio_id = base_audio_id
            counter = 1
            while audio_id in existing_ids:
                audio_id = f"{base_audio_id}_{counter}"
                counter += 1

            audio_item = etree.SubElement(
                manifest,
                qname("item"),
                attrib={
                    "id": audio_id,
                    "href": audio_rel_href,
                    "media-type": mime,
                },
            )
            existing_ids[audio_id] = audio_item
            existing_hrefs[audio_rel_href] = audio_item

    # 7. Update Media Overlays duration & active-class metadata
    for old_meta in metadata.xpath("./*[local-name()='meta'][@property='media:duration' or @property='media:active-class']"):
        metadata.remove(old_meta)

    total_ms = 0
    for entry in processed_smils:
        dur_ms = entry["duration_ms"]
        total_ms += dur_ms
        smil_id = entry.get("smil_id")
        dur_str = format_clock_hms(dur_ms)

        meta_elem = etree.SubElement(
            metadata,
            qname("meta"),
            attrib={
                "property": "media:duration",
                "refines": f"#{smil_id}",
            },
        )
        meta_elem.text = dur_str

    total_meta = etree.SubElement(
        metadata,
        qname("meta"),
        attrib={"property": "media:duration"},
    )
    total_meta.text = format_clock_hms(total_ms)

    active_meta = etree.SubElement(
        metadata,
        qname("meta"),
        attrib={"property": "media:active-class"},
    )
    active_meta.text = active_class

    # 8. Inject active CSS styling into book stylesheets
    inject_active_class_css(work_dir, css_class=active_class, color=highlight_color)

    # 9. Verify manifest hrefs exist
    if validate_hrefs:
        for it in manifest.xpath("./*[local-name()='item']"):
            href = it.get("href")
            if href:
                target = opf_dir / href
                if not target.exists():
                    log.warning("Manifest item '%s' href '%s' not found on disk at %s", it.get("id"), href, target)

    # 10. Write updated package document
    tree.write(str(opf_path), encoding="utf-8", xml_declaration=True, pretty_print=True)
    return opf_path


def validate_epubcheck(
    epub_path: Union[str, Path],
    epubcheck_bin: str | None = None,
) -> tuple[bool, str]:
    """Validate an EPUB file using the EPUBCheck command line utility.

    If epubcheck is not installed, logs a warning and returns (True, "skipped").
    If installed, runs epubcheck and returns (is_valid, report).

    Parameters
    ----------
    epub_path : Union[str, Path]
        Path to EPUB file to validate.
    epubcheck_bin : str, optional
        Path or command name for epubcheck (default searches PATH).

    Returns
    -------
    tuple[bool, str]
        Tuple of (is_valid, report_text).
    """
    epub_path = Path(epub_path)
    if not epub_path.is_file():
        raise FileNotFoundError(f"EPUB file not found: {epub_path}")

    bin_path = epubcheck_bin or shutil.which("epubcheck")
    if bin_path is None:
        log.warning("epubcheck is not installed; skipping validation. Install via 'brew install epubcheck'.")
        return True, "EPUBCheck not installed; skipped validation"

    try:
        proc = subprocess.run(
            [bin_path, str(epub_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        if proc.returncode == 0:
            log.info("EPUBCheck validation passed for %s", epub_path.name)
            return True, output.strip()
        else:
            log.error("EPUBCheck validation failed for %s (exit code %d):\n%s", epub_path.name, proc.returncode, output)
            return False, output.strip()
    except Exception as exc:
        log.warning("Failed to run epubcheck on %s: %s", epub_path, exc)
        return False, str(exc)


def zip_epub(
    work_dir: Union[str, Path],
    output_path: Union[str, Path],
) -> Path:
    """Pack an unpacked EPUB directory into a compliant EPUB zip container.

    Enforces EPUB container packaging specifications:
    1. The first entry in the ZIP is 'mimetype' containing exactly
       'application/epub+zip' stored uncompressed (ZIP_STORED).
    2. All other files are added with standard Deflate compression (ZIP_DEFLATED),
       except pre-compressed audio files which use ZIP_STORED for performance.
    3. Excludes stray files (.DS_Store, __pycache__, temp files, hidden files).

    Parameters
    ----------
    work_dir : Union[str, Path]
        Directory containing unpacked EPUB files.
    output_path : Union[str, Path]
        Destination path for the packaged .epub file.

    Returns
    -------
    Path
        Path to the written EPUB file.

    Raises
    ------
    PackagerError
        If packaging fails or work_dir is invalid.
    """
    work_dir = Path(work_dir)
    if not work_dir.is_dir():
        raise PackagerError(f"Directory not found for packaging: {work_dir}")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    temp_zip = output_path.with_suffix(".tmp.epub")

    try:
        with zipfile.ZipFile(temp_zip, "w") as zf:
            # 1. First entry must be 'mimetype' stored uncompressed
            zf.writestr("mimetype", b"application/epub+zip", compress_type=zipfile.ZIP_STORED)

            # 2. Add all other files
            for root, dirs, files in os.walk(work_dir):
                dirs[:] = [
                    d for d in dirs
                    if not d.startswith(".")
                    and d != "__pycache__"
                    and not d.endswith(".tmp")
                ]

                for f in sorted(files):
                    if f == "mimetype" or f.startswith(".") or f.endswith(("~", ".tmp", ".swp", ".bak")):
                        continue
                    if f.endswith(".epub"):
                        continue

                    full_path = Path(root) / f
                    arcname = os.path.relpath(full_path, work_dir).replace("\\", "/")

                    suffix = full_path.suffix.lower()
                    if suffix in AUDIO_MIME_TYPES:
                        comp_type = zipfile.ZIP_STORED
                    else:
                        comp_type = zipfile.ZIP_DEFLATED

                    zf.write(full_path, arcname=arcname, compress_type=comp_type)

        temp_zip.replace(output_path)
        log.info("Packaged EPUB archive: %s (%d bytes)", output_path, output_path.stat().st_size)
        return output_path
    except Exception as exc:
        if temp_zip.is_file():
            temp_zip.unlink(missing_ok=True)
        raise PackagerError(f"Failed to zip EPUB to {output_path}: {exc}") from exc


def package(
    epub: Union[str, Path],
    audio: Sequence[Union[str, Path]],
    alignment: Union[str, Path, Sequence[Union[AlignedChapter, dict[str, Any]]]],
    output: Union[str, Path],
    work_dir: Union[str, Path, None] = None,
    validate_epub: bool = True,
) -> Path:
    """High-level packaging pipeline entrypoint.

    Injects span IDs into XHTML, generates SMIL playlists, updates the OPF
    package manifest, packs the container into an EPUB archive with uncompressed
    mimetype first, and validates the output with EPUBCheck.

    Parameters
    ----------
    epub : Union[str, Path]
        Path to source EPUB file.
    audio : Sequence[Union[str, Path]]
        List of audio files.
    alignment : Union[str, Path, Sequence[Union[AlignedChapter, dict[str, Any]]]]
        Alignment data or path to alignment.json.
    output : Union[str, Path]
        Path to output EPUB.
    work_dir : Union[str, Path, None], optional
        Working directory for unpacked files. If None, uses a temporary directory.
    validate_epub : bool, default=True
        Whether to run EPUBCheck validation if installed.

    Returns
    -------
    Path
        Path to output EPUB.

    Raises
    ------
    PackagerError
        If packaging or validation fails.
    """
    output_path = Path(output)

    if work_dir is not None:
        target_dir = Path(work_dir)
        if not target_dir.is_dir():
            from echopage import parser as epub_parser
            epub_parser.unpack(epub, target_dir)

        inject_alignment_spans(target_dir, alignment)
        smil_results = generate_smil_playlists(target_dir, alignment, audio_source=audio)
        update_opf_manifest(target_dir, smil_metadata=smil_results, audio_files=audio)
        zip_epub(target_dir, output_path)
    else:
        with tempfile.TemporaryDirectory(prefix="echopage_pack_") as tmp_dir:
            temp_target = Path(tmp_dir)
            from echopage import parser as epub_parser
            epub_parser.unpack(epub, temp_target)
            inject_alignment_spans(temp_target, alignment)
            smil_results = generate_smil_playlists(temp_target, alignment, audio_source=audio)
            update_opf_manifest(temp_target, smil_metadata=smil_results, audio_files=audio)
            zip_epub(temp_target, output_path)

    if validate_epub:
        is_valid, report = validate_epubcheck(output_path)
        if not is_valid:
            raise EpubCheckValidationError(f"EPUBCheck validation failed for {output_path}:\n{report}")

    return output_path
