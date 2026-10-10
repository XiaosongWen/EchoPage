# System Architecture & Technical Specification: EchoPage (EPUB 3 Media Overlays Generator)

## 1. Project Goal & Scope

**EchoPage** is an automated end-to-end pipeline application designed to compile synchronized **EPUB 3 with Media Overlays** from standard EPUB books (EPUB 2 or EPUB 3) and audiobooks (DRM-free `.m4b`/`.mp3` or Audible `.aax`/`.aaxc`).

The system assumes the user possesses the source `.epub` file and corresponding audiobook file(s). EchoPage manages the entire conversion workflow across four operational phases:

1. **Audio Preparation & DRM Decryption**: Strips AAX/AAXC container encryption via FFmpeg, probes M4B chapter boundaries, and splits/downsamples audio into 16kHz mono WAV scratch units for acoustic feature extraction.
2. **EPUB Parsing & Sentence Extraction**: Unpacks EPUB containers securely, parses the OPF spine and navigation documents (TOC/NCX), and deterministically tokenizes paragraph nodes into trackable sentence units while preserving original HTML markup.
3. **Auto-Mapping & Forced Alignment**: Uses heuristic algorithms to filter unvoiced front/back matter, matches chapters to audio tracks, and runs WhisperX + Wav2Vec2 alignment with automated hardware model selection (`auto`).
4. **EPUB 3 Media Overlays Packaging**: Injects `<span id="mo_s_XXXX">` elements into chapter XHTML, synthesizes SMIL 3.0 playlist files, upgrades metadata in `package.opf`, and packages a standard-compliant EPUB 3 zip container.

---

## 2. End-to-End Pipeline Architecture

```
[Raw Audio (.m4b/.mp3/.aax/.aaxc)]
       │
       ▼
[Phase 1: echopage.audio & decryptor]
 ├── Decrypt AAX / AAXC via FFmpeg
 ├── Probe metadata & chapter boundaries (ffprobe)
 └── Split / Resample scratch audio (16kHz mono WAV)
       │
       ├─────────────────────────────────────────┐
       ▼                                         ▼
[Phase 2: echopage.parser]             [Phase 3: echopage.automap]
 ├── Safe unpack (prevents Zip Slip)    ├── Filter unvoiced front/back matter
 ├── OPF spine & manifest parsing      ├── Fuzzy chapter-to-audio matching
 └── NLTK sentence tokenization         └── Resolve 1:1 chapter alignment pairs
       │                                         │
       └────────────────────┬────────────────────┘
                            ▼
              [Phase 3: echopage.aligner]
               ├── Hardware VRAM auto model sizing
               ├── WhisperX phoneme alignment
               └── Cache intermediate alignment.json
                            │
                            ▼
              [Phase 4: echopage.packager]
               ├── XHTML span injection: Inject DOM span IDs (<span id="mo_s_XXXX">)
               ├── SMIL synthesis: Synthesize SMIL 3.0 (<seq>, <par>, <audio>)
               ├── OPF manifest updates: Register overlays & active CSS in package.opf
               └── Container ZIP: Store mimetype uncompressed, Deflate package
                            │
                            ▼
              [Final Synchronized EPUB 3 Package]
```

---

## 3. Detailed Component Specifications

### 3.1 Audio Processing & DRM Stripping (`echopage.audio`, `echopage.decryptor`)

#### Responsibilities
* Format detection for `.aax`, `.aaxc`, `.m4b`, and `.mp3`.
* Non-destructive DRM removal using account `activation_bytes` (AAX) or `audible_key` + `audible_iv` (AAXC) via FFmpeg stream copying (`-c:a copy`).
* Chapter boundary probing via `ffprobe` JSON chapter markers.
* Multi-chapter audio splitting and scratch resampling to 16kHz mono WAV chunks.

#### Processing Flow
* If already DRM-free (`.m4b` / `.mp3`), skip decryption.
* If `.aax`: Invoke FFmpeg with `-activation_bytes`:
  ```bash
  ffmpeg -activation_bytes <HEX8> -i input.aax -vn -c:a copy output.m4b
  ```
* If `.aaxc`: Invoke FFmpeg using `-audible_key <HEX>` and `-audible_iv <HEX>`.
* Extract chapter timestamps and split multi-chapter files when necessary.

---

### 3.2 EPUB Parser & Text Extraction (`echopage.parser`)

#### Responsibilities
* Extract source EPUB into working directory with strict Zip Slip path traversal validation.
* Parse `META-INF/container.xml` to locate OPF package file.
* Read OPF manifest and spine to establish exact canonical reading order.
* Parse navigation metadata from EPUB 3 `nav.xhtml` and EPUB 2 `toc.ncx`.
* Clean and tokenize HTML paragraph nodes into sentences using NLTK `sent_tokenize` while preserving inline tags (`<em>`, `<strong>`, `<a>`, etc.) and character offsets.

---

### 3.3 Auto-Mapping & Forced Alignment (`echopage.automap`, `echopage.aligner`)

#### Responsibilities
* Solve chapter count discrepancies between EPUB spine and audiobook tracks.
* Filter unvoiced front matter (Cover, Title, Copyright, Dedication, TOC) and back matter (Glossary, Timeline, Appendix).
* Match chapter headings using normalized fuzzy string matching and duration heuristics.
* Compute acoustic forced alignment with WhisperX.

#### Hardware Model Selection
When `--model-size auto` is specified (default):
* Evaluates active CUDA device and free VRAM:
  * $\ge 7.0\text{ GB}$ VRAM: `large-v3` (Highest accuracy, ideal for fantasy/sci-fi terms)
  * $\ge 5.0\text{ GB}$ VRAM: `medium`
  * $< 5.0\text{ GB}$ or CPU/MPS fallback: `small` (Resource efficient)

#### Intermediate Data Contract (`alignment.json`)
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
        "end_ms": 2340,
        "confidence": 0.96
      },
      {
        "element_id": "mo_s_0002",
        "text": "It was the worst of times.",
        "start_ms": 2360,
        "end_ms": 4120,
        "confidence": 0.94
      }
    ]
  }
]
```

---

### 3.4 EPUB 3 Media Overlays Packager (`echopage.packager`)

#### Functional Architecture
The packager module (`echopage/packager.py`) encapsulates the four core packaging phases:

#### 1. DOM ID Mutation (`inject_alignment_spans`)
Wraps each aligned sentence in an inline span containing its unique element ID:
```html
<p>
  <span id="mo_s_0001">It was the best of times.</span>
  <span id="mo_s_0002">It was the worst of times.</span>
</p>
```

#### 2. SMIL 3.0 Document Synthesis (`generate_chapter_smil`, `copy_chapter_audio`)
Generates valid SMIL 3.0 XML documents linking text IDs to audio timestamps:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<smil xmlns="http://www.w3.org/ns/SMIL" xmlns:epub="http://www.idpf.org/2007/ops" version="3.0">
  <body>
    <seq id="seq_chapter01" epub:textref="chapter01.xhtml">
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

#### 3. OPF Package Manifest Updates (`opf.py`)
* Automatically upgrades EPUB 2 `package.opf` to EPUB 3.0 if necessary.
* In `<metadata>`:
  * Adds global playback duration: `<meta property="media:duration">01:24:30.000</meta>`.
  * Adds per-SMIL duration: `<meta property="media:duration" refines="#smil_chapter01">00:15:20.000</meta>`.
  * Injects active CSS class: `<meta property="media:active-class">-epub-media-overlay-active</meta>`.
* In `<manifest>`:
  * Links XHTML items to overlays: `media-overlay="smil_chapter01"`.
  * Registers SMIL items with `media-type="application/smil+xml"`.
  * Registers audio tracks with proper MIME types (`audio/mpeg`, `audio/mp4`).

#### 4. Container Packaging & Compression (`zip_epub_container`, `validate_epub`)
* First entry in zip archive is stored with `ZIP_STORED` (uncompressed) at offset 0: `mimetype` containing `application/epub+zip`.
* All subsequent entries compressed using `ZIP_DEFLATED`.
* Validates output with EPUBCheck if installed on the host.

---

## 4. CLI Interface Specification

### Primary Command: `echopage build`

```bash
echopage build \
  --epub ./sources/book.epub \
  --audio ./sources/book.m4b \
  --output ./dist/book_narrated.epub \
  --model-size auto \
  --dry-run
```

| Flag | Type | Default | Description |
|---|---|---|---|
| `--epub PATH` | Required | - | Source EPUB file (EPUB 2 or 3) |
| `--audio PATH [PATH...]` | Required | - | One or more audio files (`.m4b`, `.mp3`, `.aax`, `.aaxc`) |
| `--output PATH` | Required | - | Destination synchronized `.epub` path |
| `--activation-bytes HEX` | Optional | `None` | 8-character hex key for Audible AAX |
| `--audible-key HEX` | Optional | `None` | Key for Audible AAXC (requires `--audible-iv`) |
| `--audible-iv HEX` | Optional | `None` | IV for Audible AAXC (requires `--audible-key`) |
| `--model-size SIZE` | Optional | `auto` | `auto`, `tiny`, `base`, `small`, `medium`, `large-v1`, `large-v2`, `large-v3` |
| `--device DEV` | Optional | `auto` | `auto`, `cuda`, `mps`, `cpu` |
| `--granularity LEVEL` | Optional | `sentence` | `sentence` (default); `word` is reserved in CLI schema |
| `--work-dir DIR` | Optional | `.echopage_build_<stem>` | Scratch workspace for extraction & caching |
| `--auto-map / --no-auto-map` | Optional | `True` | Heuristic matching of spine chapters to audio |
| `--skip-spine IDS` | Optional | `None` | Comma-separated spine item IDs to explicitly skip |
| `--dry-run` | Optional | `False` | Inspect mapping plan without running heavy alignment |
| `--force` | Optional | `False` | Ignore cached `alignment.json` and re-align |
| `--keep-temp` | Optional | `False` | Retain 16kHz scratch WAV files |
| `--verbose` | Optional | `False` | Verbose debug logging |

### Diagnostic & Step Subcommands
EchoPage provides isolated subcommands for debugging individual pipeline phases:
* `echopage probe <audio>`: Inspect audio duration, codec, and embedded chapter markers.
* `echopage split <audio> --out-dir <dir>`: Extract individual chapters from M4B/MP3.
* `echopage to-wav <audio> <out.wav>`: Convert audio to 16kHz mono WAV.
* `echopage decrypt <audio> --out-dir <dir>`: Decrypt AAX/AAXC files.
* `echopage parse <epub> --work-dir <dir>`: Unpack EPUB and extract chapter sentences.
* `echopage align <epub> <audio> --json-out <out.json>`: Generate `alignment.json` directly.
* `echopage inject-spans <work_dir> <alignment.json>`: Inject `<span>` tags into unpacked XHTML.
* `echopage generate-smil <work_dir> <alignment.json> --audio <dir>`: Synthesize SMIL playlists.
* `echopage update-opf <work_dir> [--alignment <file>] [--audio <files>]`: Update package manifest.

---

## 5. Implementation Status

All core modules and technical specifications are 100% implemented, tested, and validated:

- [x] **Module 1: Audio & Decryption (`echopage/audio.py`, `echopage/decryptor.py`)**
  - [x] Format detector for `.aax`, `.aaxc`, `.m4b`, `.mp3`.
  - [x] Stream-copy decryption runner for AAX & AAXC via FFmpeg.
  - [x] M4B chapter metadata probe & track splitter.
  - [x] 16kHz mono WAV resampler with automatic cleanup.
- [x] **Module 2: EPUB Parser (`echopage/parser.py`)**
  - [x] Safe extraction with zip-slip prevention.
  - [x] OPF package, spine, manifest, and TOC/NCX metadata reading.
  - [x] Deterministic sentence segmentation with inline markup preservation.
- [x] **Module 3: Alignment & Heuristic Auto-Map (`echopage/aligner.py`, `echopage/automap.py`)**
  - [x] Heuristic front/back-matter detection (Title, Copyright, TOC, Dramatis Personae, Timeline).
  - [x] Fuzzy title string and duration ratio matching.
  - [x] WhisperX neural forced alignment pipeline.
  - [x] Hardware-aware VRAM model auto-selection (`auto` -> `large-v3`, `medium`, `small`).
  - [x] Intermediate `alignment.json` serialization and cache invalidation (`--force`).
- [x] **Module 4: Media Overlays Packager (`echopage/packager.py`)**
  - [x] Clean inline `<span>` ID injection (`inject_alignment_spans`).
  - [x] SMIL 3.0 XML playlist generation (`generate_chapter_smil`, `copy_chapter_audio`).
  - [x] EPUB 2/3 OPF duration calculation, active class, and manifest overlay binding (`update_opf_manifest`).
  - [x] Standard-compliant zip packaging (`mimetype` uncompressed first) and EPUBCheck validation (`zip_epub_container`).
- [x] **Module 5: CLI & Automation (`echopage/cli.py`, `setup.sh`, `setup.ps1`)**
  - [x] Unified CLI with full parameter support and isolated subcommands.
  - [x] Cross-platform automated setup scripts powered exclusively by Astral `uv` (Linux, macOS, Windows PowerShell).
  - [x] Package management standard: Strict reliance on `uv` (`uv venv`, `uv pip install`); `pip` is not used.
  - [x] 238 unit and integration tests passing.
