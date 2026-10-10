"""Tests for automatic chapter mapping, title normalization, section heuristics, and monotonic DP alignment."""

from __future__ import annotations

import tempfile
from pathlib import Path
from lxml import etree
import pytest

from echopage.audio import AudioUnit
from echopage.automap import (
    align_chapter_subsequence,
    detect_non_narrated_section,
    normalize_chapter_title,
    parse_roman,
    parse_word_number,
    title_similarity,
)
from echopage.parser import (
    Sentence,
    extract_chapter_title,
    extract_navigation_metadata,
    parse_epub,
)
from echopage import aligner, cli


# ---------------------------------------------------------------------------
# 1. Title Extraction Tests
# ---------------------------------------------------------------------------

def test_extract_chapter_title_priority_ncx_and_nav():
    """Verify that TOC label takes top priority over <title> and headings."""
    xhtml = """<?xml version="1.0" encoding="utf-8"?>
    <!DOCTYPE html>
    <html xmlns="http://www.w3.org/1999/xhtml">
      <head><title>Document Head Title</title></head>
      <body>
        <h1>Heading 1 Title</h1>
        <p>First paragraph sentence.</p>
      </body>
    </html>
    """
    # When toc_title is provided, it wins (priority 1)
    title = extract_chapter_title(xhtml, toc_title="TOC Label Title")
    assert title == "TOC Label Title"


def test_extract_chapter_title_fallback_to_head_title():
    """Verify fallback to <head><title> when no TOC title is provided."""
    xhtml = """<?xml version="1.0" encoding="utf-8"?>
    <html xmlns="http://www.w3.org/1999/xhtml">
      <head><title>Chapter I: In the Beginning</title></head>
      <body>
        <h1>Heading 1 Title</h1>
        <p>First paragraph text.</p>
      </body>
    </html>
    """
    title = extract_chapter_title(xhtml, toc_title=None)
    assert title == "Chapter I: In the Beginning"


def test_extract_chapter_title_fallback_to_heading():
    """Verify fallback to <h1>, <h2>, <h3> when head title is missing/generic."""
    xhtml = """<?xml version="1.0" encoding="utf-8"?>
    <html xmlns="http://www.w3.org/1999/xhtml">
      <head><title>Untitled</title></head>
      <body>
        <h2>Chapter 5: The Journey</h2>
        <p>First paragraph text.</p>
      </body>
    </html>
    """
    title = extract_chapter_title(xhtml, toc_title=None)
    assert title == "Chapter 5: The Journey"


def test_extract_chapter_title_fallback_to_class_paragraph():
    """Verify fallback to <p class="chapter-title"> or <div class="head">."""
    xhtml = """<?xml version="1.0" encoding="utf-8"?>
    <html xmlns="http://www.w3.org/1999/xhtml">
      <head></head>
      <body>
        <p class="chapter_title">PROLOGUE</p>
        <p>It was a dark and stormy night.</p>
      </body>
    </html>
    """
    title = extract_chapter_title(xhtml, toc_title=None)
    assert title == "PROLOGUE"


def test_extract_chapter_title_fallback_to_first_sentence():
    """Verify last-resort fallback to first non-empty text sentence."""
    xhtml = """<?xml version="1.0" encoding="utf-8"?>
    <html xmlns="http://www.w3.org/1999/xhtml">
      <head></head>
      <body>
        <p>Once upon a time in a faraway kingdom.</p>
        <p>Second sentence.</p>
      </body>
    </html>
    """
    sents = [Sentence({"text": "Once upon a time in a faraway kingdom."})]
    title = extract_chapter_title(xhtml, toc_title=None, sentences=sents)
    assert title == "Once upon a time in a faraway kingdom."


def test_extract_navigation_metadata_on_fixture_epub():
    """Verify navigation document extraction on book.epub."""
    fixture_epub = Path(__file__).parent / "fixtures" / "book.epub"
    with tempfile.TemporaryDirectory() as td:
        res = parse_epub(fixture_epub, work_dir=td)
        assert len(res["chapters"]) == 2
        ch1 = res["chapters"][0]
        ch2 = res["chapters"][1]

        # Titles extracted from nav.xhtml
        assert ch1["title"] == "Chapter 1: The Tortoise and the Hare"
        assert ch2["title"] == "Chapter 2: The North Wind and the Sun"


# ---------------------------------------------------------------------------
# 2. Title Normalization Tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("input_title,expected", [
    ("Chapter One", "chapter 1"),
    ("Chapter 1", "chapter 1"),
    ("Chapter I", "chapter 1"),
    ("CHAPTER 1", "chapter 1"),
    ("Ch. 1", "chapter 1"),
    ("Chap. 1", "chapter 1"),
    ("Part One", "part 1"),
    ("Part 1", "part 1"),
    ("Part I", "part 1"),
    ("One", "1"),
    ("Two", "2"),
    ("Three", "3"),
    ("Ten", "10"),
    ("Twenty-One", "21"),
    ("Chapter IV", "chapter 4"),
    ("Chapter IX", "chapter 9"),
    ("Chapter XIV", "chapter 14"),
    ("Part Three", "part 3"),
    ("1st Chapter", "1 chapter"),
    ("Opening Credits", "opening credits"),
    ("Closing Credits", "closing credits"),
    ("Chapter 1: The Tortoise and the Hare", "chapter 1 the tortoise and the hare"),
])
def test_normalize_chapter_title(input_title, expected):
    assert normalize_chapter_title(input_title) == expected


def test_parse_roman():
    assert parse_roman("i") == 1
    assert parse_roman("iv") == 4
    assert parse_roman("v") == 5
    assert parse_roman("ix") == 9
    assert parse_roman("x") == 10
    assert parse_roman("xiv") == 14
    assert parse_roman("xix") == 19
    assert parse_roman("xxv") == 25
    assert parse_roman("xxx") == 30
    assert parse_roman("invalid") is None


def test_parse_word_number():
    assert parse_word_number("one") == 1
    assert parse_word_number("twenty") == 20
    assert parse_word_number("twenty-one") == 21
    assert parse_word_number("first") == 1
    assert parse_word_number("second") == 2
    assert parse_word_number("unknown") is None


# ---------------------------------------------------------------------------
# 3. Known Section Filtering / Heuristics Tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("title,guide,expected_pattern", [
    ("Table of Contents", None, "front-matter TOC"),
    ("Contents", None, "front-matter TOC"),
    ("TOC", None, "front-matter TOC"),
    ("Dramatis Personae", None, "front-matter Dramatis Personae"),
    ("Copyright", None, "front-matter Copyright"),
    ("Title Page", None, "front-matter Title Page"),
    ("Dedication", None, "front-matter Dedication"),
    ("Epigraph", None, "front-matter Epigraph"),
    ("Also by the author", None, "front-matter Also by"),
    ("Timeline", None, "back-matter Timeline"),
    ("Appendix", None, "back-matter Appendix"),
    ("About the Author", None, "back-matter About the Author"),
    ("Colophon", None, "back-matter Colophon"),
    ("Glossary", None, "back-matter Glossary"),
    ("Notes", None, "back-matter Notes"),
    ("Advertisements", None, "back-matter Advertisements"),
    ("Cover", "cover", "cover"),
    ("Arbitrary", "toc", "front-matter TOC"),
])
def test_detect_non_narrated_section(title, guide, expected_pattern):
    reason = detect_non_narrated_section(title, guide_type=guide)
    assert reason is not None
    assert expected_pattern.lower() in reason.lower()


def test_detect_non_narrated_epigraph_from_content():
    text = "‘Myths grow like crystals, according to their own pattern.’ — Koestler"
    reason = detect_non_narrated_section("", text_preview=text)
    assert reason is not None
    assert "epigraph" in reason.lower()


def test_detect_narrated_story_chapter_not_skipped():
    reason = detect_non_narrated_section("Chapter 1: The Beginning", text_preview="The story begins here.")
    assert reason is None


# ---------------------------------------------------------------------------
# 4. Monotonic Subsequence DP Alignment Tests
# ---------------------------------------------------------------------------

def test_align_chapter_subsequence_preserves_monotonic_order():
    """Verify that DP alignment strictly preserves reading order."""
    chapters = [
        {"id": "c1", "title": "Contents", "sentences": [{"text": "Contents list"}]},
        {"id": "c2", "title": "Chapter 1", "sentences": [{"text": "Story 1"}]},
        {"id": "c3", "title": "Dramatis Personae", "sentences": [{"text": "Characters"}]},
        {"id": "c4", "title": "Chapter 2", "sentences": [{"text": "Story 2"}]},
        {"id": "c5", "title": "Timeline", "sentences": [{"text": "Dates"}]},
    ]
    audio_units = [
        AudioUnit(path=Path("ch1.mp3"), start_s=0.0, end_s=10.0, title="Chapter One"),
        AudioUnit(path=Path("ch2.mp3"), start_s=10.0, end_s=20.0, title="Chapter Two"),
    ]

    matched, skipped = align_chapter_subsequence(chapters, audio_units)

    assert len(matched) == 2
    assert matched[0][0]["id"] == "c2"
    assert matched[0][1].title == "Chapter One"
    assert matched[1][0]["id"] == "c4"
    assert matched[1][1].title == "Chapter Two"

    # Verify skipped chapters
    skipped_ids = [c["id"] for c, _ in skipped]
    assert skipped_ids == ["c1", "c3", "c5"]


def test_align_chapter_subsequence_credits_mapping():
    """Verify opening credits mapping to front title page."""
    chapters = [
        {"id": "c_title", "title": "Dan Abnett: Title Page", "sentences": [{"text": "The Horus Heresy"}]},
        {"id": "c_toc", "title": "CONTENTS", "sentences": [{"text": "Table of contents"}]},
        {"id": "c_part1", "title": "PART ONE", "sentences": [{"text": "Part one content"}]},
    ]
    audio_units = [
        AudioUnit(path=Path("track0.m4b"), start_s=0.0, end_s=30.0, title="Opening Credits"),
        AudioUnit(path=Path("track1.m4b"), start_s=30.0, end_s=60.0, title="Part One"),
    ]

    matched, skipped = align_chapter_subsequence(chapters, audio_units)

    assert len(matched) == 2
    assert matched[0][0]["id"] == "c_title"
    assert matched[1][0]["id"] == "c_part1"
    assert len(skipped) == 1
    assert skipped[0][0]["id"] == "c_toc"


def test_aligner_map_audio_units_auto_map():
    """Verify aligner.map_audio_units_to_chapters with auto_map=True."""
    chapters = [
        {"id": "c0", "title": "Contents", "sentences": [{"text": "TOC"}]},
        {"id": "c1", "title": "Chapter 1", "sentences": [{"text": "First chapter."}]},
    ]
    audio_units = [
        AudioUnit(path=Path("a1.mp3"), start_s=0.0, end_s=10.0, title="One"),
    ]

    pairs, skipped = aligner.map_audio_units_to_chapters(
        chapters,
        audio_units,
        auto_map=True,
        return_skipped=True,
    )

    assert len(pairs) == 1
    assert pairs[0][0]["id"] == "c1"
    assert len(skipped) == 1
    assert skipped[0][0]["id"] == "c0"


# ---------------------------------------------------------------------------
# 5. Real-Book Verification: Horus Rising
# ---------------------------------------------------------------------------

def test_horus_rising_real_book_auto_mapping():
    """Acceptance criterion: Horus Rising (30 spine chapters vs 25 audio units) matches all 25 chapters."""
    epub_path = Path("my_books/Horus Rising: The Horus Heresy.epub")
    audio_path = Path("my_books/Horus Rising: The Horus Heresy.m4b")

    if not epub_path.is_file() or not audio_path.is_file():
        pytest.skip("Horus Rising book files not present in workspace")

    with tempfile.TemporaryDirectory() as td:
        parsed = parse_epub(epub_path, work_dir=td)
        chapters = [c for c in parsed["chapters"] if c.get("sentences")]
        audio_units = aligner.prepare_audio_units([audio_path], work_dir=td)

        assert len(chapters) == 30
        assert len(audio_units) == 25

        matched, skipped = align_chapter_subsequence(chapters, audio_units)

        assert len(matched) == 25
        assert len(skipped) == 5

        # Verify matched pairs order
        assert matched[0][0]["id"] == "id002"
        assert matched[0][1].title == "Opening Credits"

        assert matched[1][0]["id"] == "id006"
        assert matched[1][1].title == "Part One"

        assert matched[2][0]["id"] == "id008"
        assert matched[2][1].title == "One"

        assert matched[-1][0]["id"] == "id030"
        assert matched[-1][1].title == "Four"

        # Verify skipped chapters
        skipped_ids = [c["id"] for c, _ in skipped]
        assert skipped_ids == ["id003", "id004", "id005", "id007", "id031"]


# ---------------------------------------------------------------------------
# 6. CLI Integration & Precedence Tests
# ---------------------------------------------------------------------------

def test_cli_build_dry_run_auto_map(capsys, tmp_path):
    """Acceptance criterion: Dry run prints planned matches and auto-skipped chapters."""
    epub_path = Path("my_books/Horus Rising: The Horus Heresy.epub")
    audio_path = Path("my_books/Horus Rising: The Horus Heresy.m4b")

    if not epub_path.is_file() or not audio_path.is_file():
        pytest.skip("Horus Rising book files not present")

    exit_code = cli.main([
        "build",
        "--epub", str(epub_path),
        "--audio", str(audio_path),
        "--output", str(tmp_path / "dummy.epub"),
        "--dry-run",
        "--auto-map",
        "--work-dir", str(tmp_path / "work"),
    ])
    assert exit_code == 0
    captured = capsys.readouterr().out

    assert "Dry run: planned chapter-to-audio mapping:" in captured
    assert "Chapter 'id002'" in captured
    assert "Audio 'Opening Credits'" in captured
    assert "Auto-skipped chapters (5):" in captured
    assert "Skipped 'CONTENTS' (id004): detected front-matter TOC" in captured
    assert "Skipped 'DRAMATIS PERSONAE' (id005): detected front-matter Dramatis Personae" in captured
    assert "Skipped 'TIMELINE' (id031): detected back-matter Timeline" in captured


def test_cli_build_precedence_skip_spine(capsys, tmp_path):
    """Acceptance criterion: Manual --skip-spine overrides auto-matching."""
    epub_path = Path("my_books/Horus Rising: The Horus Heresy.epub")
    audio_path = Path("my_books/Horus Rising: The Horus Heresy.m4b")

    if not epub_path.is_file() or not audio_path.is_file():
        pytest.skip("Horus Rising book files not present")

    exit_code = cli.main([
        "build",
        "--epub", str(epub_path),
        "--audio", str(audio_path),
        "--output", str(tmp_path / "dummy.epub"),
        "--dry-run",
        "--skip-spine", "id003,id004,id005,id007,id031",
        "--work-dir", str(tmp_path / "work"),
    ])
    assert exit_code == 0
    captured = capsys.readouterr().out

    assert "Dry run: planned chapter-to-audio mapping:" in captured
    # When manual skip-spine leaves exact 25 chapters, no auto-skipped list is printed
    assert "Auto-skipped chapters" not in captured


def test_cli_build_no_auto_map_raises_mismatch(capsys, tmp_path):
    """Verify that --no-auto-map raises AlignmentMismatchError when counts differ."""
    epub_path = Path("my_books/Horus Rising: The Horus Heresy.epub")
    audio_path = Path("my_books/Horus Rising: The Horus Heresy.m4b")

    if not epub_path.is_file() or not audio_path.is_file():
        pytest.skip("Horus Rising book files not present")

    exit_code = cli.main([
        "build",
        "--epub", str(epub_path),
        "--audio", str(audio_path),
        "--output", str(tmp_path / "dummy.epub"),
        "--dry-run",
        "--no-auto-map",
        "--work-dir", str(tmp_path / "work"),
    ])
    assert exit_code == 1
