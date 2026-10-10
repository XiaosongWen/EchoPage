import json
import shutil
import subprocess
import zipfile
from pathlib import Path
from lxml import etree
import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_epub_fixture_structure():
    """Verify that the EPUB fixture complies with EPUB 3 container and package rules."""
    epub_path = FIXTURES_DIR / "book.epub"
    assert epub_path.exists(), f"Missing fixture EPUB: {epub_path}"

    with zipfile.ZipFile(epub_path, "r") as zf:
        infolist = zf.infolist()
        assert len(infolist) > 0, "EPUB zip archive is empty"

        # 1. First file must be 'mimetype', uncompressed (ZIP_STORED)
        first_entry = infolist[0]
        assert first_entry.filename == "mimetype", "First entry in EPUB must be 'mimetype'"
        assert first_entry.compress_type == zipfile.ZIP_STORED, "mimetype must be uncompressed (stored)"
        assert zf.read("mimetype") == b"application/epub+zip", "mimetype content must be application/epub+zip"

        # 2. META-INF/container.xml must exist and identify rootfile
        assert "META-INF/container.xml" in zf.namelist()
        container_xml = zf.read("META-INF/container.xml")
        container_doc = etree.fromstring(container_xml)
        rootfile_elem = container_doc.xpath(
            "//c:rootfile",
            namespaces={"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
        )
        assert len(rootfile_elem) > 0, "No rootfile found in container.xml"
        opf_path = rootfile_elem[0].get("full-path")
        assert opf_path in zf.namelist(), f"OPF file {opf_path} not found in zip"

        # 3. Read and validate package.opf
        opf_doc = etree.fromstring(zf.read(opf_path))
        opf_ns = {"opf": "http://www.idpf.org/2007/opf"}

        manifest_items = {
            item.get("id"): item.get("href")
            for item in opf_doc.xpath("//opf:manifest/opf:item", namespaces=opf_ns)
        }
        assert "chapter01" in manifest_items
        assert "chapter02" in manifest_items

        spine_items = [
            itemref.get("idref")
            for itemref in opf_doc.xpath("//opf:spine/opf:itemref", namespaces=opf_ns)
        ]
        assert spine_items == ["chapter01", "chapter02"], "Spine must order chapter01 before chapter02"

        # 4. Validate chapter content
        ch1_doc = etree.fromstring(zf.read(f"EPUB/{manifest_items['chapter01']}"))
        ch1_text = "".join(ch1_doc.itertext())
        assert "The Tortoise and the Hare" in ch1_text
        assert "Mr. Fox" in ch1_text
        assert "full speed" in ch1_text

        ch2_doc = etree.fromstring(zf.read(f"EPUB/{manifest_items['chapter02']}"))
        ch2_text = "".join(ch2_doc.itertext())
        assert "The North Wind and the Sun" in ch2_text


def test_audio_fixtures_exist():
    """Verify all required audio fixtures exist and are non-empty."""
    for filename in ["book.m4b", "book.mp3", "ch01.mp3", "ch02.mp3", "sample_16k.wav"]:
        filepath = FIXTURES_DIR / filename
        assert filepath.exists(), f"Missing audio fixture: {filename}"
        assert filepath.stat().st_size > 0, f"Empty audio fixture: {filename}"


@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe not installed")
def test_audio_m4b_chapters_and_metadata():
    """Verify book.m4b has valid 2-chapter metadata and proper audio properties."""
    m4b_path = FIXTURES_DIR / "book.m4b"
    res = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_chapters",
            "-show_entries", "format=duration:stream=codec_name,channels",
            "-of", "json",
            str(m4b_path)
        ],
        capture_output=True,
        text=True,
        check=True
    )
    data = json.loads(res.stdout)
    chapters = data.get("chapters", [])
    assert len(chapters) == 2, f"Expected 2 chapters, found {len(chapters)}"

    ch1 = chapters[0]
    ch2 = chapters[1]

    assert float(ch1["start_time"]) == 0.0
    assert float(ch1["end_time"]) > 20.0
    assert "Tortoise" in ch1.get("tags", {}).get("title", "")

    assert float(ch2["start_time"]) == float(ch1["end_time"])
    assert float(ch2["end_time"]) > float(ch2["start_time"])
    assert "North Wind" in ch2.get("tags", {}).get("title", "")

    total_duration = float(data["format"]["duration"])
    assert 30.0 <= total_duration <= 60.0, f"Duration {total_duration}s not in 30-60s range"


@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe not installed")
def test_sample_16k_wav_format():
    """Verify sample_16k.wav is mono 16kHz PCM WAV."""
    wav_path = FIXTURES_DIR / "sample_16k.wav"
    res = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=codec_name,sample_rate,channels",
            "-of", "json",
            str(wav_path)
        ],
        capture_output=True,
        text=True,
        check=True
    )
    data = json.loads(res.stdout)
    stream = data["streams"][0]

    assert stream["codec_name"] == "pcm_s16le"
    assert int(stream["sample_rate"]) == 16000
    assert int(stream["channels"]) == 1


def test_fixtures_readme():
    """Verify fixtures README.md exists and documents public domain provenance."""
    readme_path = FIXTURES_DIR / "README.md"
    assert readme_path.exists(), f"Missing {readme_path}"
    readme_content = readme_path.read_text(encoding="utf-8")
    assert "Public Domain" in readme_content
    assert "Aesop" in readme_content
