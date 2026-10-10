"""EPUB archive parsing, OPF package resolution, and XHTML sentence tokenization."""

from __future__ import annotations

import logging
import os
import re
import zipfile
from pathlib import Path
from typing import Any, Sequence, Union

from lxml import etree
import nltk

log = logging.getLogger("echopage.parser")


class EpubError(RuntimeError):
    """Base exception for EPUB parsing errors."""


class EpubSecurityError(ValueError, EpubError):
    """Raised when an EPUB archive contains unsafe entries such as path traversal."""


class PackageItem(dict):
    """Represents a manifest item referenced in the EPUB spine."""

    @property
    def id(self) -> str:
        return str(self.get("id", ""))

    @property
    def href(self) -> str:
        return str(self.get("href", ""))

    @property
    def media_type(self) -> str:
        return str(self.get("media_type", ""))

    @property
    def path(self) -> Path:
        """Relative path from work directory to the document file."""
        return Path(self.get("path", self.href))

    @property
    def file_path(self) -> Path:
        """Absolute or relative Path on the filesystem."""
        val = self.get("file_path")
        return Path(val) if val is not None else Path(self.href)


class Sentence(dict):
    """Represents an extracted sentence mapped to a DOM block element."""

    @property
    def element_id_placeholder(self) -> str:
        return str(self.get("element_id_placeholder", ""))

    @property
    def element_id(self) -> str:
        return str(self.get("element_id", self.element_id_placeholder))

    @property
    def text(self) -> str:
        return str(self.get("text", ""))

    @property
    def block_xpath(self) -> str:
        return str(self.get("block_xpath", ""))

    @property
    def char_start(self) -> int:
        return int(self.get("char_start", 0))

    @property
    def char_end(self) -> int:
        return int(self.get("char_end", 0))

    @property
    def block_text(self) -> str:
        return str(self.get("block_text", ""))

    def __iter__(self):
        """Allow tuple unpacking: id, text, xpath, start, end = sentence."""
        yield self.element_id_placeholder
        yield self.text
        yield self.block_xpath
        yield self.char_start
        yield self.char_end


BLOCK_TAGS = {
    "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "li", "blockquote", "pre", "dt", "dd",
    "figcaption", "caption", "div", "address",
    "section", "article", "aside",
}

SKIP_TAGS = {"script", "style", "nav", "head"}

XHTML_MEDIA_TYPES = {
    "application/xhtml+xml",
    "text/html",
    "application/html+xml",
}


def unpack(epub_path: Union[str, Path], work_dir: Union[str, Path]) -> Path:
    """Extract an EPUB zip archive into work_dir, rejecting path traversal attempts.

    Parameters
    ----------
    epub_path : Union[str, Path]
        Path to the source .epub archive.
    work_dir : Union[str, Path]
        Directory where archive contents should be extracted.

    Returns
    -------
    Path
        Resolved Path to work_dir.

    Raises
    ------
    EpubSecurityError (ValueError)
        If any archive entry contains path traversal patterns (e.g. '../', absolute paths).
    FileNotFoundError
        If epub_path does not exist.
    """
    epub_path = Path(epub_path)
    if not epub_path.is_file():
        raise FileNotFoundError(f"Source EPUB not found: {epub_path}")

    target_dir = Path(work_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    try:
        zf = zipfile.ZipFile(epub_path, "r")
    except zipfile.BadZipFile as exc:
        raise EpubError(f"Invalid or corrupted EPUB archive: {exc}") from exc

    with zf:
        infolist = zf.infolist()

        # Validate all entry filenames before extraction
        for member in infolist:
            name = member.filename
            # Reject absolute paths (POSIX or Windows)
            if name.startswith("/") or name.startswith("\\"):
                raise EpubSecurityError(f"Absolute path traversal detected in zip: {name}")
            if os.path.isabs(name) or (len(name) > 1 and name[1] == ":"):
                raise EpubSecurityError(f"Absolute path traversal detected in zip: {name}")

            # Reject relative directory traversal components
            member_parts = Path(name).parts
            if ".." in member_parts:
                raise EpubSecurityError(f"Path traversal ('..') detected in zip: {name}")

            dest = (target_dir / name).resolve()
            if not dest.is_relative_to(target_dir):
                raise EpubSecurityError(f"Path escapes extraction directory: {name}")

        # Safe to extract all
        zf.extractall(target_dir)

    return target_dir


def read_package(work_dir: Union[str, Path]) -> list[PackageItem]:
    """Read container.xml, locate the OPF package, and parse spine items.

    Returns an ordered list of PackageItem objects (dicts with id, href, media_type)
    for XHTML spine items matching the reading order.

    Parameters
    ----------
    work_dir : Union[str, Path]
        Root directory containing the extracted EPUB container.

    Returns
    -------
    list[PackageItem]
        Ordered list of XHTML spine items.
    """
    work_dir = Path(work_dir)
    container_path = work_dir / "META-INF" / "container.xml"
    if not container_path.is_file():
        raise FileNotFoundError(f"Missing container descriptor: {container_path}")

    try:
        container_tree = etree.parse(str(container_path))
    except Exception as exc:
        raise EpubError(f"Failed to parse META-INF/container.xml: {exc}") from exc

    # Locate rootfile with full-path
    rootfile_nodes = container_tree.xpath("//*[local-name()='rootfile'][@full-path]")
    if not rootfile_nodes:
        raise EpubError("No rootfile element with 'full-path' found in container.xml")

    opf_rel_path = rootfile_nodes[0].get("full-path")
    opf_path = work_dir / opf_rel_path
    if not opf_path.is_file():
        raise FileNotFoundError(f"OPF package file not found: {opf_path}")

    try:
        opf_tree = etree.parse(str(opf_path))
    except Exception as exc:
        raise EpubError(f"Failed to parse OPF package file {opf_path}: {exc}") from exc

    opf_dir = Path(opf_rel_path).parent

    # Build manifest map: id -> {id, href, media_type, path, file_path}
    manifest: dict[str, PackageItem] = {}
    for item in opf_tree.xpath("//*[local-name()='manifest']/*[local-name()='item']"):
        item_id = item.get("id")
        item_href = item.get("href")
        item_media_type = item.get("media-type", "")
        if not item_id or not item_href:
            continue

        item_path = (opf_dir / item_href) if str(opf_dir) != "." else Path(item_href)
        file_path = work_dir / item_path

        manifest[item_id] = PackageItem({
            "id": item_id,
            "href": item_href,
            "media_type": item_media_type,
            "path": item_path,
            "file_path": file_path,
        })

    # Read spine itemrefs in order
    spine_items: list[PackageItem] = []
    for itemref in opf_tree.xpath("//*[local-name()='spine']/*[local-name()='itemref']"):
        idref = itemref.get("idref")
        if not idref or idref not in manifest:
            continue

        pkg_item = manifest[idref]
        mtype = pkg_item.media_type.lower()
        href_lower = pkg_item.href.lower()

        # Filter strictly for XHTML/HTML items
        if mtype in XHTML_MEDIA_TYPES or href_lower.endswith((".xhtml", ".html")):
            spine_items.append(pkg_item)

    return spine_items


def _is_ancestor_skipped(elem: etree._Element) -> bool:
    """Return True if element or any of its ancestors should be skipped."""
    curr = elem
    while curr is not None:
        tag = etree.QName(curr).localname.lower()
        if tag in SKIP_TAGS:
            return True
        curr = curr.getparent()
    return False


def _collect_direct_block_text(elem: etree._Element) -> str:
    """Collect text from elem and its inline children, stopping at any child block elements."""
    parts = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        if not isinstance(child.tag, str):
            if child.tail:
                parts.append(child.tail)
            continue
        child_tag = etree.QName(child).localname.lower()
        if child_tag in BLOCK_TAGS:
            # Child is a block element: do not recurse into it, only include its tail text
            if child.tail:
                parts.append(child.tail)
        else:
            # Inline element (<em>, <a>, <span>, etc.): recursively collect its text and tail
            parts.append(_collect_direct_block_text(child))
            if child.tail:
                parts.append(child.tail)
    return "".join(parts)


def _get_tokenizer():
    """Obtain NLTK Punkt tokenizer with public resource loader without runtime downloads."""
    try:
        return nltk.data.load("tokenizers/punkt/english.pickle")
    except (LookupError, OSError):
        try:
            return nltk.tokenize.PunktSentenceTokenizer()
        except Exception as exc:
            log.warning("Could not load Punkt tokenizer (%s); using fallback tokenizer", exc)
            return None


def _fallback_sentence_spans(text: str) -> list[tuple[int, int]]:
    """Simple regex-based sentence boundary fallback if NLTK data is unavailable."""
    spans = []
    # Match sentence endings: . ! ? followed by whitespace or end of string, accounting for abbreviations
    pattern = re.compile(r'(?:[A-Z][a-z]{1,3}\.\s*)+|[^.!?\s][^.!?]*(?:[.!?]+["\']?|$)', re.MULTILINE)
    for match in pattern.finditer(text):
        s = match.start()
        e = match.end()
        if text[s:e].strip():
            spans.append((s, e))
    return spans


def extract_sentences(
    xhtml_source: Union[str, Path],
    start_id: int = 1,
) -> list[Sentence]:
    """Parse an XHTML document and extract sentences from content block elements.

    Parameters
    ----------
    xhtml_source : Union[str, Path]
        Path to an XHTML file, or raw XHTML string/bytes.
    start_id : int, default=1
        Starting index for element_id_placeholder numbering ('mo_s_{index:04d}').

    Returns
    -------
    list[Sentence]
        List of Sentence objects conforming to:
        [{element_id_placeholder, text, block_xpath, char_start, char_end}]
    """
    # Load XHTML tree
    if isinstance(xhtml_source, Path) or (isinstance(xhtml_source, str) and not xhtml_source.strip().startswith("<")):
        source_path = Path(xhtml_source)
        if not source_path.is_file():
            raise FileNotFoundError(f"XHTML source file not found: {source_path}")
        raw_bytes = source_path.read_bytes()
    else:
        raw_bytes = xhtml_source.encode("utf-8") if isinstance(xhtml_source, str) else xhtml_source

    parser = etree.XMLParser(remove_blank_text=False)
    try:
        doc = etree.fromstring(raw_bytes, parser=parser)
    except etree.XMLSyntaxError:
        # Fallback to recovery mode for documents with undeclared HTML entities or mild syntax quirks
        recover_parser = etree.XMLParser(recover=True, remove_blank_text=False)
        doc = etree.fromstring(raw_bytes, parser=recover_parser)

    tree = etree.ElementTree(doc)
    tokenizer = _get_tokenizer()

    results: list[Sentence] = []
    curr_id = start_id

    # Walk all elements in document order
    for elem in doc.iter():
        if not isinstance(elem.tag, str):
            continue

        tag = etree.QName(elem).localname.lower()

        # Skip head, script, style, nav, and any elements nested inside them
        if _is_ancestor_skipped(elem):
            continue

        # Check if elem is a candidate block tag
        if tag in BLOCK_TAGS:
            # Collect text belonging directly to this block (and inline children),
            # without descending into child block tags which are processed separately.
            block_text = _collect_direct_block_text(elem)
            if not block_text.strip():
                # Skip empty blocks or whitespace-only container blocks
                continue

            # Deterministic, unique xpath via lxml getpath (works without namespace map overhead)
            block_xpath = tree.getpath(elem)

            # Tokenize into sentence spans
            if tokenizer is not None:
                spans = list(tokenizer.span_tokenize(block_text))
            else:
                spans = _fallback_sentence_spans(block_text)

            for raw_start, raw_end in spans:
                raw_sent = block_text[raw_start:raw_end]
                # Strip leading and trailing whitespace while adjusting exact character offsets
                l_strip = len(raw_sent) - len(raw_sent.lstrip())
                r_strip = len(raw_sent) - len(raw_sent.rstrip())
                s_start = raw_start + l_strip
                s_end = raw_end - r_strip

                if s_start >= s_end:
                    continue

                sent_text = block_text[s_start:s_end]
                if not sent_text.strip():
                    continue

                # Ensure exact character offset guarantee
                assert block_text[s_start:s_end] == sent_text

                placeholder_id = f"mo_s_{curr_id:04d}"
                sentence = Sentence({
                    "element_id_placeholder": placeholder_id,
                    "element_id": placeholder_id,
                    "text": sent_text,
                    "block_xpath": block_xpath,
                    "char_start": s_start,
                    "char_end": s_end,
                    "block_text": block_text,
                })
                results.append(sentence)
                curr_id += 1

    return results


def parse_epub(
    epub_path: Union[str, Path],
    work_dir: Union[str, Path, None] = None,
) -> dict[str, Any]:
    """High-level pipeline utility to unpack an EPUB and extract all chapter sentences.

    Parameters
    ----------
    epub_path : Union[str, Path]
        Path to the EPUB file.
    work_dir : Union[str, Path, None], optional
        Working directory for unpacking. If None, uses a temporary or sibling folder.

    Returns
    -------
    dict[str, Any]
        Dictionary with:
        - "work_dir": Path
        - "spine": list[PackageItem]
        - "chapters": list[dict] with chapter metadata and extracted sentences.
    """
    epub_path = Path(epub_path)
    if work_dir is None:
        work_dir = epub_path.parent / f".echopage_unpack_{epub_path.stem}"

def extract_navigation_metadata(
    work_dir: Union[str, Path],
) -> tuple[dict[str, str], dict[str, str]]:
    """Extract chapter title mappings from EPUB navigation document (nav.xhtml) and NCX (toc.ncx).

    Also extracts landmarks/guide metadata (e.g. 'toc', 'copyright', 'cover').

    Returns
    -------
    tuple[dict[str, str], dict[str, str]]
        (toc_titles_map, guide_types_map)
        Keys are normalized relative paths and filenames matching manifest hrefs.
    """
    work_dir = Path(work_dir)
    container_path = work_dir / "META-INF" / "container.xml"
    if not container_path.is_file():
        return {}, {}

    try:
        container_tree = etree.parse(str(container_path))
    except Exception:
        return {}, {}

    rootfile_nodes = container_tree.xpath("//*[local-name()='rootfile'][@full-path]")
    if not rootfile_nodes:
        return {}, {}

    opf_rel_path = rootfile_nodes[0].get("full-path")
    opf_path = work_dir / opf_rel_path
    if not opf_path.is_file():
        return {}, {}

    try:
        opf_tree = etree.parse(str(opf_path))
    except Exception:
        return {}, {}

    opf_dir = Path(opf_rel_path).parent
    toc_map: dict[str, str] = {}
    guide_map: dict[str, str] = {}

    def _register(d: dict[str, str], href_val: str, text_val: str):
        if not href_val or not text_val:
            return
        clean_href = href_val.split("#")[0].strip()
        if clean_href:
            d[clean_href] = text_val
            d[Path(clean_href).name] = text_val

    # 1. Parse OPF <guide> references
    for ref in opf_tree.xpath("//*[local-name()='guide']/*[local-name()='reference']"):
        href = ref.get("href", "")
        gtype = ref.get("type", "")
        _register(guide_map, href, gtype)

    # 2. Inspect manifest items for NCX and Nav XHTML documents
    ncx_hrefs: list[str] = []
    nav_hrefs: list[str] = []
    for item in opf_tree.xpath("//*[local-name()='manifest']/*[local-name()='item']"):
        mtype = (item.get("media-type") or "").lower()
        item_id = (item.get("id") or "").lower()
        href = item.get("href") or ""
        props = (item.get("properties") or "").lower()

        if "ncx" in mtype or item_id == "ncx" or href.lower().endswith(".ncx"):
            ncx_hrefs.append(href)
        if "nav" in props or item_id == "nav" or href.lower().endswith("nav.xhtml"):
            nav_hrefs.append(href)

    for ncx_href in ncx_hrefs:
        ncx_path = (work_dir / opf_dir / ncx_href) if str(opf_dir) != "." else (work_dir / ncx_href)
        if ncx_path.is_file():
            try:
                ncx_tree = etree.parse(str(ncx_path))
                for np in ncx_tree.xpath("//*[local-name()='navPoint']"):
                    content_src = "".join(np.xpath(".//*[local-name()='content']/@src"))
                    label_text = "".join(np.xpath(".//*[local-name()='text']/text()")).strip()
                    _register(toc_map, content_src, label_text)
            except Exception as exc:
                log.warning("Could not parse NCX document (%s): %s", ncx_path, exc)

    for nav_href in nav_hrefs:
        nav_path = (work_dir / opf_dir / nav_href) if str(opf_dir) != "." else (work_dir / nav_href)
        if nav_path.is_file():
            try:
                nav_tree = etree.parse(str(nav_path), parser=etree.XMLParser(recover=True))
                for a in nav_tree.xpath("//*[local-name()='nav']//*[local-name()='a']"):
                    href = a.get("href", "")
                    link_text = "".join(a.itertext()).strip()
                    _register(toc_map, href, link_text)
                    ep_type = a.get("{http://www.idpf.org/2007/ops}type") or a.get("type", "")
                    if ep_type:
                        _register(guide_map, href, ep_type)
            except Exception as exc:
                log.warning("Could not parse Nav document (%s): %s", nav_path, exc)

    return toc_map, guide_map


def extract_chapter_title(
    xhtml_source: Union[str, Path],
    toc_title: str | None = None,
    sentences: Sequence[Sentence] | None = None,
) -> str:
    """Extract a meaningful title for an EPUB chapter using prioritized fallback:
    1. Navigation document (nav.xhtml) or NCX (toc.ncx) label.
    2. Document <title> tag inside <head>.
    3. First prominent heading (<h1>, <h2>, <h3>, or <p/div class="title|chapter|head">).
    4. First non-empty text sentence as fallback.
    """
    # 1. NCX or Nav document label
    if toc_title and toc_title.strip():
        return toc_title.strip()

    # Load XHTML tree
    if isinstance(xhtml_source, Path) or (isinstance(xhtml_source, str) and not xhtml_source.strip().startswith("<")):
        source_path = Path(xhtml_source)
        if not source_path.is_file():
            if sentences:
                for s in sentences:
                    txt = s.text.strip() if hasattr(s, "text") else str(s).strip()
                    if txt:
                        return txt
            return ""
        raw_bytes = source_path.read_bytes()
    else:
        raw_bytes = xhtml_source.encode("utf-8") if isinstance(xhtml_source, str) else xhtml_source

    try:
        doc = etree.fromstring(raw_bytes, parser=etree.XMLParser(recover=True))
    except Exception:
        doc = None

    if doc is not None:
        # 2. Document <title> inside <head>
        title_nodes = doc.xpath("//*[local-name()='head']/*[local-name()='title']")
        if title_nodes:
            t_text = "".join(title_nodes[0].itertext()).strip()
            if t_text and t_text.lower() not in ("untitled", "unknown"):
                return t_text

        # 3. First prominent heading (h1, h2, h3 or p/div with class title|chapter|head)
        headings = doc.xpath(
            "//*[local-name()='h1' or local-name()='h2' or local-name()='h3']"
            " | "
            "//*[(local-name()='p' or local-name()='div') and ("
            "contains(@class, 'title') or contains(@class, 'chapter') or contains(@class, 'head')"
            ")]"
        )
        for h in headings:
            h_text = "".join(h.itertext()).strip()
            if h_text:
                return h_text

    def _sent_text(s) -> str:
        if isinstance(s, dict):
            return str(s.get("text", "")).strip()
        return str(getattr(s, "text", s)).strip()

    # 4. First non-empty text sentence as last-resort fallback
    if sentences:
        for s in sentences:
            txt = _sent_text(s)
            if txt:
                return txt

    if doc is not None:
        body_text = "".join(doc.xpath("//*[local-name()='body']//text()")).strip()
        if body_text:
            first_line = body_text.splitlines()[0].strip()
            if first_line:
                return first_line

    return ""


def parse_epub(
    epub_path: Union[str, Path],
    work_dir: Union[str, Path, None] = None,
) -> dict[str, Any]:
    """High-level pipeline utility to unpack an EPUB and extract all chapter sentences.

    Parameters
    ----------
    epub_path : Union[str, Path]
        Path to the EPUB file.
    work_dir : Union[str, Path, None], optional
        Working directory for unpacking. If None, uses a temporary or sibling folder.

    Returns
    -------
    dict[str, Any]
        Dictionary with:
        - "work_dir": Path
        - "spine": list[PackageItem]
        - "chapters": list[dict] with chapter metadata, title, and extracted sentences.
    """
    epub_path = Path(epub_path)
    if work_dir is None:
        work_dir = epub_path.parent / f".echopage_unpack_{epub_path.stem}"

    unpacked_dir = unpack(epub_path, work_dir)
    spine = read_package(unpacked_dir)
    toc_map, guide_map = extract_navigation_metadata(unpacked_dir)

    chapters = []
    sentence_counter = 1
    for item in spine:
        xhtml_file = item.file_path
        sentences = extract_sentences(xhtml_file, start_id=sentence_counter)
        sentence_counter += len(sentences)

        toc_title = toc_map.get(item.href) or toc_map.get(item.path.name)
        guide_type = guide_map.get(item.href) or guide_map.get(item.path.name)
        chapter_title = extract_chapter_title(
            xhtml_file,
            toc_title=toc_title,
            sentences=sentences,
        )

        chapters.append({
            "id": item.id,
            "href": item.href,
            "media_type": item.media_type,
            "file_path": xhtml_file,
            "title": chapter_title,
            "guide_type": guide_type,
            "sentences": sentences,
        })

    return {
        "work_dir": unpacked_dir,
        "spine": spine,
        "chapters": chapters,
    }


# Backwards compatibility alias
parse = parse_epub
