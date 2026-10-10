"""Tests for EPUB 3 Media Overlays SMIL generation and audio placement."""

import re
import shutil
from pathlib import Path

import pytest
from lxml import etree

from echopage import cli, packager, parser
from echopage.alignment import load_alignment
from echopage.packager import (
    SmilDuration,
    SmilGenerationError,
    SmilMetadata,
    copy_chapter_audio,
    find_epub_content_dir,
    format_clock_hms,
    format_smil_clock,
    generate_chapter_smil,
    generate_smil_playlists,
    inject_alignment_spans,
    parse_smil_clock,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_ALIGNMENT_PATH = FIXTURES_DIR / "alignment.sample.json"
SAMPLE_EPUB_PATH = FIXTURES_DIR / "book.epub"
BOOK_PARTS_DIR = FIXTURES_DIR / "book_parts"

SMIL_NS = "http://www.w3.org/ns/SMIL"
EPUB_NS = "http://www.idpf.org/2007/ops"


@pytest.fixture
def minimal_xhtml(tmp_path):
    """Create a minimal XHTML file with known IDs."""
    content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">\n'
        '<head><title>Test</title></head>\n'
        '<body>\n'
        '  <p><span id="mo_s_0001">First sentence.</span> '
        '<span id="mo_s_0002">Second sentence.</span></p>\n'
        '</body>\n'
        '</html>'
    )
    p = tmp_path / "chapter01.xhtml"
    p.write_text(content, encoding="utf-8")
    return p


@pytest.fixture
def dummy_audio(tmp_path):
    """Create a dummy audio file."""
    audio_path = tmp_path / "audio_source" / "chapter01.mp3"
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(b"dummy audio content")
    return audio_path


def test_format_smil_clock():
    assert format_smil_clock(0) == "0.000s"
    assert format_smil_clock(31) == "0.031s"
    assert format_smil_clock(2340) == "2.340s"
    assert format_smil_clock(123456) == "123.456s"
    with pytest.raises(ValueError):
        format_smil_clock(-10)


def test_parse_smil_clock():
    assert parse_smil_clock("2.340s") == 2.34
    assert parse_smil_clock("0.031s") == 0.031
    assert parse_smil_clock("123.456s") == 123.456
    assert parse_smil_clock("01:02:03.456") == 3723.456
    assert parse_smil_clock("02:03.456") == 123.456


def test_format_clock_hms():
    # Acceptance criteria from Task 12: 3723456 ms becomes 01:02:03.456
    assert format_clock_hms(3723456) == "01:02:03.456"
    assert format_clock_hms(0) == "00:00:00.000"
    assert format_clock_hms(59000) == "00:00:59.000"
    assert format_clock_hms(61050) == "00:01:01.050"


def test_smil_duration_behavior():
    dur = SmilDuration(2.340, 2340)
    assert dur.ms == 2340
    assert dur.clock == "2.340s"
    assert dur.hms == "00:00:02.340"
    assert str(dur) == "2.340s"

    # Equates to both numeric seconds and string representation
    assert dur == 2.34
    assert dur == "2.340s"
    assert dur == "2.340"
    assert float(dur) == 2.340


def test_generate_chapter_smil_xml_structure_and_namespaces(minimal_xhtml, tmp_path):
    """Test AC 1: The output SMIL parses as XML and uses the http://www.w3.org/ns/SMIL namespace."""
    smil_path = tmp_path / "chapter01.smil"
    chapter_data = {
        "spine_item_id": "chapter01",
        "xhtml_filename": "chapter01.xhtml",
        "audio_filename": "chapter01.mp3",
        "timeline": [
            {"element_id": "mo_s_0001", "start_ms": 120, "end_ms": 2340},
            {"element_id": "mo_s_0002", "start_ms": 2360, "end_ms": 4120},
        ],
    }

    meta = generate_chapter_smil(
        chapter=chapter_data,
        smil_path=smil_path,
        xhtml_path=minimal_xhtml,
        audio_rel_path="audio/chapter01.mp3",
    )

    assert smil_path.is_file()
    doc = etree.parse(str(smil_path))
    root = doc.getroot()

    # XML root tag and namespace
    assert root.tag == f"{{{SMIL_NS}}}smil"
    assert root.nsmap[None] == SMIL_NS
    assert root.nsmap["epub"] == EPUB_NS
    assert root.get("version") == "3.0"

    # Body and seq
    body = root.find(f"{{{SMIL_NS}}}body")
    assert body is not None
    seq = body.find(f"{{{SMIL_NS}}}seq")
    assert seq is not None

    # Seq attributes: id, epub:textref, epub:type
    assert seq.get("id") == "seq_chapter01"
    assert seq.get(f"{{{EPUB_NS}}}textref") == "chapter01.xhtml"
    assert seq.get(f"{{{EPUB_NS}}}type") == "chapter"

    # Par elements
    pars = seq.findall(f"{{{SMIL_NS}}}par")
    assert len(pars) == 2
    assert pars[0].get("id") == "par_0001"
    assert pars[1].get("id") == "par_0002"

    # Text and audio elements
    t0 = pars[0].find(f"{{{SMIL_NS}}}text")
    a0 = pars[0].find(f"{{{SMIL_NS}}}audio")
    assert t0.get("src") == "chapter01.xhtml#mo_s_0001"
    assert a0.get("src") == "audio/chapter01.mp3"
    assert a0.get("clipBegin") == "0.120s"
    assert a0.get("clipEnd") == "2.340s"

    t1 = pars[1].find(f"{{{SMIL_NS}}}text")
    a1 = pars[1].find(f"{{{SMIL_NS}}}audio")
    assert t1.get("src") == "chapter01.xhtml#mo_s_0002"
    assert a1.get("src") == "audio/chapter01.mp3"
    assert a1.get("clipBegin") == "2.360s"
    assert a1.get("clipEnd") == "4.120s"


def test_clip_times_formatting_and_order(minimal_xhtml, tmp_path):
    """Test AC 2: Clip times are formatted as N.NNNs and are in order."""
    smil_path = tmp_path / "chapter01.smil"
    chapter_data = {
        "spine_item_id": "chapter01",
        "timeline": [
            {"element_id": "mo_s_0001", "start_ms": 31, "end_ms": 2014},
            {"element_id": "mo_s_0002", "start_ms": 2295, "end_ms": 5360},
        ],
    }

    generate_chapter_smil(
        chapter=chapter_data,
        smil_path=smil_path,
        xhtml_path=minimal_xhtml,
        audio_rel_path="audio/chapter01.mp3",
    )

    doc = etree.parse(str(smil_path))
    audios = doc.xpath("//smil:audio", namespaces={"smil": SMIL_NS})
    pattern = re.compile(r"^\d+\.\d{3}s$")

    prev_end = 0.0
    for aud in audios:
        cb = aud.get("clipBegin")
        ce = aud.get("clipEnd")
        assert pattern.match(cb), f"clipBegin '{cb}' does not match N.NNNs format"
        assert pattern.match(ce), f"clipEnd '{ce}' does not match N.NNNs format"

        cb_val = parse_smil_clock(cb)
        ce_val = parse_smil_clock(ce)
        assert cb_val < ce_val
        assert cb_val >= prev_end
        prev_end = ce_val


def test_every_text_src_points_to_existing_id(minimal_xhtml, tmp_path):
    """Test AC 3: Every <text src> fragment points to an ID that exists in the XHTML."""
    smil_path = tmp_path / "chapter01.smil"
    chapter_data = {
        "spine_item_id": "chapter01",
        "timeline": [
            {"element_id": "mo_s_0001", "start_ms": 0, "end_ms": 1000},
            {"element_id": "mo_s_0002", "start_ms": 1000, "end_ms": 2000},
        ],
    }

    generate_chapter_smil(
        chapter=chapter_data,
        smil_path=smil_path,
        xhtml_path=minimal_xhtml,
        audio_rel_path="audio/chapter01.mp3",
        validate_xhtml_ids=True,
    )

    # Read SMIL and verify against XHTML DOM
    smil_doc = etree.parse(str(smil_path))
    xhtml_doc = etree.parse(str(minimal_xhtml))
    xhtml_ids = set(xhtml_doc.xpath("//@id"))

    text_nodes = smil_doc.xpath("//smil:text", namespaces={"smil": SMIL_NS})
    for t in text_nodes:
        src = t.get("src")
        assert "#" in src
        file_part, frag_id = src.split("#", 1)
        assert frag_id in xhtml_ids


def test_missing_xhtml_id_raises_error(minimal_xhtml, tmp_path):
    """Test that a non-existent element_id raises SmilGenerationError when validating."""
    smil_path = tmp_path / "chapter01.smil"
    chapter_data = {
        "spine_item_id": "chapter01",
        "timeline": [
            {"element_id": "mo_s_9999", "start_ms": 0, "end_ms": 1000},
        ],
    }

    with pytest.raises(SmilGenerationError, match="Timeline element ID 'mo_s_9999' does not exist"):
        generate_chapter_smil(
            chapter=chapter_data,
            smil_path=smil_path,
            xhtml_path=minimal_xhtml,
            audio_rel_path="audio/chapter01.mp3",
            validate_xhtml_ids=True,
        )


def test_copy_chapter_audio(tmp_path, dummy_audio):
    """Test copying audio file into target directory."""
    target_dir = tmp_path / "EPUB" / "audio"
    copied = copy_chapter_audio(dummy_audio, target_dir)

    assert copied.is_file()
    assert copied.parent == target_dir
    assert copied.name == "chapter01.mp3"
    assert copied.read_bytes() == b"dummy audio content"

    # Missing audio file raises FileNotFoundError
    with pytest.raises(FileNotFoundError):
        copy_chapter_audio(tmp_path / "nonexistent.mp3", target_dir)


def test_per_smil_duration_equals_last_clip_end(minimal_xhtml, tmp_path):
    """Test AC 5: Per-SMIL duration is returned and equals the last clipEnd."""
    smil_path = tmp_path / "chapter01.smil"
    chapter_data = {
        "spine_item_id": "chapter01",
        "timeline": [
            {"element_id": "mo_s_0001", "start_ms": 120, "end_ms": 2340},
            {"element_id": "mo_s_0002", "start_ms": 2360, "end_ms": 4120},
        ],
    }

    meta = generate_chapter_smil(
        chapter=chapter_data,
        smil_path=smil_path,
        xhtml_path=minimal_xhtml,
        audio_rel_path="audio/chapter01.mp3",
    )

    last_clip_end_str = "4.120s"
    last_clip_end_float = 4.120
    last_clip_end_ms = 4120

    # AC 5 asserts
    assert meta.duration == last_clip_end_str
    assert meta.duration == last_clip_end_float
    assert meta.duration_clock == last_clip_end_str
    assert meta.duration_s == last_clip_end_float
    assert meta.duration_ms == last_clip_end_ms
    assert meta.par_count == 2
    assert meta.chapter_id == "chapter01"


def test_relative_paths_across_nested_directories(tmp_path):
    """Test relative path calculations when SMIL, XHTML, and audio are in subfolders."""
    content_dir = tmp_path / "OEBPS"
    xhtml_dir = content_dir / "text"
    smil_dir = content_dir / "smil"
    audio_dir = content_dir / "audio"

    xhtml_dir.mkdir(parents=True)
    smil_dir.mkdir(parents=True)
    audio_dir.mkdir(parents=True)

    xhtml_file = xhtml_dir / "ch01.xhtml"
    xhtml_file.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
        '<p><span id="s1">Hello</span></p>'
        '</body></html>',
        encoding="utf-8",
    )

    audio_file = audio_dir / "ch01.mp3"
    audio_file.write_bytes(b"data")

    smil_file = smil_dir / "ch01.smil"
    chapter_data = {
        "spine_item_id": "ch01",
        "timeline": [{"element_id": "s1", "start_ms": 0, "end_ms": 1500}],
    }

    meta = generate_chapter_smil(
        chapter=chapter_data,
        smil_path=smil_file,
        xhtml_path=xhtml_file,
        audio_rel_path="../audio/ch01.mp3",
    )

    doc = etree.parse(str(smil_file))
    seq = doc.xpath("//smil:seq", namespaces={"smil": SMIL_NS})[0]
    assert seq.get(f"{{{EPUB_NS}}}textref") == "../text/ch01.xhtml"

    text = doc.xpath("//smil:text", namespaces={"smil": SMIL_NS})[0]
    assert text.get("src") == "../text/ch01.xhtml#s1"

    audio = doc.xpath("//smil:audio", namespaces={"smil": SMIL_NS})[0]
    assert audio.get("src") == "../audio/ch01.mp3"


def test_end_to_end_smil_generation_on_fixtures(tmp_path):
    """End-to-end integration test on real unpacked book.epub, alignment.sample.json, and audio fixtures."""
    work_dir = tmp_path / "unpacked_epub"
    parser.unpack(SAMPLE_EPUB_PATH, work_dir)

    # Inject span IDs first
    alignment = load_alignment(SAMPLE_ALIGNMENT_PATH)
    inject_alignment_spans(work_dir, alignment)

    # Generate SMIL playlists with fixture audio from BOOK_PARTS_DIR
    smil_results = generate_smil_playlists(
        work_dir=work_dir,
        alignment=alignment,
        audio_source=BOOK_PARTS_DIR,
        validate_xhtml_ids=True,
    )

    assert "chapter01" in smil_results
    assert "chapter02" in smil_results

    content_dir = work_dir / "EPUB"
    audio_dir = content_dir / "audio"
    assert audio_dir.is_dir()

    # Verify Chapter 1
    ch1 = smil_results["chapter01"]
    assert ch1.smil_path.is_file()
    assert ch1.smil_path.name == "chapter01.smil"
    assert ch1.duration_clock == "23.732s"
    assert ch1.duration == 23.732
    assert ch1.par_count == 8

    # AC 4: Every <audio src> points to a file that exists in the folder
    ch1_doc = etree.parse(str(ch1.smil_path))
    ch1_audios = ch1_doc.xpath("//smil:audio", namespaces={"smil": SMIL_NS})
    for aud in ch1_audios:
        rel_src = aud.get("src")
        target = ch1.smil_path.parent / rel_src
        assert target.is_file(), f"Audio src '{rel_src}' not found at {target}"

    # AC 3: Every <text src> fragment points to an ID that exists in the XHTML
    ch1_xhtml_doc = etree.parse(str(content_dir / "chapter01.xhtml"))
    ch1_xhtml_ids = set(ch1_xhtml_doc.xpath("//@id"))
    ch1_texts = ch1_doc.xpath("//smil:text", namespaces={"smil": SMIL_NS})
    for t in ch1_texts:
        frag_id = t.get("src").split("#")[1]
        assert frag_id in ch1_xhtml_ids

    # Verify Chapter 2
    ch2 = smil_results["chapter02"]
    assert ch2.smil_path.is_file()
    assert ch2.smil_path.name == "chapter02.smil"
    assert ch2.duration_clock == "21.338s"
    assert ch2.duration == 21.338
    assert ch2.par_count == 5

    ch2_doc = etree.parse(str(ch2.smil_path))
    ch2_audios = ch2_doc.xpath("//smil:audio", namespaces={"smil": SMIL_NS})
    for aud in ch2_audios:
        rel_src = aud.get("src")
        target = ch2.smil_path.parent / rel_src
        assert target.is_file(), f"Audio src '{rel_src}' not found at {target}"

    ch2_xhtml_doc = etree.parse(str(content_dir / "chapter02.xhtml"))
    ch2_xhtml_ids = set(ch2_xhtml_doc.xpath("//@id"))
    ch2_texts = ch2_doc.xpath("//smil:text", namespaces={"smil": SMIL_NS})
    for t in ch2_texts:
        frag_id = t.get("src").split("#")[1]
        assert frag_id in ch2_xhtml_ids

    # Verify audio files exist in EPUB/audio/
    assert (audio_dir / "part_0.m4b").is_file()
    assert (audio_dir / "part_1.m4b").is_file()


def test_cli_generate_smil_subcommand(tmp_path):
    """Test running the CLI generate-smil subcommand."""
    work_dir = tmp_path / "cli_unpacked"
    parser.unpack(SAMPLE_EPUB_PATH, work_dir)
    inject_alignment_spans(work_dir, SAMPLE_ALIGNMENT_PATH)

    ret = cli.main([
        "generate-smil",
        str(work_dir),
        str(SAMPLE_ALIGNMENT_PATH),
        "--audio",
        str(BOOK_PARTS_DIR),
    ])
    assert ret == 0

    assert (work_dir / "EPUB" / "chapter01.smil").is_file()
    assert (work_dir / "EPUB" / "chapter02.smil").is_file()
    assert (work_dir / "EPUB" / "audio" / "part_0.m4b").is_file()


def test_cli_generate_smil_missing_directory_errors(tmp_path):
    """Test CLI error handling for missing directories and files."""
    with pytest.raises(SystemExit):
        cli.main(["generate-smil", str(tmp_path / "missing_dir"), str(SAMPLE_ALIGNMENT_PATH)])

    with pytest.raises(SystemExit):
        cli.main(["generate-smil", str(tmp_path), str(tmp_path / "missing_align.json")])


def test_continuous_smil_bridges_sentence_gaps(minimal_xhtml, tmp_path):
    """Test that continuous=True bridges inter-sentence pauses and starts at 0.000s."""
    smil_path = tmp_path / "continuous.smil"
    chapter_data = {
        "spine_item_id": "chapter01",
        "xhtml_filename": "chapter01.xhtml",
        "audio_filename": "chapter01.mp3",
        "timeline": [
            {"element_id": "mo_s_0001", "start_ms": 1200, "end_ms": 3500},
            {"element_id": "mo_s_0002", "start_ms": 5000, "end_ms": 8200},
        ],
    }

    generate_chapter_smil(
        chapter=chapter_data,
        smil_path=smil_path,
        xhtml_path=minimal_xhtml,
        audio_rel_path="audio/chapter01.mp3",
        continuous=True,
    )

    doc = etree.parse(str(smil_path))
    audios = doc.xpath("//smil:audio", namespaces={"smil": SMIL_NS})
    assert len(audios) == 2

    # First sentence starts at 0.000s (covers chapter intro)
    assert audios[0].get("clipBegin") == "0.000s"
    # First sentence ends where second sentence begins (5.000s, covering 3.5s-5.0s pause)
    assert audios[0].get("clipEnd") == "5.000s"

    # Second sentence starts exactly at 5.000s
    assert audios[1].get("clipBegin") == "5.000s"
    assert audios[1].get("clipEnd") == "8.200s"

