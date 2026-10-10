# 16 - Automatic Chapter Mapping & Auto-Skip

## Background
Real-world books rarely have a pristine 1:1 match between EPUB spine items and audiobook chapter cuts. EPUBs almost always contain non-narrated front-matter (e.g. half-title, copyright, table of contents, dramatis personae, epigraph) and back-matter (e.g. timeline, author biography, appendix, advertisements). 

Currently, EchoPage raises an `AlignmentMismatchError` when chapter counts differ, requiring users to manually inspect XHTML files and pass explicit spine IDs via `--skip-spine id002,id004,...` (as seen in *Horus Rising*, which has 30 spine items for 25 audio parts).

An automated mapping mechanism should intelligently align audio tracks to the correct story chapters and auto-skip non-narrated pages.

---

## What to do

1. **EPUB Chapter Title & Heading Extraction:**
   - Extract a meaningful title for each EPUB chapter using a prioritized fallback:
     1. EPUB Navigation document (`nav.xhtml`) or NCX (`toc.ncx`) label matching the spine `href`.
     2. Document `<title>` tag inside `<head>`.
     3. First prominent heading (`<h1>`, `<h2>`, `<h3>`, or `<p class="title|chapter|head">`).
     4. First non-empty text sentence as last-resort fallback.

2. **Title Normalization & Matching:**
   - Normalize both EPUB titles and audio unit titles for robust comparison:
     - Case-folding and strip surrounding punctuation.
     - Word-to-number and Roman numeral conversion (e.g. `"Chapter One"`, `"Chapter 1"`, `"Chapter I"` $\rightarrow$ `"chapter 1"`).
     - Ordinal and part prefix standardization (e.g. `"Part One"`, `"Part 1"`).

3. **Heuristic Front-Matter / Back-Matter Detection:**
   - Identify well-known non-narrated sections by keyword pattern matching:
     - Front matter: `Contents`, `Table of Contents`, `TOC`, `Dramatis Personae`, `Copyright`, `Title Page`, `Dedication`, `Epigraph`, `Also by`, `Books by`.
     - Back matter: `Timeline`, `Appendix`, `About the Author`, `Colophon`, `Glossary`, `Notes`, `Advertisements`.
   - Inspect OPF `<guide>` and `<landmarks>` elements (`type="toc"`, `type="copyright"`, `type="cover"`).

4. **Monotonic Subsequence Alignment Algorithm:**
   - When EPUB chapters count ($M$) exceeds audio units ($N$):
     - Use dynamic programming / longest common subsequence (LCS) alignment to find the optimal monotonic sequence of $N$ chapters that best matches the $N$ audio units.
     - Preserve strict document order: if Audio Chapter 2 maps to EPUB Chapter 8, Audio Chapter 3 must map to an EPUB chapter $> 8$.
     - Detect unmatched audio (e.g. `"Opening Credits"`, `"Closing Credits"`) and map them to appropriate title pages or exclude gracefully.

5. **CLI Integration & Diagnostics (`--auto-map`):**
   - Add `--auto-map` flag to `echopage build` (enabled by default when chapter count mismatch occurs, or as an explicit opt-in flag).
   - In `--dry-run`, clearly display the auto-detected mapping along with the list of auto-skipped chapters and reasons (e.g. `Skipped 'CONTENTS' (id004): detected front-matter TOC`).
   - If manual `--skip-spine` or explicit mapping is provided, respect user configuration over auto-matching.

---

## Acceptance Criteria
- [x] **Title Extraction:** EPUB chapter titles are accurately extracted from `nav.xhtml`/NCX, `<title>`, or headings for each spine item.
- [x] **Title Normalization:** Normalizer recognizes chapter numbering equivalences (`"One"`, `"Chapter 1"`, `"Chapter I"`, `"Part One"`).
- [x] **Known Section Filtering:** Standard non-narrated sections (`Contents`, `Dramatis Personae`, `Timeline`, `Copyright`) are identified.
- [x] **Monotonic Subsequence Matching:** Alignment preserves document order and finds the optimal matching sequence when EPUB chapter count exceeds audio unit count.
- [x] **Real-Book Verification:** Running `echopage build --dry-run --auto-map` on *Horus Rising* (30 spine chapters vs 25 audio units) automatically matches all 25 chapters without needing manual `--skip-spine`.
- [x] **Diagnostic Dry-Run Display:** `--dry-run` clearly prints which chapters were matched and which chapters were auto-skipped with reasons.
- [x] **Precedence:** Manual `--skip-spine` or `--map` overrides automatic mapping.
- [x] **Test Suite:** Unit tests for title extraction, normalization, subsequence alignment, and CLI integration pass with 100% success rate.
