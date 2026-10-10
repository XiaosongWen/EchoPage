"""Unit and integration tests for EPUB parser and sentence tokenizer (Task 06)."""

import io
import shutil
import tempfile
import zipfile
from pathlib import Path

import pytest
from lxml import etree

from echopage.parser import (
    EpubError,
    EpubSecurityError,
    PackageItem,
    Sentence,
    extract_sentences,
    parse_epub,
    read_package,
    unpack,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
BOOK_EPUB = FIXTURES_DIR / "book.epub"


# ============================================================================
# 1. Archive Unpacking & Path Traversal Security Tests
# ============================================================================

def test_unpack_valid_epub():
    """Verify that a valid EPUB archive unpacks successfully into target directory."""
    with tempfile.TemporaryDirectory() as td:
        work_dir = Path(td) / "unpacked"
        res = unpack(BOOK_EPUB, work_dir)
        assert res == work_dir.resolve()
        assert (work_dir / "mimetype").is_file()
        assert (work_dir / "META-INF" / "container.xml").is_file()
        assert (work_dir / "EPUB" / "package.opf").is_file()
        assert (work_dir / "EPUB" / "chapter01.xhtml").is_file()
        assert (work_dir / "EPUB" / "chapter02.xhtml").is_file()


def test_unpack_missing_file_raises():
    """Verify unpack raises FileNotFoundError on missing file."""
    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(FileNotFoundError):
            unpack("non_existent_book.epub", td)


def test_unpack_rejects_relative_path_traversal():
    """Acceptance criterion: A zip with a '../evil' entry is rejected."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("../evil.txt", "pwned")

    buf.seek(0)
    with tempfile.TemporaryDirectory() as td:
        bad_zip = Path(td) / "evil.epub"
        bad_zip.write_bytes(buf.getvalue())

        extract_to = Path(td) / "dest"
        with pytest.raises((ValueError, EpubSecurityError)) as exc_info:
            unpack(bad_zip, extract_to)
        assert "traversal" in str(exc_info.value).lower()
        # Ensure file was never written outside dest
        assert not (Path(td) / "evil.txt").exists()


def test_unpack_rejects_nested_relative_path_traversal():
    """Verify paths like 'sub/../../evil' are rejected."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("sub/../../evil.txt", "pwned")

    buf.seek(0)
    with tempfile.TemporaryDirectory() as td:
        bad_zip = Path(td) / "evil2.epub"
        bad_zip.write_bytes(buf.getvalue())
        extract_to = Path(td) / "dest"
        with pytest.raises((ValueError, EpubSecurityError)):
            unpack(bad_zip, extract_to)


def test_unpack_rejects_absolute_path_traversal():
    """Verify absolute paths starting with / are rejected."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("/tmp/evil.txt", "pwned")

    buf.seek(0)
    with tempfile.TemporaryDirectory() as td:
        bad_zip = Path(td) / "evil3.epub"
        bad_zip.write_bytes(buf.getvalue())
        extract_to = Path(td) / "dest"
        with pytest.raises((ValueError, EpubSecurityError)):
            unpack(bad_zip, extract_to)


# ============================================================================
# 2. Package & Spine Resolution Tests
# ============================================================================

def test_read_package_fixture_epub():
    """Acceptance criterion: The fixture EPUB unpacks and its spine order matches the OPF."""
    with tempfile.TemporaryDirectory() as td:
        work_dir = unpack(BOOK_EPUB, td)
        spine_items = read_package(work_dir)

        # Spine must contain chapter01 and chapter02 in exact reading order
        assert len(spine_items) == 2
        ch1, ch2 = spine_items[0], spine_items[1]

        assert ch1["id"] == "chapter01"
        assert ch1["href"] == "chapter01.xhtml"
        assert ch1["media_type"] == "application/xhtml+xml"
        assert ch1.id == "chapter01"
        assert ch1.href == "chapter01.xhtml"
        assert ch1.file_path == work_dir / "EPUB" / "chapter01.xhtml"
        assert ch1.file_path.is_file()

        assert ch2["id"] == "chapter02"
        assert ch2["href"] == "chapter02.xhtml"
        assert ch2["media_type"] == "application/xhtml+xml"
        assert ch2.id == "chapter02"
        assert ch2.href == "chapter02.xhtml"
        assert ch2.file_path == work_dir / "EPUB" / "chapter02.xhtml"
        assert ch2.file_path.is_file()


def test_read_package_filters_non_xhtml_items():
    """Verify that CSS, images, and non-XHTML items in spine or manifest are filtered."""
    with tempfile.TemporaryDirectory() as td:
        meta_inf = Path(td) / "META-INF"
        meta_inf.mkdir(parents=True)
        (meta_inf / "container.xml").write_text(
            '<?xml version="1.0"?>'
            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '  <rootfiles>'
            '    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>'
            '  </rootfiles>'
            '</container>',
            encoding="utf-8"
        )
        (Path(td) / "content.opf").write_text(
            '<?xml version="1.0"?>'
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
            '  <manifest>'
            '    <item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>'
            '    <item id="img" href="pic.jpg" media-type="image/jpeg"/>'
            '    <item id="c2" href="ch2.html" media-type="text/html"/>'
            '  </manifest>'
            '  <spine>'
            '    <itemref idref="c1"/>'
            '    <itemref idref="img"/>'
            '    <itemref idref="c2"/>'
            '  </spine>'
            '</package>',
            encoding="utf-8"
        )
        spine = read_package(td)
        assert len(spine) == 2
        assert [item.id for item in spine] == ["c1", "c2"]


def test_read_package_missing_container_raises():
    """Verify read_package raises FileNotFoundError when container.xml is missing."""
    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(FileNotFoundError):
            read_package(td)


def test_read_package_missing_opf_raises():
    """Verify read_package raises FileNotFoundError when OPF file does not exist."""
    with tempfile.TemporaryDirectory() as td:
        meta_inf = Path(td) / "META-INF"
        meta_inf.mkdir(parents=True)
        (meta_inf / "container.xml").write_text(
            '<?xml version="1.0"?>'
            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '  <rootfiles>'
            '    <rootfile full-path="non_existent.opf" media-type="application/oebps-package+xml"/>'
            '  </rootfiles>'
            '</container>',
            encoding="utf-8"
        )
        with pytest.raises(FileNotFoundError):
            read_package(td)


# ============================================================================
# 3. Sentence Extraction, Inline Tags, and Offset Invariant Tests
# ============================================================================

def test_extract_sentences_chapter01_fixture():
    """Verify sentence extraction on chapter01.xhtml fixture:

    - Acceptance criterion: Sentences from a paragraph with <em> inside come out as whole sentences.
    - Acceptance criterion: Offsets map back: original_text[char_start:char_end] == sentence text.
    - Acceptance criterion: Tests cover abbreviations ('Mr. Fox' / 'Mr. Smith') and quotes.
    """
    with tempfile.TemporaryDirectory() as td:
        work_dir = unpack(BOOK_EPUB, td)
        ch1_path = work_dir / "EPUB" / "chapter01.xhtml"

        sentences = extract_sentences(ch1_path)
        assert len(sentences) == 8

        # 1. Title sentence in <h1>
        assert sentences[0].text == "Chapter 1: The Tortoise and the Hare"
        assert sentences[0].char_start == 0
        assert sentences[0].char_end == len(sentences[0].text)

        # 2. Paragraph 1 with <em>full speed</em> and 'Mr. Fox' abbreviation
        # Sentence with <em>: '"I have never yet been beaten," said he, "when I put forth my full speed.'
        sent_em = sentences[2]
        assert 'put forth my full speed' in sent_em.text
        assert 'full speed' in sent_em.text
        # Invariant check
        assert sent_em.block_text[sent_em.char_start:sent_em.char_end] == sent_em.text

        # Sentence with abbreviation 'Mr. Fox':
        sent_mr = sentences[3]
        assert sent_mr.text == 'Mr. Fox can witness my victories."'
        # Confirm 'Mr.' did not split the sentence
        assert not any(s.text.strip() == "Mr." for s in sentences)
        assert sent_mr.block_text[sent_mr.char_start:sent_mr.char_end] == sent_mr.text

        # Check every sentence satisfies offset mapping back to original block text
        doc = etree.parse(str(ch1_path))
        for s in sentences:
            # Verify block_xpath resolves the exact block element
            matched = doc.xpath(s.block_xpath)
            assert len(matched) == 1, f"Failed xpath resolution for {s.block_xpath}"
            block_elem = matched[0]
            orig_text = "".join(block_elem.itertext())
            assert orig_text[s.char_start:s.char_end] == s.text, (
                f"Offset mismatch: expected {s.text!r}, got {orig_text[s.char_start:s.char_end]!r}"
            )


def test_extract_sentences_chapter02_fixture():
    """Verify sentence extraction on chapter02.xhtml fixture."""
    with tempfile.TemporaryDirectory() as td:
        work_dir = unpack(BOOK_EPUB, td)
        ch2_path = work_dir / "EPUB" / "chapter02.xhtml"

        sentences = extract_sentences(ch2_path)
        assert len(sentences) == 5

        doc = etree.parse(str(ch2_path))
        for s in sentences:
            matched = doc.xpath(s.block_xpath)
            assert len(matched) == 1
            orig_text = "".join(matched[0].itertext())
            assert orig_text[s.char_start:s.char_end] == s.text


def test_extract_sentences_abbreviations_and_quotes():
    """Acceptance criterion: Tests cover abbreviations ('Mr. Smith went.') and quotes."""
    xhtml = """<?xml version="1.0" encoding="UTF-8"?>
    <!DOCTYPE html>
    <html xmlns="http://www.w3.org/1999/xhtml">
    <body>
      <p>Mr. Smith went to the store. "Are you coming?" asked Mrs. Davis. Dr. Watson was also there at 4 p.m. yesterday.</p>
      <p>"I am ready," said Alice. "Let us begin!"</p>
    </body>
    </html>"""

    sentences = extract_sentences(xhtml)
    texts = [s.text for s in sentences]

    # Verify 'Mr. Smith went to the store.' is a single whole sentence
    assert "Mr. Smith went to the store." in texts
    assert not any(t == "Mr." for t in texts)

    # Verify 'Dr. Watson was also there at 4 p.m. yesterday.' is not split at Dr. or p.m.
    assert any("Dr. Watson was also there" in t for t in texts)
    assert not any(t == "Dr." for t in texts)

    # Check offset invariant on every sentence
    for s in sentences:
        assert s.block_text[s.char_start:s.char_end] == s.text


def test_extract_sentences_inline_tags():
    """Verify various inline tags (em, a, strong, span, code) concatenate cleanly."""
    xhtml = """<?xml version="1.0" encoding="UTF-8"?>
    <html xmlns="http://www.w3.org/1999/xhtml">
    <body>
      <p>The <a href="http://example.com">quick brown <strong>fox</strong></a> jumped over the <em>lazy dog</em>. It was <code>awesome</code>!</p>
    </body>
    </html>"""

    sentences = extract_sentences(xhtml)
    assert len(sentences) == 2
    assert sentences[0].text == "The quick brown fox jumped over the lazy dog."
    assert sentences[1].text == "It was awesome!"

    for s in sentences:
        assert s.block_text[s.char_start:s.char_end] == s.text


def test_extract_sentences_skips_non_content():
    """Verify script, style, nav, head, and nested elements within them are skipped."""
    xhtml = """<?xml version="1.0" encoding="UTF-8"?>
    <html xmlns="http://www.w3.org/1999/xhtml">
    <head>
      <title>Book Title</title>
      <style>body { font-size: 14px; }</style>
    </head>
    <body>
      <script>console.log("Ignore me");</script>
      <nav>
        <h1>Table of Contents</h1>
        <ol>
          <li><a href="ch1.xhtml">Chapter 1</a></li>
        </ol>
      </nav>
      <section>
        <p>This is the real content.</p>
      </section>
    </body>
    </html>"""

    sentences = extract_sentences(xhtml)
    assert len(sentences) == 1
    assert sentences[0].text == "This is the real content."
    assert sentences[0].block_text[sentences[0].char_start:sentences[0].char_end] == sentences[0].text


def test_extract_sentences_skips_empty_and_whitespace_blocks():
    """Verify empty blocks and blocks with only whitespace are skipped."""
    xhtml = """<?xml version="1.0" encoding="UTF-8"?>
    <html xmlns="http://www.w3.org/1999/xhtml">
    <body>
      <p></p>
      <p>   \n\t  </p>
      <h1>Actual Heading</h1>
      <div>    </div>
      <p>Actual paragraph.</p>
      <p><span>   </span></p>
    </body>
    </html>"""

    sentences = extract_sentences(xhtml)
    assert len(sentences) == 2
    assert sentences[0].text == "Actual Heading"
    assert sentences[1].text == "Actual paragraph."


def test_extract_sentences_nested_block_leaf_resolution():
    """Verify nested blocks (blockquote/p, div/p, ul/li) extract only from leaf blocks without duplicate sentences."""
    xhtml = """<?xml version="1.0" encoding="UTF-8"?>
    <html xmlns="http://www.w3.org/1999/xhtml">
    <body>
      <blockquote>
        <p>Nested quote line one.</p>
        <p>Nested quote line two.</p>
      </blockquote>
      <ul>
        <li>First bullet.</li>
        <li>Second bullet.</li>
      </ul>
      <div class="verse">A standalone div without child blocks.</div>
    </body>
    </html>"""

    sentences = extract_sentences(xhtml)
    texts = [s.text for s in sentences]
    assert texts == [
        "Nested quote line one.",
        "Nested quote line two.",
        "First bullet.",
        "Second bullet.",
        "A standalone div without child blocks.",
    ]
    for s in sentences:
        assert s.block_text[s.char_start:s.char_end] == s.text


def test_sentence_data_contract():
    """Verify keys, properties, and tuple unpacking on Sentence objects."""
    xhtml = """<html xmlns="http://www.w3.org/1999/xhtml"><body><p>Hello world.</p></body></html>"""
    sentences = extract_sentences(xhtml, start_id=42)
    assert len(sentences) == 1
    s = sentences[0]

    # Required dictionary keys from Task 06
    assert "element_id_placeholder" in s
    assert "text" in s
    assert "block_xpath" in s
    assert "char_start" in s
    assert "char_end" in s

    # Properties
    assert s.element_id_placeholder == "mo_s_0042"
    assert s.element_id == "mo_s_0042"
    assert s.text == "Hello world."
    assert s.char_start == 0
    assert s.char_end == 12

    # Tuple unpacking
    placeholder, text, xpath, start, end = s
    assert placeholder == "mo_s_0042"
    assert text == "Hello world."
    assert start == 0
    assert end == 12


def test_package_item_data_contract():
    """Verify PackageItem dictionary keys and properties."""
    item = PackageItem({
        "id": "item1",
        "href": "chapter1.xhtml",
        "media_type": "application/xhtml+xml",
        "path": Path("EPUB/chapter1.xhtml"),
        "file_path": Path("/tmp/work/EPUB/chapter1.xhtml"),
    })
    assert item["id"] == "item1"
    assert item["href"] == "chapter1.xhtml"
    assert item["media_type"] == "application/xhtml+xml"
    assert item.id == "item1"
    assert item.href == "chapter1.xhtml"
    assert item.media_type == "application/xhtml+xml"
    assert item.path == Path("EPUB/chapter1.xhtml")
    assert item.file_path == Path("/tmp/work/EPUB/chapter1.xhtml")


# ============================================================================
# 4. End-to-End Pipeline Utility: parse_epub
# ============================================================================

def test_parse_epub_pipeline():
    """Verify parse_epub end-to-end unpacking and extraction."""
    with tempfile.TemporaryDirectory() as td:
        work_dir = Path(td) / "unpack_dest"
        result = parse_epub(BOOK_EPUB, work_dir=work_dir)

        assert result["work_dir"] == work_dir.resolve()
        assert len(result["spine"]) == 2
        assert len(result["chapters"]) == 2

        ch1 = result["chapters"][0]
        assert ch1["id"] == "chapter01"
        assert len(ch1["sentences"]) == 8

        ch2 = result["chapters"][1]
        assert ch2["id"] == "chapter02"
        assert len(ch2["sentences"]) == 5

        # Verify sequential sentence IDs across chapters
        all_ids = [s.element_id_placeholder for ch in result["chapters"] for s in ch["sentences"]]
        assert len(all_ids) == 13
        assert all_ids[0] == "mo_s_0001"
        assert all_ids[-1] == "mo_s_0013"


def test_unpack_corrupted_zip_raises_epub_error():
    """Verify corrupted zip archive raises EpubError."""
    with tempfile.TemporaryDirectory() as td:
        corrupted = Path(td) / "corrupt.epub"
        corrupted.write_bytes(b"not a valid zip archive header")
        with pytest.raises(EpubError):
            unpack(corrupted, Path(td) / "dest")


def test_extract_sentences_missing_file_raises():
    """Verify FileNotFoundError is raised when xhtml file does not exist."""
    with pytest.raises(FileNotFoundError):
        extract_sentences("non_existent_file.xhtml")


def test_extract_sentences_nested_blocks_preserves_parent_text():
    """Verify that direct text in block elements containing child blocks is preserved."""
    xhtml = """<html xmlns="http://www.w3.org/1999/xhtml">
    <body>
      <div>
        Chapter 1 Introduction.
        <p>First paragraph text.</p>
        Concluding note.
      </div>
      <ul>
        <li>Item header text.
          <ul>
            <li>Sub item text.</li>
          </ul>
        </li>
      </ul>
    </body>
    </html>"""
    sentences = extract_sentences(xhtml)
    texts = [s.text for s in sentences]
    assert "Chapter 1 Introduction." in texts
    assert "Concluding note." in texts
    assert "First paragraph text." in texts
    assert "Item header text." in texts
    assert "Sub item text." in texts

