# 10 - Packager: Inject Span IDs into XHTML

## Background
SMIL points at elements by ID, so each aligned sentence must be wrapped in `<span id="mo_s_0001">...</span>` inside the original XHTML.

## What to do
1. For each chapter in `alignment.json`, load its XHTML with `lxml` (keep it XML-valid, keep the namespace and the doctype).
2. Using `block_xpath`, `char_start` and `char_end`, wrap the sentence text in a span.
3. Handle sentences that cross inline tags (`<em>`, `<a>`): wrap each text fragment separately, or split into several spans. Pick one approach and document it. The first span carries the main ID.
4. Don't change any other markup, attributes or text. Never alter the visible text.
5. Write the modified XHTML back in place in the work directory.

## Acceptance Criteria
- [x] Every `element_id` in the alignment appears exactly once as an `id` in its XHTML.
- [x] The text content of each chapter is identical before and after (compare `''.join(root.itertext())` ignoring the added spans).
- [x] Output is well-formed XML and parses without error.
- [x] A test covers a sentence containing an `<em>` tag.
- [x] Existing IDs in the source XHTML are preserved, and a collision with `mo_s_*` is detected.
