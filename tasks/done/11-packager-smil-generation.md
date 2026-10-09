# 11 - Packager: SMIL Generation

## Background
A SMIL file is the "playlist" for one chapter. Each `<par>` pairs a text element with an audio clip range.

## What to do
1. For each chapter, generate `<chapter>.smil` in the format shown in the PRD (section 3, Phase 3, step 2).
2. Convert ms to seconds with 3 decimals: `2340` becomes `2.340s`.
3. `<text src="chapter01.xhtml#mo_s_0001"/>`: use the correct relative path from the SMIL file to the XHTML.
4. `<audio src="audio/chapter01.mp3" .../>`: use the correct relative path to the audio asset.
5. Add `epub:type="chapter"` to the `<seq>` (missing from the PRD example) and set a unique `id` on every `<par>`.
6. Return the total duration of each SMIL (last `clipEnd`), which task 12 needs.
7. Copy the audio files into the EPUB folder (`OEBPS/audio/` or `EPUB/audio/`).

## Acceptance Criteria
- [x] The output SMIL parses as XML and uses the `http://www.w3.org/ns/SMIL` namespace.
- [x] Clip times are formatted as `N.NNNs` and are in order.
- [x] Every `<text src>` fragment points to an ID that exists in the XHTML (test checks this).
- [x] Every `<audio src>` points to a file that exists in the folder.
- [x] Per-SMIL duration is returned and equals the last `clipEnd`.
