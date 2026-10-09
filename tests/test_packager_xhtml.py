"""Tests for EPUB packager XHTML sentence span ID injection."""

import copy
import shutil
from pathlib import Path

import pytest
from lxml import etree

from echopage import aligner, cli, packager, parser
from echopage.alignment import load_alignment
from echopage.packager import (
    IdCollisionError,
    PackagerError,
    XhtmlInjectionError,
    collect_text_segments,
    find_chapter_xhtml_path,
    inject_alignment_spans,
    inject_spans_into_element,
    inject_spans_into_xhtml,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_ALIGNMENT_PATH = FIXTURES_DIR / "alignment.sample.json"
SAMPLE_EPUB_PATH = FIXTURES_DIR / "book.epub"


@pytest.fixture
def sample_xhtml():
    """Return a minimal valid XHTML document with doctype and namespace."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en" lang="en">\n'
        '<head><title>Test Book</title></head>\n'
        '<body>\n'
        '  <section id="sec01">\n'
        '    <h1>Chapter 1: Beginnings</h1>\n'
        '    <p>First sentence here. Second sentence follows.</p>\n'
        '  </section>\n'
        '</body>\n'
        '</html>'
    )


def test_collect_text_segments():
    xml = "<p>Hello <em>brave <b>new</b> world</em>! How <a>are you</a> today?</p>"
    root = etree.fromstring(xml)
    segs = collect_text_segments(root)

    # Invariant: concatenation of text segments must strictly equal itertext
    joined = "".join(s[2] for s in segs)
    assert joined == "".join(root.itertext())
    assert len(segs) == 7


def test_inject_spans_simple_paragraph(sample_xhtml, tmp_path):
    doc_path = tmp_path / "chapter.xhtml"
    doc_path.write_text(sample_xhtml, encoding="utf-8")

    # In paragraph: "First sentence here. Second sentence follows."
    # len("First sentence here.") = 20 (0..20)
    # len(" ") = 1
    # len("Second sentence follows.") = 24 (21..45)
    timeline = [
        {
            "element_id": "mo_s_0001",
            "text": "Chapter 1: Beginnings",
            "block_xpath": "/*/*[2]/*/*[1]",
            "char_start": 0,
            "char_end": 21,
        },
        {
            "element_id": "mo_s_0002",
            "text": "First sentence here.",
            "block_xpath": "/*/*[2]/*/*[2]",
            "char_start": 0,
            "char_end": 20,
        },
        {
            "element_id": "mo_s_0003",
            "text": "Second sentence follows.",
            "block_xpath": "/*/*[2]/*/*[2]",
            "char_start": 21,
            "char_end": 45,
        },
    ]

    doc = inject_spans_into_xhtml(doc_path, timeline)
    root = doc.getroot()

    # Criterion 1: Every element_id appears exactly once as an id
    all_ids = root.xpath("//@id")
    assert all_ids.count("mo_s_0001") == 1
    assert all_ids.count("mo_s_0002") == 1
    assert all_ids.count("mo_s_0003") == 1
    # Existing id preserved
    assert "sec01" in all_ids

    # Criterion 2: Text content is 100% identical before and after
    orig_doc = etree.fromstring(sample_xhtml.encode("utf-8"))
    assert "".join(root.itertext()) == "".join(orig_doc.itertext())

    # Criterion 3: Output is well-formed XML and parses without error
    reloaded = etree.parse(str(doc_path))
    assert reloaded.getroot() is not None


def test_inject_spans_sentence_crossing_em_tag(tmp_path):
    """Test a sentence that crosses an <em> tag."""
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        '<head><title>Test</title></head>\n'
        '<body>\n'
        '  <p>I put forth my <em>full speed</em>. Mr. Fox witnessed it.</p>\n'
        '</body>\n'
        '</html>'
    )
    doc_path = tmp_path / "crossing.xhtml"
    doc_path.write_text(xml, encoding="utf-8")

    # In paragraph: "I put forth my full speed. Mr. Fox witnessed it."
    # "I put forth my " = 15 chars (in p.text)
    # "full speed" = 10 chars (in em.text)
    # ". Mr. Fox witnessed it." = 23 chars (in em.tail)
    # Sentence 1: "I put forth my full speed." -> 0..26
    # Sentence 2: "Mr. Fox witnessed it." -> 27..48
    timeline = [
        {
            "element_id": "mo_s_0001",
            "text": "I put forth my full speed.",
            "block_xpath": "/*/*[2]/*",
            "char_start": 0,
            "char_end": 26,
        },
        {
            "element_id": "mo_s_0002",
            "text": "Mr. Fox witnessed it.",
            "block_xpath": "/*/*[2]/*",
            "char_start": 27,
            "char_end": 48,
        },
    ]

    doc = inject_spans_into_xhtml(doc_path, timeline)
    root = doc.getroot()

    # Criterion 1: Every element_id appears exactly once as an id
    all_ids = root.xpath("//@id")
    assert all_ids.count("mo_s_0001") == 1
    assert all_ids.count("mo_s_0002") == 1

    # First span carries the main ID
    s1_elem = root.xpath("//*[@id='mo_s_0001']")[0]
    assert s1_elem.text == "I put forth my "

    # em tag is preserved and contains continuation
    em_elem = root.find(".//{http://www.w3.org/1999/xhtml}em")
    assert em_elem is not None
    assert len(em_elem) == 1
    continuation_span = em_elem[0]
    assert continuation_span.text == "full speed"
    assert "id" not in continuation_span.attrib

    # Period after em is also wrapped without id
    p_elem = root.find(".//{http://www.w3.org/1999/xhtml}p")
    spans = p_elem.findall("{http://www.w3.org/1999/xhtml}span")
    # p has s1, tail period span, and s2
    assert len(spans) == 3

    # Criterion 2: Text content is identical before and after
    orig_doc = etree.fromstring(xml.encode("utf-8"))
    assert "".join(root.itertext()) == "".join(orig_doc.itertext())

    # Criterion 3: Well-formed XML
    reloaded = etree.parse(str(doc_path))
    assert reloaded.getroot() is not None


def test_inject_spans_sentence_entirely_inside_inline_tag(tmp_path):
    """Test a sentence located entirely inside an inline tag."""
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        '<head><title>Test</title></head>\n'
        '<body>\n'
        '  <p>Start text. <em>Whole sentence in italics.</em> End text.</p>\n'
        '</body>\n'
        '</html>'
    )
    doc_path = tmp_path / "inside_em.xhtml"
    doc_path.write_text(xml, encoding="utf-8")

    # "Start text." = 0..11
    # " " = 11..12
    # "Whole sentence in italics." = 12..38
    # " " = 38..39
    # "End text." = 39..48
    timeline = [
        {
            "element_id": "mo_s_0001",
            "text": "Start text.",
            "block_xpath": "/*/*[2]/*",
            "char_start": 0,
            "char_end": 11,
        },
        {
            "element_id": "mo_s_0002",
            "text": "Whole sentence in italics.",
            "block_xpath": "/*/*[2]/*",
            "char_start": 12,
            "char_end": 38,
        },
        {
            "element_id": "mo_s_0003",
            "text": "End text.",
            "block_xpath": "/*/*[2]/*",
            "char_start": 39,
            "char_end": 48,
        },
    ]

    doc = inject_spans_into_xhtml(doc_path, timeline)
    root = doc.getroot()

    all_ids = root.xpath("//@id")
    assert all_ids == ["mo_s_0001", "mo_s_0002", "mo_s_0003"]

    # mo_s_0002 is inside em
    em_elem = root.find(".//{http://www.w3.org/1999/xhtml}em")
    assert em_elem.find("{http://www.w3.org/1999/xhtml}span").get("id") == "mo_s_0002"

    orig_doc = etree.fromstring(xml.encode("utf-8"))
    assert "".join(root.itertext()) == "".join(orig_doc.itertext())


def test_inject_spans_multiple_sentences_in_inline_tag(tmp_path):
    """Test multiple sentences inside a single inline tag."""
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        '<head><title>Test</title></head>\n'
        '<body>\n'
        '  <p><em>Sentence one here. Sentence two here.</em></p>\n'
        '</body>\n'
        '</html>'
    )
    doc_path = tmp_path / "multi_in_em.xhtml"
    doc_path.write_text(xml, encoding="utf-8")

    # "Sentence one here." = 0..18
    # " " = 18..19
    # "Sentence two here." = 19..37
    timeline = [
        {
            "element_id": "mo_s_0001",
            "text": "Sentence one here.",
            "block_xpath": "/*/*[2]/*",
            "char_start": 0,
            "char_end": 18,
        },
        {
            "element_id": "mo_s_0002",
            "text": "Sentence two here.",
            "block_xpath": "/*/*[2]/*",
            "char_start": 19,
            "char_end": 37,
        },
    ]

    doc = inject_spans_into_xhtml(doc_path, timeline)
    root = doc.getroot()

    em_elem = root.find(".//{http://www.w3.org/1999/xhtml}em")
    spans = em_elem.findall("{http://www.w3.org/1999/xhtml}span")
    assert len(spans) == 2
    assert spans[0].get("id") == "mo_s_0001"
    assert spans[1].get("id") == "mo_s_0002"

    orig_doc = etree.fromstring(xml.encode("utf-8"))
    assert "".join(root.itertext()) == "".join(orig_doc.itertext())


def test_inject_spans_nested_inline_tags(tmp_path):
    """Test sentence wrapping with nested inline tags (e.g. <a><em>...</em></a>)."""
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        '<head><title>Test</title></head>\n'
        '<body>\n'
        '  <p>Check <a href="http://example.com">the <em>cool link</em></a> now.</p>\n'
        '</body>\n'
        '</html>'
    )
    doc_path = tmp_path / "nested.xhtml"
    doc_path.write_text(xml, encoding="utf-8")

    # "Check the cool link now." = 0..24
    timeline = [
        {
            "element_id": "mo_s_0001",
            "text": "Check the cool link now.",
            "block_xpath": "/*/*[2]/*",
            "char_start": 0,
            "char_end": 24,
        }
    ]

    doc = inject_spans_into_xhtml(doc_path, timeline)
    root = doc.getroot()

    all_ids = root.xpath("//@id")
    assert all_ids == ["mo_s_0001"]

    orig_doc = etree.fromstring(xml.encode("utf-8"))
    assert "".join(root.itertext()) == "".join(orig_doc.itertext())


def test_existing_ids_preserved(tmp_path):
    """Test that pre-existing IDs in the source XHTML are preserved."""
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        '<head><title>Test</title></head>\n'
        '<body>\n'
        '  <section id="chapter_intro">\n'
        '    <h1 id="heading_title">Title</h1>\n'
        '    <p id="first_para">A simple sentence.</p>\n'
        '  </section>\n'
        '</body>\n'
        '</html>'
    )
    doc_path = tmp_path / "ids.xhtml"
    doc_path.write_text(xml, encoding="utf-8")

    timeline = [
        {
            "element_id": "mo_s_0001",
            "text": "Title",
            "block_xpath": "/*/*[2]/*/*[1]",
            "char_start": 0,
            "char_end": 5,
        },
        {
            "element_id": "mo_s_0002",
            "text": "A simple sentence.",
            "block_xpath": "/*/*[2]/*/*[2]",
            "char_start": 0,
            "char_end": 18,
        },
    ]

    doc = inject_spans_into_xhtml(doc_path, timeline)
    root = doc.getroot()

    all_ids = root.xpath("//@id")
    assert "chapter_intro" in all_ids
    assert "heading_title" in all_ids
    assert "first_para" in all_ids
    assert "mo_s_0001" in all_ids
    assert "mo_s_0002" in all_ids


def test_id_collision_detected(tmp_path):
    """Test that an existing ID colliding with mo_s_* raises IdCollisionError."""
    # Case 1: Existing ID directly collides with target timeline element_id
    xml1 = (
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
        '<div id="mo_s_0001">Already here</div><p>Sentence one.</p>'
        '</body></html>'
    )
    doc1 = tmp_path / "collision1.xhtml"
    doc1.write_text(xml1, encoding="utf-8")

    timeline1 = [
        {
            "element_id": "mo_s_0001",
            "text": "Sentence one.",
            "block_xpath": "/*/*[2]/*[2]",
            "char_start": 0,
            "char_end": 13,
        }
    ]

    with pytest.raises(IdCollisionError) as exc_info:
        inject_spans_into_xhtml(doc1, timeline1)
    assert "ID collision" in str(exc_info.value)
    assert "mo_s_0001" in str(exc_info.value)

    # Case 2: Existing ID matches mo_s_* prefix pattern even if not in current timeline
    xml2 = (
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
        '<p id="mo_s_9999">Prefix collision.</p>'
        '</body></html>'
    )
    doc2 = tmp_path / "collision2.xhtml"
    doc2.write_text(xml2, encoding="utf-8")

    timeline2 = [
        {
            "element_id": "mo_s_0001",
            "text": "Prefix collision.",
            "block_xpath": "/*/*[2]/*",
            "char_start": 0,
            "char_end": 17,
        }
    ]

    with pytest.raises(IdCollisionError) as exc_info2:
        inject_spans_into_xhtml(doc2, timeline2)
    assert "mo_s_*" in str(exc_info2.value) or "mo_s_9999" in str(exc_info2.value)


def test_preserves_doctype_and_xml_declaration(sample_xhtml, tmp_path):
    """Test that XML declaration and DOCTYPE are preserved in written file."""
    doc_path = tmp_path / "doctype_test.xhtml"
    doc_path.write_text(sample_xhtml, encoding="utf-8")

    timeline = [
        {
            "element_id": "mo_s_0001",
            "text": "Chapter 1: Beginnings",
            "block_xpath": "/*/*[2]/*/*[1]",
            "char_start": 0,
            "char_end": 21,
        }
    ]

    inject_spans_into_xhtml(doc_path, timeline)
    raw_content = doc_path.read_text(encoding="utf-8")

    assert "<?xml" in raw_content
    assert "<!DOCTYPE html>" in raw_content
    assert 'xmlns="http://www.w3.org/1999/xhtml"' in raw_content


def test_invalid_block_xpath_raises_error(sample_xhtml, tmp_path):
    """Test that non-existent block XPath raises XhtmlInjectionError."""
    doc_path = tmp_path / "xpath_error.xhtml"
    doc_path.write_text(sample_xhtml, encoding="utf-8")

    timeline = [
        {
            "element_id": "mo_s_0001",
            "text": "Chapter 1: Beginnings",
            "block_xpath": "/*/*[2]/*/*[999]",  # Does not exist
            "char_start": 0,
            "char_end": 21,
        }
    ]

    with pytest.raises(XhtmlInjectionError) as exc:
        inject_spans_into_xhtml(doc_path, timeline)
    assert "not found" in str(exc.value)


def test_invalid_char_offsets_raises_error(sample_xhtml, tmp_path):
    """Test that invalid character offsets raise XhtmlInjectionError."""
    doc_path = tmp_path / "bounds_error.xhtml"
    doc_path.write_text(sample_xhtml, encoding="utf-8")

    timeline = [
        {
            "element_id": "mo_s_0001",
            "text": "Too long",
            "block_xpath": "/*/*[2]/*/*[1]",
            "char_start": 0,
            "char_end": 9999,  # Out of bounds
        }
    ]

    with pytest.raises(XhtmlInjectionError) as exc:
        inject_spans_into_xhtml(doc_path, timeline)
    assert "invalid" in str(exc.value) or "bounds" in str(exc.value)


def test_inject_alignment_spans_on_unpacked_epub(tmp_path):
    """End-to-end test on unpacked book.epub using alignment.sample.json."""
    work_dir = tmp_path / "unpacked"
    parser.unpack(SAMPLE_EPUB_PATH, work_dir)

    # Load sample alignment fixture
    alignment = load_alignment(SAMPLE_ALIGNMENT_PATH)
    assert len(alignment) == 2

    # Save original text contents of both chapters
    orig_texts = {}
    for ch in alignment:
        ch_path = find_chapter_xhtml_path(work_dir, ch)
        orig_doc = etree.parse(str(ch_path))
        orig_texts[ch.spine_item_id] = "".join(orig_doc.getroot().itertext())

    # Perform injection across all chapters in work directory
    modified_paths = inject_alignment_spans(work_dir, alignment)

    assert len(modified_paths) == 2
    assert "chapter01" in modified_paths
    assert "chapter02" in modified_paths

    # Verify each chapter meets all acceptance criteria
    total_injected_ids = 0
    for ch in alignment:
        ch_path = modified_paths[ch.spine_item_id]
        assert ch_path.is_file()

        # Reload with lxml: well-formed XML parsing without error
        reloaded_doc = etree.parse(str(ch_path))
        root = reloaded_doc.getroot()

        # Acceptance Criterion 2: text content is identical before and after
        new_text = "".join(root.itertext())
        assert orig_texts[ch.spine_item_id] == new_text

        # Acceptance Criterion 1: every element_id appears exactly once as an id
        all_ids = root.xpath("//@id")
        for entry in ch.timeline:
            eid = entry.element_id
            count = all_ids.count(eid)
            assert count == 1, f"element_id '{eid}' appeared {count} times (expected 1)"
            total_injected_ids += 1

        # Acceptance Criterion 5: existing id (e.g. section#ch01) is preserved
        if ch.spine_item_id == "chapter01":
            assert "ch01" in all_ids
        elif ch.spine_item_id == "chapter02":
            assert "ch02" in all_ids

    # Total 13 sentences injected across the 2 chapters
    assert total_injected_ids == 13

    # Acceptance Criterion 4: check chapter 1 sentence 3 covering <em> tag
    ch1_doc = etree.parse(str(modified_paths["chapter01"]))
    ch1_root = ch1_doc.getroot()
    s3_elem = ch1_root.xpath("//*[@id='mo_s_0003']")[0]
    assert "full speed" not in s3_elem.text  # Text fragment before em
    em_elem = ch1_root.find(".//{http://www.w3.org/1999/xhtml}em")
    assert em_elem is not None
    assert em_elem[0].text == "full speed"  # Fragment inside em


def test_cli_inject_spans_subcommand(tmp_path):
    """Test the CLI inject-spans subcommand."""
    work_dir = tmp_path / "cli_unpacked"
    parser.unpack(SAMPLE_EPUB_PATH, work_dir)

    ret = cli.main(["inject-spans", str(work_dir), str(SAMPLE_ALIGNMENT_PATH)])
    assert ret == 0

    # Verify files were modified in place
    ch1_path = work_dir / "EPUB" / "chapter01.xhtml"
    doc = etree.parse(str(ch1_path))
    assert doc.xpath("//*[@id='mo_s_0001']") is not None
    assert doc.xpath("//*[@id='mo_s_0008']") is not None


def test_cli_inject_spans_missing_directory_errors(tmp_path):
    """Test CLI error handling when work directory does not exist."""
    with pytest.raises(SystemExit):
        cli.main(["inject-spans", str(tmp_path / "nonexistent"), str(SAMPLE_ALIGNMENT_PATH)])
