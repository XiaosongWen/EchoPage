"""Unit and integration tests for EPUB OPF package manifest updates (Task 12)."""

import shutil
import tempfile
from pathlib import Path

import pytest
from lxml import etree

from echopage import cli, packager
from echopage.packager import (
    OPF_NAMESPACE,
    OpfUpdateError,
    SmilDuration,
    SmilMetadata,
    find_opf_path,
    format_clock_hms,
    inject_active_class_css,
    synthesize_nav_xhtml,
    update_opf_manifest,
)


@pytest.fixture
def temp_unpacked_epub(tmp_path: Path) -> Path:
    """Create a temporary unpacked EPUB fixture directory."""
    fixture_dir = Path("tests/fixtures/.echopage_unpack_book")
    target = tmp_path / "book_unpacked"
    shutil.copytree(fixture_dir, target)
    return target


def test_find_opf_path_with_container(temp_unpacked_epub: Path):
    """Test locating package OPF path via META-INF/container.xml."""
    opf = find_opf_path(temp_unpacked_epub)
    assert opf.is_file()
    assert opf.name == "package.opf"
    assert opf.parent.name == "EPUB"


def test_find_opf_path_fallback(tmp_path: Path):
    """Test locating package OPF via directory search when container.xml is absent."""
    content_dir = tmp_path / "OEBPS"
    content_dir.mkdir(parents=True)
    opf_file = content_dir / "content.opf"
    opf_file.write_text("<package/>", encoding="utf-8")

    found = find_opf_path(tmp_path)
    assert found == opf_file


def test_find_opf_path_missing_raises(tmp_path: Path):
    """Test that missing OPF raises OpfUpdateError."""
    with pytest.raises(OpfUpdateError, match="Could not locate OPF"):
        find_opf_path(tmp_path)


def test_duration_formatting_ms_to_hms():
    """Test Acceptance Criterion: 3723456 ms becomes 01:02:03.456."""
    assert format_clock_hms(3723456) == "01:02:03.456"
    assert format_clock_hms(0) == "00:00:00.000"
    assert format_clock_hms(500) == "00:00:00.500"
    assert format_clock_hms(60000) == "00:01:00.000"
    assert format_clock_hms(3600000) == "01:00:00.000"


def test_epub2_upgrade_to_epub3(tmp_path: Path):
    """Test upgrading an EPUB 2.0 OPF to 3.0 while synthesizing nav.xhtml and preserving NCX."""
    epub_dir = tmp_path / "epub2_book"
    meta_inf = epub_dir / "META-INF"
    meta_inf.mkdir(parents=True)
    content_dir = epub_dir / "OPS"
    content_dir.mkdir(parents=True)

    container_xml = meta_inf / "container.xml"
    container_xml.write_text(
        '<?xml version="1.0"?>\n'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
        '  <rootfiles>\n'
        '    <rootfile full-path="OPS/content.opf" media-type="application/oebps-package+xml"/>\n'
        '  </rootfiles>\n'
        '</container>',
        encoding="utf-8",
    )

    # Minimal EPUB 2 OPF
    opf_file = content_dir / "content.opf"
    opf_file.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="pub-id">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        '    <dc:identifier id="pub-id">urn:uuid:test-epub2</dc:identifier>\n'
        '    <dc:title>EPUB 2 Title</dc:title>\n'
        '    <dc:creator>Test Author</dc:creator>\n'
        '  </metadata>\n'
        '  <manifest>\n'
        '    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>\n'
        '    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>\n'
        '  </manifest>\n'
        '  <spine toc="ncx">\n'
        '    <itemref idref="ch1"/>\n'
        '  </spine>\n'
        '</package>',
        encoding="utf-8",
    )

    (content_dir / "toc.ncx").write_text("<ncx/>", encoding="utf-8")
    (content_dir / "ch1.xhtml").write_text("<html/>", encoding="utf-8")

    update_opf_manifest(epub_dir, smil_metadata=[])

    tree = etree.parse(str(opf_file))
    root = tree.getroot()

    # 1. Version upgraded to 3.0
    assert root.get("version") == "3.0"

    # 2. NCX item is kept
    ncx_items = root.xpath("//*[local-name()='manifest']/*[local-name()='item'][@id='ncx']")
    assert len(ncx_items) == 1

    # 3. Nav document synthesized and added to manifest with properties="nav"
    nav_items = root.xpath("//*[local-name()='manifest']/*[local-name()='item'][contains(@properties, 'nav')]")
    assert len(nav_items) == 1
    assert (content_dir / "nav.xhtml").is_file()

    # 4. Original metadata preserved
    titles = root.xpath("//*[local-name()='metadata']/*[local-name()='title']")
    assert titles[0].text == "EPUB 2 Title"
    creators = root.xpath("//*[local-name()='metadata']/*[local-name()='creator']")
    assert creators[0].text == "Test Author"


def test_smil_registration_and_media_type(temp_unpacked_epub: Path):
    """Test registering SMIL playlist items with application/smil+xml."""
    epub_content = temp_unpacked_epub / "EPUB"
    smil_path = epub_content / "chapter01.smil"
    smil_path.write_text("<smil/>", encoding="utf-8")

    audio_path = epub_content / "audio" / "part_0.mp3"
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    audio_path.write_text("mp3-data", encoding="utf-8")

    meta = SmilMetadata(
        smil_path=smil_path,
        chapter_id="chapter01",
        duration=SmilDuration(15.5),
        duration_ms=15500,
        duration_s=15.5,
        duration_clock="15.500s",
        audio_src="audio/part_0.mp3",
        audio_file_path=audio_path,
        par_count=4,
        xhtml_path=epub_content / "chapter01.xhtml",
    )

    update_opf_manifest(temp_unpacked_epub, smil_metadata={"chapter01": meta})

    opf_path = epub_content / "package.opf"
    tree = etree.parse(str(opf_path))
    root = tree.getroot()

    # SMIL item registered
    smil_items = root.xpath("//*[local-name()='manifest']/*[local-name()='item'][@href='chapter01.smil']")
    assert len(smil_items) == 1
    assert smil_items[0].get("media-type") == "application/smil+xml"
    assert smil_items[0].get("id") == "smil_chapter01"


def test_audio_registration_and_mime_types(temp_unpacked_epub: Path):
    """Test registering mp3 (audio/mpeg) and m4b (audio/mp4) assets."""
    epub_content = temp_unpacked_epub / "EPUB"
    audio_dir = epub_content / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    mp3_file = audio_dir / "sample.mp3"
    mp3_file.write_text("mp3", encoding="utf-8")
    m4b_file = audio_dir / "sample.m4b"
    m4b_file.write_text("m4b", encoding="utf-8")

    update_opf_manifest(temp_unpacked_epub, smil_metadata=[], audio_files=[mp3_file, m4b_file])

    opf_path = epub_content / "package.opf"
    tree = etree.parse(str(opf_path))
    root = tree.getroot()

    mp3_items = root.xpath("//*[local-name()='manifest']/*[local-name()='item'][@href='audio/sample.mp3']")
    assert len(mp3_items) == 1
    assert mp3_items[0].get("media-type") == "audio/mpeg"

    m4b_items = root.xpath("//*[local-name()='manifest']/*[local-name()='item'][@href='audio/sample.m4b']")
    assert len(m4b_items) == 1
    assert m4b_items[0].get("media-type") == "audio/mp4"


def test_xhtml_media_overlay_attribute(temp_unpacked_epub: Path):
    """Test adding media-overlay='smil_ch' attribute to corresponding XHTML item."""
    epub_content = temp_unpacked_epub / "EPUB"
    smil_path = epub_content / "chapter01.smil"
    smil_path.write_text("<smil/>", encoding="utf-8")

    meta = SmilMetadata(
        smil_path=smil_path,
        chapter_id="chapter01",
        duration=SmilDuration(10.0),
        duration_ms=10000,
        duration_s=10.0,
        duration_clock="10.000s",
        audio_src="audio/part_0.mp3",
        xhtml_path=epub_content / "chapter01.xhtml",
    )

    update_opf_manifest(temp_unpacked_epub, smil_metadata={"chapter01": meta})

    opf_path = epub_content / "package.opf"
    tree = etree.parse(str(opf_path))
    root = tree.getroot()

    ch1_items = root.xpath("//*[local-name()='manifest']/*[local-name()='item'][@id='chapter01']")
    assert len(ch1_items) == 1
    assert ch1_items[0].get("media-overlay") == "smil_chapter01"


def test_duration_metadata_calculation(temp_unpacked_epub: Path):
    """Test total duration equals sum of SMIL durations, and per-SMIL durations refines."""
    epub_content = temp_unpacked_epub / "EPUB"
    smil1 = epub_content / "chapter01.smil"
    smil1.write_text("<smil/>", encoding="utf-8")
    smil2 = epub_content / "chapter02.smil"
    smil2.write_text("<smil/>", encoding="utf-8")

    meta1 = SmilMetadata(
        smil_path=smil1,
        chapter_id="chapter01",
        duration=SmilDuration(10.5),
        duration_ms=10500,
        duration_s=10.5,
        duration_clock="10.500s",
        audio_src="audio/part_0.mp3",
    )
    meta2 = SmilMetadata(
        smil_path=smil2,
        chapter_id="chapter02",
        duration=SmilDuration(25.25),
        duration_ms=25250,
        duration_s=25.25,
        duration_clock="25.250s",
        audio_src="audio/part_1.mp3",
    )

    update_opf_manifest(temp_unpacked_epub, smil_metadata=[meta1, meta2])

    opf_path = epub_content / "package.opf"
    tree = etree.parse(str(opf_path))
    root = tree.getroot()

    # Per-SMIL duration metadata
    meta_dur1 = root.xpath("//*[local-name()='metadata']/*[local-name()='meta'][@property='media:duration'][@refines='#smil_chapter01']")
    assert len(meta_dur1) == 1
    assert meta_dur1[0].text == "00:00:10.500"

    meta_dur2 = root.xpath("//*[local-name()='metadata']/*[local-name()='meta'][@property='media:duration'][@refines='#smil_chapter02']")
    assert len(meta_dur2) == 1
    assert meta_dur2[0].text == "00:00:25.250"

    # Total duration metadata = 10500 + 25250 = 35750 ms = 00:00:35.750
    total_dur = root.xpath("//*[local-name()='metadata']/*[local-name()='meta'][@property='media:duration'][not(@refines)]")
    assert len(total_dur) == 1
    assert total_dur[0].text == "00:00:35.750"


def test_active_class_metadata_and_css_injection(temp_unpacked_epub: Path):
    """Test media:active-class metadata and CSS injection."""
    css_file = temp_unpacked_epub / "EPUB" / "styles.css"
    assert "-epub-media-overlay-active" not in css_file.read_text(encoding="utf-8")

    update_opf_manifest(temp_unpacked_epub, smil_metadata=[])

    opf_path = temp_unpacked_epub / "EPUB" / "package.opf"
    tree = etree.parse(str(opf_path))
    root = tree.getroot()

    active_meta = root.xpath("//*[local-name()='metadata']/*[local-name()='meta'][@property='media:active-class']")
    assert len(active_meta) == 1
    assert active_meta[0].text == "-epub-media-overlay-active"

    # CSS modified
    css_content = css_file.read_text(encoding="utf-8")
    assert ".-epub-media-overlay-active" in css_content
    assert "background-color: #ffe58a;" in css_content


def test_original_metadata_is_unchanged(temp_unpacked_epub: Path):
    """Test original metadata (title, author, identifier, language) remains intact."""
    opf_path = temp_unpacked_epub / "EPUB" / "package.opf"
    tree_before = etree.parse(str(opf_path))
    title_before = tree_before.xpath("//*[local-name()='title']")[0].text
    creator_before = tree_before.xpath("//*[local-name()='creator']")[0].text
    identifier_before = tree_before.xpath("//*[local-name()='identifier']")[0].text

    update_opf_manifest(temp_unpacked_epub, smil_metadata=[])

    tree_after = etree.parse(str(opf_path))
    assert tree_after.xpath("//*[local-name()='title']")[0].text == title_before
    assert tree_after.xpath("//*[local-name()='creator']")[0].text == creator_before
    assert tree_after.xpath("//*[local-name()='identifier']")[0].text == identifier_before


def test_every_smil_and_audio_in_folder_in_manifest(temp_unpacked_epub: Path):
    """Test Acceptance Criterion: Every SMIL and audio file in the folder is in the manifest, and every manifest href exists."""
    epub_content = temp_unpacked_epub / "EPUB"
    audio_dir = epub_content / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    # Create 2 SMIL files and 2 audio files
    s1 = epub_content / "chapter01.smil"
    s1.write_text("<smil/>", encoding="utf-8")
    s2 = epub_content / "chapter02.smil"
    s2.write_text("<smil/>", encoding="utf-8")

    a1 = audio_dir / "part_0.mp3"
    a1.write_text("mp3-data", encoding="utf-8")
    a2 = audio_dir / "part_1.m4b"
    a2.write_text("m4b-data", encoding="utf-8")

    update_opf_manifest(temp_unpacked_epub)

    opf_path = epub_content / "package.opf"
    tree = etree.parse(str(opf_path))
    root = tree.getroot()

    manifest_hrefs = {item.get("href") for item in root.xpath("//*[local-name()='manifest']/*[local-name()='item']")}

    # SMIL and audio files are in manifest
    assert "chapter01.smil" in manifest_hrefs
    assert "chapter02.smil" in manifest_hrefs
    assert "audio/part_0.mp3" in manifest_hrefs
    assert "audio/part_1.m4b" in manifest_hrefs

    # Every manifest href points to an existing file
    for href in manifest_hrefs:
        target = epub_content / href
        assert target.exists(), f"Manifest href '{href}' does not exist on disk"


def test_end_to_end_package_pipeline(temp_unpacked_epub: Path):
    """Test full package() call with XHTML injection, SMIL generation, and OPF manifest update."""
    alignment_file = Path("tests/fixtures/alignment.sample.json")
    audio_parts = sorted(Path("tests/fixtures/book_parts").glob("*.m4b"))

    out_file = temp_unpacked_epub / "output.epub"
    res = packager.package(
        epub=Path("tests/fixtures/book.epub"),
        audio=audio_parts,
        alignment=alignment_file,
        output=out_file,
        work_dir=temp_unpacked_epub,
    )
    assert res == out_file

    # Verify OPF manifest updated
    opf_path = temp_unpacked_epub / "EPUB" / "package.opf"
    tree = etree.parse(str(opf_path))
    root = tree.getroot()

    # Check SMIL items
    smil_items = root.xpath("//*[local-name()='manifest']/*[local-name()='item'][@media-type='application/smil+xml']")
    assert len(smil_items) == 2

    # Check media-overlay attributes
    ch1 = root.xpath("//*[local-name()='manifest']/*[local-name()='item'][@id='chapter01']")[0]
    ch2 = root.xpath("//*[local-name()='manifest']/*[local-name()='item'][@id='chapter02']")[0]
    assert ch1.get("media-overlay") is not None
    assert ch2.get("media-overlay") is not None

    # Check duration metadata
    dur_meta = root.xpath("//*[local-name()='metadata']/*[local-name()='meta'][@property='media:duration']")
    assert len(dur_meta) == 3  # 2 per-smil + 1 total


def test_cli_update_opf(temp_unpacked_epub: Path, capsys: pytest.CaptureFixture):
    """Test CLI update-opf subcommand execution."""
    ret = cli.main(["update-opf", str(temp_unpacked_epub)])
    assert ret == 0
    captured = capsys.readouterr()
    assert "Updated OPF package manifest" in captured.out
