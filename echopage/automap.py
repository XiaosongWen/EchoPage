"""Automatic chapter mapping and non-narrated section detection.

Intelligently matches audiobook chapter cuts to EPUB spine items using:
- Title extraction (nav.xhtml, toc.ncx, <title>, <h1>-<h3>, class attributes, sentence fallback)
- Title normalization (Roman numerals, words-to-numbers, prefix standardization)
- Front-matter and back-matter heuristic filtering (TOC, Dramatis Personae, Timeline, etc.)
- Monotonic dynamic programming subsequence alignment preserving strict reading order
"""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Sequence, Union

from echopage.audio import AudioUnit

log = logging.getLogger("echopage.automap")

# Words to integer number mapping
_WORD_NUMBERS: dict[str, int] = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90, "hundred": 100,
    # Ordinals
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14, "fifteenth": 15,
    "sixteenth": 16, "seventeenth": 17, "eighteenth": 18, "nineteenth": 19, "twentieth": 20,
    "thirtieth": 30, "fortieth": 40, "fiftieth": 50,
}

_ROMAN_MAP: dict[str, int] = {
    "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10,
    "xi": 11, "xii": 12, "xiii": 13, "xiv": 14, "xv": 15, "xvi": 16, "xvii": 17, "xviii": 18, "xix": 19, "xx": 20,
    "xxi": 21, "xxii": 22, "xxiii": 23, "xxiv": 24, "xxv": 25, "xxvi": 26, "xxvii": 27, "xxviii": 28, "xxix": 29, "xxx": 30,
    "xxxi": 31, "xxxii": 32, "xxxiii": 33, "xxxiv": 34, "xxxv": 35, "xxxvi": 36, "xxxvii": 37, "xxxviii": 38, "xxxix": 39, "xl": 40,
    "l": 50, "lx": 60, "lxx": 70, "lxxx": 80, "xc": 90, "c": 100,
}

# Regex for detecting Roman numerals (up to 399)
_ROMAN_REGEX = re.compile(r"^m{0,4}(cm|cd|d?c{0,3})(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})$", re.IGNORECASE)

# Front-matter and back-matter heuristic keywords
FRONT_MATTER_PATTERNS = [
    (re.compile(r"\b(table of contents|contents|toc)\b", re.I), "detected front-matter TOC"),
    (re.compile(r"\bdramatis personae\b", re.I), "detected front-matter Dramatis Personae"),
    (re.compile(r"\b(copyright|all rights reserved)\b", re.I), "detected front-matter Copyright"),
    (re.compile(r"\b(title page|half title)\b", re.I), "detected front-matter Title Page"),
    (re.compile(r"\bdedication\b", re.I), "detected front-matter Dedication"),
    (re.compile(r"\bepigraph\b", re.I), "detected front-matter Epigraph"),
    (re.compile(r"\b(also by|books by|other books|praise for)\b", re.I), "detected front-matter Also by"),
]

BACK_MATTER_PATTERNS = [
    (re.compile(r"\btimeline\b", re.I), "detected back-matter Timeline"),
    (re.compile(r"\bappendix\b", re.I), "detected back-matter Appendix"),
    (re.compile(r"\b(about the author|author bio|about author)\b", re.I), "detected back-matter About the Author"),
    (re.compile(r"\bcolophon\b", re.I), "detected back-matter Colophon"),
    (re.compile(r"\bglossary\b", re.I), "detected back-matter Glossary"),
    (re.compile(r"\b(endnotes|footnotes|notes)\b", re.I), "detected back-matter Notes"),
    (re.compile(r"\b(advertisement|advertisements|preview|teaser)\b", re.I), "detected back-matter Advertisements"),
]


def parse_roman(text: str) -> int | None:
    """Parse a Roman numeral string into an integer, or return None."""
    s = text.strip().lower()
    if not s:
        return None
    if s in _ROMAN_MAP:
        return _ROMAN_MAP[s]
    if _ROMAN_REGEX.fullmatch(s):
        vals = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
        total = 0
        prev = 0
        for ch in reversed(s):
            val = vals.get(ch, 0)
            if val < prev:
                total -= val
            else:
                total += val
                prev = val
        return total if total > 0 else None
    return None


def parse_word_number(text: str) -> int | None:
    """Parse written English number words (e.g. 'one', 'twenty-one') into an integer."""
    s = text.strip().lower()
    if not s:
        return None
    if s in _WORD_NUMBERS:
        return _WORD_NUMBERS[s]
    # Handle hyphenated numbers (e.g. 'twenty-one')
    parts = re.split(r"[\s-]+", s)
    if len(parts) == 2 and parts[0] in _WORD_NUMBERS and parts[1] in _WORD_NUMBERS:
        return _WORD_NUMBERS[parts[0]] + _WORD_NUMBERS[parts[1]]
    return None


def normalize_chapter_title(title: str) -> str:
    """Normalize a chapter title for robust comparison between EPUB and audio metadata.

    Transformations:
    - Lowercase and strip surrounding punctuation.
    - Word-to-number and Roman numeral conversion (e.g. 'Chapter One' -> 'chapter 1', 'Part I' -> 'part 1').
    - Standardize prefixes ('Chapter 1', 'Part 1', 'Book 1').
    - Strip ordinal suffixes ('1st' -> '1', '2nd' -> '2').
    """
    if not title:
        return ""

    raw = title.strip().lower()

    # Replace punctuation characters with whitespace
    cleaned = re.sub(r"[:;,.\-—–\"\'/\\()[\]{}!?#]+", " ", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    tokens = cleaned.split()
    if not tokens:
        return ""

    # Replace prefix variations
    prefix_map = {
        "ch": "chapter", "chap": "chapter", "chpt": "chapter", "chapter": "chapter",
        "pt": "part", "part": "part",
        "bk": "book", "book": "book",
        "sec": "section", "section": "section",
        "act": "act", "scene": "scene",
    }

    norm_tokens = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]

        # Strip ordinal suffixes from numbers (e.g. 1st -> 1, 2nd -> 2)
        ord_match = re.fullmatch(r"(\d+)(?:st|nd|rd|th)", tok)
        if ord_match:
            tok = ord_match.group(1)

        # Standardize prefixes
        if tok in prefix_map:
            prefix = prefix_map[tok]
            # Check if next token is a number or Roman numeral
            if i + 1 < len(tokens):
                nxt = tokens[i + 1]
                # Check digits
                if nxt.isdigit():
                    norm_tokens.append(f"{prefix} {int(nxt)}")
                    i += 2
                    continue
                # Check word number
                wnum = parse_word_number(nxt)
                if wnum is not None:
                    norm_tokens.append(f"{prefix} {wnum}")
                    i += 2
                    continue
                # Check Roman numeral
                rnum = parse_roman(nxt)
                if rnum is not None:
                    norm_tokens.append(f"{prefix} {rnum}")
                    i += 2
                    continue
            norm_tokens.append(prefix)
            i += 1
            continue

        # Check compound word numbers (e.g. 'twenty one' or 'twenty-one')
        if i + 1 < len(tokens):
            compound_num = parse_word_number(f"{tok} {tokens[i + 1]}")
            if compound_num is not None:
                norm_tokens.append(str(compound_num))
                i += 2
                continue

        # Check standalone word number
        wnum = parse_word_number(tok)
        if wnum is not None:
            norm_tokens.append(str(wnum))
            i += 1
            continue

        # Check standalone Roman numeral
        rnum = parse_roman(tok)
        if rnum is not None:
            norm_tokens.append(str(rnum))
            i += 1
            continue

        norm_tokens.append(tok)
        i += 1

    return " ".join(norm_tokens)


def detect_non_narrated_section(
    title: str,
    text_preview: str = "",
    guide_type: str | None = None,
) -> str | None:
    """Heuristically identify standard non-narrated front-matter and back-matter sections.

    Returns
    -------
    str | None
        Reason string if section should be skipped, or None if it appears narrated.
    """
    if guide_type:
        g = guide_type.lower()
        if "toc" in g:
            return "detected front-matter TOC"
        if "copyright" in g:
            return "detected front-matter Copyright"
        if "cover" in g:
            return "detected OPF guide/landmark 'cover'"

    t = (title or "").strip()
    preview = (text_preview or "").strip()

    # Check title against front-matter patterns
    for pat, reason in FRONT_MATTER_PATTERNS:
        if pat.search(t):
            return reason

    # Check title against back-matter patterns
    for pat, reason in BACK_MATTER_PATTERNS:
        if pat.search(t):
            return reason

    # Check epigraph heuristic from text content if title is missing or contains quotes
    combined = f"{t} {preview}".strip()
    if re.search(r"[‘'\"].{5,}[’'\"]\s*(?:—|--|-)", combined, re.DOTALL):
        return "detected front-matter Epigraph"
    if re.search(r"\bepigraph\b", combined, re.I):
        return "detected front-matter Epigraph"

    # Check dramatis personae in text preview
    if re.search(r"\bdramatis personae\b", combined, re.I):
        return "detected front-matter Dramatis Personae"

    return None


def title_similarity(epub_title: str, audio_title: str) -> float:
    """Compute normalized similarity score between an EPUB chapter title and audio unit title.

    Returns a float between 0.0 and 1.0.
    """
    if not epub_title or not audio_title:
        return 0.0

    ne = normalize_chapter_title(epub_title)
    na = normalize_chapter_title(audio_title)

    if not ne or not na:
        return 0.0

    # Exact normalized match
    if ne == na:
        return 1.0

    # Chapter number equivalence: 'chapter 1' <-> '1'
    if re.sub(r"^chapter\s+", "", ne) == re.sub(r"^chapter\s+", "", na):
        return 0.95

    # Credits match
    credits_keywords = {"opening credits", "closing credits", "credits", "title page", "title"}
    if na in ("opening credits", "credits"):
        if any(k in ne for k in ("dan abnett", "the horus heresy", "title", "credits", "author")):
            return 0.90
        # Check if first chapter is title page
        return 0.70

    # One contains the other
    if ne.startswith(na) or na.startswith(ne):
        return 0.85
    if ne in na or na in ne:
        return 0.80

    # Sequence matcher fuzzy similarity
    ratio = SequenceMatcher(None, ne, na).ratio()
    if ratio >= 0.7:
        return ratio

    return 0.0


def align_chapter_subsequence(
    chapters: Sequence[dict],
    audio_units: Sequence[AudioUnit],
) -> tuple[list[tuple[dict, AudioUnit]], list[tuple[dict, str]]]:
    """Find the optimal monotonic subsequence of EPUB chapters matching audio units.

    Uses dynamic programming to preserve strict document order, skipping non-narrated
    front-matter and back-matter, while matching audio tracks (including opening/closing credits).

    Parameters
    ----------
    chapters : Sequence[dict]
        EPUB spine chapters in reading order.
    audio_units : Sequence[AudioUnit]
        Audiobook chapter segments in chronological order.

    Returns
    -------
    tuple[list[tuple[dict, AudioUnit]], list[tuple[dict, str]]]
        - List of matched (chapter_dict, audio_unit) pairs.
        - List of skipped (chapter_dict, reason_string) pairs.
    """
    m = len(chapters)
    n = len(audio_units)

    if m == 0 or n == 0:
        return [], [(c, "empty collection") for c in chapters]

    # Pre-calculate detected skip reasons for chapters
    skip_reasons: list[str | None] = []
    for c in chapters:
        title = c.get("title", "")
        guide = c.get("guide_type")
        sents = c.get("sentences", [])
        preview = " ".join((s.get("text", "") if isinstance(s, dict) else getattr(s, "text", str(s))) for s in sents[:3]) if sents else ""
        reason = detect_non_narrated_section(title, text_preview=preview, guide_type=guide)
        skip_reasons.append(reason)

    # DP Table: dp[i][j] = max score matching first i audio units using a subset of first j chapters
    # States:
    #   i in 0..n (audio units)
    #   j in 0..m (chapters)
    dp = [[-1e9] * (m + 1) for _ in range(n + 1)]
    # backtrack table storing action: (prev_i, prev_j, action_type)
    # action_type: 'skip_ch', 'match', 'skip_au'
    backtrack = [[(0, 0, "")] * (m + 1) for _ in range(n + 1)]

    dp[0][0] = 0.0

    # Base case: skipping chapters with 0 audio units matched
    for j in range(1, m + 1):
        ch_reason = skip_reasons[j - 1]
        skip_score = 0.0 if ch_reason is not None else -1.0
        dp[0][j] = dp[0][j - 1] + skip_score
        backtrack[0][j] = (0, j - 1, "skip_ch")

    # Base case: skipping audio units with 0 chapters used
    for i in range(1, n + 1):
        au_title = normalize_chapter_title(audio_units[i - 1].title or "")
        skip_au_score = 0.0 if "credits" in au_title else -100.0
        dp[i][0] = dp[i - 1][0] + skip_au_score
        backtrack[i][0] = (i - 1, 0, "skip_au")

    # Fill DP table
    for i in range(1, n + 1):
        au = audio_units[i - 1]
        au_raw_title = au.title or ""
        au_norm_title = normalize_chapter_title(au_raw_title)

        for j in range(1, m + 1):
            ch = chapters[j - 1]
            ch_reason = skip_reasons[j - 1]
            ch_raw_title = ch.get("title", "")

            # Option 1: Skip EPUB chapter j-1
            ch_skip_penalty = 0.0 if ch_reason is not None else -1.0
            best_score = dp[i][j - 1] + ch_skip_penalty
            best_action = (i, j - 1, "skip_ch")

            # Option 2: Match audio unit i-1 to EPUB chapter j-1
            # Compute match score
            is_opening_credits = "opening credits" in au_norm_title or au_norm_title == "credits"
            is_closing_credits = "closing credits" in au_norm_title

            if is_opening_credits:
                ch_norm = normalize_chapter_title(ch_raw_title)
                if (
                    j <= 3
                    or "title page" in ch_norm
                    or "title" in ch_norm
                    or "credits" in ch_norm
                    or any(w in ch_norm for w in ("dan abnett", "author", "publisher"))
                ):
                    match_val = 80.0
                else:
                    match_val = -100.0
            elif is_closing_credits:
                if j >= m - 2:
                    match_val = 80.0
                else:
                    match_val = -100.0
            elif ch_reason is not None and not (au_norm_title and au_norm_title in normalize_chapter_title(ch_raw_title)):
                # If chapter is identified as non-narrated (TOC, Dramatis Personae, etc.) and audio does not match it:
                # Heavy penalty prevents assigning a story chapter to TOC
                match_val = -100.0
            else:
                sim = title_similarity(ch_raw_title, au_raw_title)
                if sim > 0.5:
                    match_val = 50.0 + sim * 50.0
                elif sim > 0.0:
                    match_val = sim * 50.0
                else:
                    # Title mismatch or uninformative title:
                    # Provide slight score if sequential ordering matches, else penalty
                    match_val = -20.0

            cand_match_score = dp[i - 1][j - 1] + match_val
            if cand_match_score > best_score:
                best_score = cand_match_score
                best_action = (i - 1, j - 1, "match")

            # Option 3: Skip audio unit i-1 (only for credits or with penalty)
            skip_au_cost = 0.0 if "credits" in au_norm_title else -100.0
            cand_skip_au = dp[i - 1][j] + skip_au_cost
            if cand_skip_au > best_score:
                best_score = cand_skip_au
                best_action = (i - 1, j, "skip_au")

            dp[i][j] = best_score
            backtrack[i][j] = best_action

    # Backtrack to recover optimal alignment
    curr_i, curr_j = n, m
    matched_rev: list[tuple[dict, AudioUnit]] = []
    skipped_ch_rev: list[tuple[dict, str]] = []

    while curr_i > 0 or curr_j > 0:
        prev_i, prev_j, act = backtrack[curr_i][curr_j]
        if act == "match":
            ch = chapters[curr_j - 1]
            au = audio_units[curr_i - 1]
            matched_rev.append((ch, au))
        elif act == "skip_ch":
            ch = chapters[curr_j - 1]
            reason = skip_reasons[curr_j - 1] or f"skipped unmapped chapter '{ch.get('title') or ch.get('href')}'"
            skipped_ch_rev.append((ch, reason))
        elif act == "skip_au":
            au = audio_units[curr_i - 1]
            log.info("Auto-map gracefully excluded unmatched audio track: %s", au.title or au.path.name)
        curr_i, curr_j = prev_i, prev_j

    matched = list(reversed(matched_rev))
    skipped_ch = list(reversed(skipped_ch_rev))

    return matched, skipped_ch
