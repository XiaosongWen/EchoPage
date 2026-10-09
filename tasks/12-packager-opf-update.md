# 12 - Packager: Update the OPF Manifest

## Background
The OPF (`package.opf`) tells readers which files exist and which SMIL belongs to which chapter. Without these entries a reader ignores the overlays.

## What to do
1. Make sure `<package version="3.0">`. Upgrade from 2.0 if needed (EPUB 2 sources may have an NCX only; keep it and add a `nav` document if one is missing).
2. Register each SMIL: `<item id="smil_ch01" href="chapter01.smil" media-type="application/smil+xml"/>`.
3. Register each audio file with the correct `media-type` (`audio/mpeg` for mp3, `audio/mp4` for m4a/m4b).
4. Add `media-overlay="smil_ch01"` to the matching XHTML manifest item.
5. Add metadata:
   - `<meta property="media:duration" refines="#smil_ch01">HH:MM:SS.mmm</meta>` for each SMIL.
   - Total `<meta property="media:duration">` equal to the sum of all SMIL durations.
   - `<meta property="media:active-class">-epub-media-overlay-active</meta>`.
6. Compute durations (don't hardcode the PRD example values) and format them as `HH:MM:SS.mmm`.
7. Add the active class to the book CSS, e.g. `.-epub-media-overlay-active { background: #ffe58a; }`.

## Acceptance Criteria
- [ ] Every SMIL and audio file in the folder is in the manifest, and every manifest `href` exists.
- [ ] Each overlaid XHTML item has `media-overlay` pointing at a valid SMIL ID.
- [ ] Total duration equals the sum of the per-SMIL durations.
- [ ] Duration formatting test: `3723456 ms` becomes `01:02:03.456`.
- [ ] The original metadata (title, author, identifier) is unchanged.
