# XHTML Span ID Injection for EPUB 3 Media Overlays

## Overview

EPUB 3 Media Overlays synchronize audio narration with text by having SMIL documents target elements in XHTML documents by their XML `id` attribute. In the SMIL playlist:

```xml
<par id="par_0001">
  <text src="chapter01.xhtml#mo_s_0001"/>
  <audio src="audio/chapter01.mp3" clipBegin="0.031s" clipEnd="2.014s"/>
</par>
```

To enable reading systems (Apple Books, Thorium, Readium, Kobo) to highlight the currently spoken sentence, each aligned sentence in the original XHTML must be wrapped in a `<span id="mo_s_xxxx">...</span>` element.

The module `echopage.packager` implements this transformation with strict guarantees:
1. **100% Text Invariant**: Visible text (`''.join(root.itertext())`) is completely unaltered.
2. **Strict ID Uniqueness**: Every `element_id` in `alignment.json` appears **exactly once** as an `id` in the XHTML.
3. **XML Validity**: Output preserves the XML declaration, XHTML namespace (`http://www.w3.org/1999/xhtml`), and DOCTYPE (`<!DOCTYPE html>`).
4. **Collision Protection**: Pre-existing IDs in source XHTML are preserved, and collisions with `mo_s_*` IDs are detected and prevented.
5. **Inline Tag Support**: Sentences containing or crossing inline tags (`<em>`, `<a>`, `<b>`) are handled safely without invalid XML tree nesting.

---

## Inline Tag Splitting Strategy

### The Challenge

In XML and XHTML, elements form a strict hierarchy. A sentence extracted by the tokenizer (`echopage.parser`) may start in a parent block's text, cross into an inline element, and continue after the inline element:

```html
<p>
  I put forth my <em>full speed</em>. Mr. Fox witnessed it.
</p>
```

In this sentence:
- Part 1 (`"I put forth my "`) is in `p.text`.
- Part 2 (`"full speed"`) is inside `em.text`.
- Part 3 (`"."`) is in `em.tail`.

Creating a single `<span id="...">` that opens outside `<em>` and closes inside `<em>` would produce malformed XML (`<span>...<em>...</span>...</em>`).

### The Solution: Text Fragment Slicing

We adopt the **fragment-wrapping approach**:
- The block element's text is decomposed into a list of contiguous text segments:
  - `(node, "text", text_str)`: text directly inside `node` before any child element.
  - `(node, "tail", text_str)`: text immediately following `node` within `node.getparent()`.
- Each sentence's character range `[char_start, char_end]` is mapped against each overlapping segment.
- **First Span Carries Main ID**: The very first text fragment belonging to the sentence is wrapped in `<span id="mo_s_xxxx">...</span>`.
- **Continuation Fragments Omit ID**: Subsequent fragments within the same sentence are wrapped in `<span>...</span>` (omitting the `id` attribute, or carrying an optional CSS class).

```html
<p>
  <span id="mo_s_0003">"I have never yet been beaten," said he, "when I put forth my </span>
  <em><span>full speed</span></em>
  <span>.</span> 
  <span id="mo_s_0004">Mr. Fox can witness my victories."</span>
</p>
```

This guarantees:
1. **Valid XML Nesting**: Every span is an inline element strictly enclosed within its respective parent.
2. **Zero ID Duplication**: `id="mo_s_0003"` appears exactly once in the entire document.
3. **Text Fidelity**: All spaces and punctuation between and inside tags are preserved character-for-character.

---

## Reverse-Order DOM Mutation

When inserting new elements into an `lxml.etree` node using `.insert(index, child)`:
- Inserting into early child indices shifts the indices of subsequent siblings.
- Modifying a parent's `.text` before `.tail` can cause index drift.

To prevent this, `echopage.packager` applies replacements in **reverse order of segments**:
1. Tails of deep descendants are modified first.
2. Descendant texts are modified next.
3. Parent tails and texts are modified last.

Because earlier sibling indices and parent pointers remain untouched throughout prior steps, every element insertion resolves to its exact intended position without pointer invalidation.

---

## ID Collision Detection

Source XHTML documents often already contain IDs on chapters, sections, or figures (e.g. `<section id="ch01">`).

### Invariants:
1. **Preservation**: All valid source IDs (like `ch01`, `heading1`) are preserved untouched.
2. **Collision Rejection**: Before modifying any document, `check_id_collisions` scans all `//@id` in the document:
   - If an existing ID matches any target `element_id` in `alignment.json`, `IdCollisionError` is raised.
   - If an existing ID starts with the reserved prefix `mo_s_`, `IdCollisionError` is raised.

---

## Python API

### 1. `inject_alignment_spans`
Batch helper that processes all chapters in an unpacked EPUB work directory:

```python
from echopage.packager import inject_alignment_spans

# Injects spans into all chapters in-place in work_dir
results = inject_alignment_spans(
    work_dir="./work_dir",
    alignment="./work_dir/alignment.json",
    in_place=True,
)
# Returns dict: {"chapter01": Path(".../chapter01.xhtml"), ...}
```

### 2. `inject_spans_into_xhtml`
Low-level single-document injector:

```python
from echopage.packager import inject_spans_into_xhtml

doc = inject_spans_into_xhtml(
    xhtml_source="chapter01.xhtml",
    timeline=chapter_timeline,
    out_path="chapter01_modified.xhtml",
)
```

### 3. `collect_text_segments`
Traverse element tree returning `[(node, "text" | "tail", text_str)]`:

```python
from echopage.packager import collect_text_segments

segments = collect_text_segments(block_elem)
```

---

## CLI Usage

The EchoPage CLI includes the `inject-spans` subcommand for direct terminal execution:

```bash
# Inject span IDs into an unpacked EPUB directory
echopage inject-spans ./my_books/.unpacked ./my_books/alignment.json
```
