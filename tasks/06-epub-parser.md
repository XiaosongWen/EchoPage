# 06 - EPUB Parser & Sentence Tokenizer

## Background
An EPUB is a zip. `META-INF/container.xml` points to the OPF. The OPF `<spine>` lists chapters in reading order, and each chapter is an XHTML file.

## What to do
1. `unpack(epub_path, work_dir)`: extract the zip. Reject path traversal entries (`../`).
2. `read_package(work_dir)`: read `container.xml`, find the OPF path, and parse the manifest and spine. Return an ordered list of `{id, href, media_type}` for XHTML items.
3. `extract_sentences(xhtml_path)`:
   - Parse with `lxml`.
   - Walk block elements (`p`, `h1-h6`, `li`, `blockquote`...). Skip `script`, `style`, `nav`.
   - Split each block's text into sentences with `nltk.sent_tokenize` (or spaCy).
   - Return `[{element_id_placeholder, text, block_xpath, char_start, char_end}]`. Keep the character offsets into the original text so task 10 can wrap them.
4. Handle inline tags (`<em>`, `<a>`): text is concatenated for tokenizing, and offsets still map back to the DOM.
5. Skip empty blocks and whitespace-only text.

## Acceptance Criteria
- [ ] The fixture EPUB unpacks and its spine order matches the OPF.
- [ ] Sentences from a paragraph with `<em>` inside come out as whole sentences.
- [ ] Offsets map back: `original_text[char_start:char_end] == sentence text` for every sentence.
- [ ] A zip with a `../evil` entry is rejected.
- [ ] Tests cover abbreviations ("Mr. Smith went.") and quotes.
