# System Architecture & Technical Specification: EchoPage (EPUB 3 Media Overlays Generator)

## 1. Project Goal & Scope

**EchoPage** is an automated pipeline application designed to compile a synchronized **EPUB 3 with Media Overlays** from an existing EPUB book and raw audiobook files.

The system assumes the user already possesses the source `.epub` file and the audiobook files (which may still have Audible AAX/AAXC DRM). The tool's responsibility is scoped strictly to three operational phases:

1. **DRM Decryption**: Strip AAX/AAXC container DRM into standard, unencrypted audio (`.m4b` / `.mp3`).
2. **Forced Alignment**: Calculate acoustic timestamps aligning EPUB text nodes to audio timeline intervals at the sentence and word level.
3. **EPUB 3 Packaging**: Inject SMIL 3.0 files, inject structural IDs into XHTML text nodes, update the OPF package manifest, and package the final compliant EPUB 3 archive.

---

## 2. End-to-End Pipeline Architecture

```
[Encrypted/Raw Audio] ──► [Phase 1: DRM Stripping] ──► [Decrypted Audio (M4B/MP3)]
                                                              │
[Source EPUB]         ──► [EPUB Unpacker/Parser]   ──► [Clean XHTML + Spine]
                                                              │
                                                              ▼
                                                   [Phase 2: Forced Alignment]
                                                   (WhisperX / wav2vec2 / ASR)
                                                              │
                                                              ▼
                                                   [Alignment Map (JSON)]
                                                              │
                                                              ▼
                                                   [Phase 3: EPUB 3 Packager]
                                                   - Inject span IDs into XHTML
                                                   - Synthesize SMIL files
                                                   - Update package.opf
                                                   - Deflate & Validate
                                                              │
                                                              ▼
                                                   [Final Synchronized EPUB 3]

```

---

## 3. Detailed Component Specifications

### Phase 1: DRM Stripping Module (`decryptor`)

#### Responsibilities

* Detect container format (`.aax`, `.aaxc`, or already decrypted `.m4b`/`.mp3`).
* If encrypted, strip DRM using account activation bytes or voucher keys via `ffmpeg`.
* Normalize multi-part audio or preserve chapter markers to map audio files to corresponding EPUB spine chapters.

#### Technical Requirements

* **Input**:
* `audio_files`: List of paths to audio files (`.aax`, `.aaxc`, `.m4b`, `.mp3`).
* `activation_bytes`: 8-character hex string (for `.aax`), or `audible_key` + `audible_iv` (for `.aaxc`).


* **Processing Logic**:
* Check file header:
* If already DRM-free (`.m4b`/`.mp3`), bypass conversion.
* If `.aax`: Invoke FFmpeg with `-activation_bytes`:
```bash
ffmpeg -activation_bytes <AUTH_CODE> -i input.aax -vn -c:a copy output.m4b

```


* If `.aaxc`: Invoke FFmpeg using `-audible_key` and `-audible_iv`.




* **Output**: Clean, unencrypted audio stream (`.m4b` or `.mp3` segmented by chapter if required).

---

### Phase 2: Forced Alignment Module (`aligner`)

#### Responsibilities

* Extract textual contents from the EPUB spine items (`.xhtml`/`.html`), stripping boilerplate CSS/scripts while retaining DOM tree hierarchy.
* Break text into trackable units (sentences/clauses) and prepare phonetic transcripts.
* Match audio segments with text segments using an acoustic forced alignment engine (`WhisperX` kernel using Wav2Vec2 alignment).

#### Technical Requirements

* **Audio Preprocessing**: Downsample audio to 16kHz mono WAV chunks in memory or scratch space for optimal acoustic feature extraction.
* **Text Normalization**:
* Parse HTML using `lxml` or `BeautifulSoup4`.
* Tokenize sentences using deterministic rules (`spacy` or `nltk.sent_tokenize`).
* Strip HTML tags for the alignment engine while preserving character offsets back to the original DOM structure.


* **Alignment Engine**:
* Run `WhisperX` alignment mode:
1. Base model generates acoustic phoneme boundaries.
2. Forced alignment maps each known sentence and word to exact millisecond intervals `[start, end]`.




* **Intermediate Data Contract (`alignment.json`)**:
```json
[
  {
    "spine_item_id": "chapter01",
    "xhtml_filename": "chapter01.xhtml",
    "audio_filename": "chapter01.mp3",
    "timeline": [
      {
        "element_id": "mo_s_0001",
        "text": "It was the best of times.",
        "start_ms": 120,
        "end_ms": 2340
      },
      {
        "element_id": "mo_s_0002",
        "text": "It was the worst of times.",
        "start_ms": 2360,
        "end_ms": 4120
      }
    ]
  }
]

```



---

### Phase 3: EPUB 3 Media Overlays Packager (`packager`)

#### Responsibilities

Transform the original EPUB container into a compliant EPUB 3 package equipped with Media Overlays.

#### Operations

1. **DOM ID Mutation (XHTML)**:
* For every entry in `alignment.json`, locate the corresponding text in the XHTML document.
* Wrap the sentence or block in an inline tag containing the ID:
```html
<p>
  <span id="mo_s_0001">It was the best of times.</span>
  <span id="mo_s_0002">It was the worst of times.</span>
</p>

```




2. **SMIL 3.0 Document Synthesis**:
* For each chapter XHTML with accompanying audio, generate a corresponding `.smil` file (e.g., `chapter01.smil`).
* Format:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<smil xmlns="http://www.w3.org/ns/SMIL" xmlns:epub="http://www.idpf.org/2007/ops" version="3.0">
  <body>
    <seq id="seq_ch01" epub:textref="chapter01.xhtml">
      <par id="par_0001">
        <text src="chapter01.xhtml#mo_s_0001"/>
        <audio src="audio/chapter01.mp3" clipBegin="0.120s" clipEnd="2.340s"/>
      </par>
      <par id="par_0002">
        <text src="chapter01.xhtml#mo_s_0002"/>
        <audio src="audio/chapter01.mp3" clipBegin="2.360s" clipEnd="4.120s"/>
      </par>
    </seq>
  </body>
</smil>

```




3. **OPF Package Manifest Updates (`content.opf` / `package.opf`)**:
* In `<metadata>`:
* Add active duration: `<meta property="media:duration">01:24:30.000</meta>`.
* Add per-SMIL duration: `<meta property="media:duration" refines="#smil_ch01">00:15:20.000</meta>`.
* Add active class: `<meta property="media:active-class">-epub-media-overlay-active</meta>`.


* In `<manifest>`:
* Update text items to link their overlays:
```xml
<item id="ch01" href="chapter01.xhtml" media-type="application/xhtml+xml" media-overlay="smil_ch01"/>

```


* Register each SMIL file:
```xml
<item id="smil_ch01" href="chapter01.smil" media-type="application/smil+xml"/>

```


* Register each audio asset:
```xml
<item id="audio_ch01" href="audio/chapter01.mp3" media-type="audio/mpeg"/>

```






4. **Container Packaging & Compression**:
* Repackage directory into `.zip` structure with standard EPUB compression rules:
* The first file in the archive must be uncompressed `mimetype` (`application/epub+zip`).
* All subsequent files (`META-INF/`, `OEBPS/`, SMIL, audio, XHTML) packed using standard Deflate compression.


* Rename `.zip` extension to `.epub`.



---

## 4. CLI Interface Specification

The coding agent should implement this workflow under a single unified CLI utility:

```bash
# Basic invocation
EchoPage build \
  --epub ./sources/book.epub \
  --audio ./sources/chapter1.aax ./sources/chapter2.aax \
  --activation-bytes 1a2b3c4d \
  --output ./dist/book_synchronized.epub

# Optional flags
  --granularity sentence|word       # Defaults to sentence
  --model-size small|medium|large-v3 # Whisper model size for alignment
  --device cpu|cuda|mps              # Hardware acceleration
  --work-dir ./tmp/build_cache       # Working directory for intermediate files

```

---

## 5. Coding Agent Implementation Tasks

### Module 1: `EchoPage/decryptor.py`

* [ ] Implement format detector for `.aax`, `.aaxc`, `.m4b`, `.mp3`.
* [ ] Build FFmpeg command runner for decryption using `activation_bytes` or voucher keys.
* [ ] Ensure non-destructive conversion with stream copying (`-c:a copy`) when possible.

### Module 2: `EchoPage/parser.py`

* [ ] Extract source EPUB into working directory.
* [ ] Parse `package.opf` to identify the correct reading order (spine items) and text assets.
* [ ] Clean and tokenize HTML paragraph nodes into sentences while preserving original markup tags.

### Module 3: `EchoPage/aligner.py`

* [ ] Integrate `WhisperX` forced alignment pipeline.
* [ ] Correlate parsed text nodes against audio segments.
* [ ] Generate structured alignment array containing element IDs, start timestamps, and end timestamps.

### Module 4: `EchoPage/packager.py`

* [ ] Inject `id` attributes into the source XHTML DOM tree for aligned spans.
* [ ] Generate valid SMIL 3.0 XML documents linking spans to audio clips.
* [ ] Update `package.opf` with `<meta property="media:duration">`, manifest references, and `media-overlay` attributes.
* [ ] Pack final folder into a valid `.epub` (ensuring correct `mimetype` header storage).