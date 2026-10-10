# EchoPage

EchoPage transforms standard EPUB eBooks and audiobooks into fully synchronized EPUB 3 Media Overlays with word- or sentence-level audio highlighting.

Compatible with Media Overlays-capable readers including **Thorium Reader**, **Apple Books**, and modern EPUB 3 reading systems.

---

## Prerequisites

- **Python 3.10+**
- **FFmpeg** (audio probing, transcoding, and segment splitting):
  ```sh
  brew install ffmpeg
  ```
- **Java & EPUBCheck** (optional, recommended for packaging validation):
  ```sh
  brew install epubcheck
  ```
- **WhisperX** (for neural speech recognition & forced alignment):
  ```sh
  pip install -e ".[align]"
  ```

---

## Installation

### Quick Automated Setup (Recommended)

Run the automated setup script for your platform. It automatically detects Python, FFmpeg, and GPU/CUDA hardware, creates the `.venv` virtual environment, installs all dependencies (including WhisperX and PyTorch with CUDA for RTX GPUs), and pre-caches NLTK tokenizers:

**On Linux / WSL2 / macOS:**
```sh
./setup.sh
```

**On Windows (PowerShell):**
```powershell
.\setup.ps1
```

### Manual Installation

```sh
git clone https://github.com/XiaosongWen/EchoPage.git
cd EchoPage
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[align,dev]"
```

> **Note:** Always activate the virtual environment (`source .venv/bin/activate` or `.\.venv\Scripts\Activate.ps1`) before running `echopage` or `pytest`.

---

## Quick Start

### 1. Build a Narrated EPUB
```sh
echopage build \
  --epub ./sources/book.epub \
  --audio ./sources/book.m4b \
  --output ./dist/book_narrated.epub
```

### 2. Preview Chapter Mapping Without Aligning (`--dry-run`)
```sh
echopage build \
  --epub ./sources/book.epub \
  --audio ./sources/book.m4b \
  --output ./dist/book_narrated.epub \
  --dry-run
```

### 3. Build from Audible AAX with Activation Bytes
```sh
echopage build \
  --epub ./sources/book.epub \
  --audio ./sources/book.aax \
  --activation-bytes 1a2b3c4d \
  --output ./dist/book_narrated.epub
```

---

## CLI Reference

### `echopage build`

| Flag | Description | Default |
|---|---|---|
| `--epub PATH` | Path to source input EPUB (EPUB 2 or EPUB 3) | *(required)* |
| `--audio PATH [PATH...]` | One or more audiobook files (`.m4b`, `.mp3`, `.aax`, `.aaxc`) | *(required)* |
| `--output PATH` | Path for the synchronized output EPUB | *(required)* |
| `--work-dir DIR` | Cache directory for intermediate files and resume support | `.echopage_build_<stem>` |
| `--force` | Force re-running alignment even if cached `alignment.json` exists | `False` |
| `--keep-temp` | Retain scratch 16kHz WAV files after alignment | `False` |
| `--dry-run` | Inspect EPUB and audio and print planned mapping without aligning | `False` |
| `--skip-spine ID,...` | Comma-separated spine item IDs to exclude (e.g. `cover,toc,colophon`) | None |
| `--granularity` | Synchronization granularity (`sentence` or `word`) | `sentence` |
| `--model-size` | Whisper model size (`tiny`, `base`, `small`, `medium`, `large-v3`) | `small` |
| `--device` | Compute device (`cpu`, `cuda`, `mps`). MPS falls back to CPU | `auto` |
| `--activation-bytes` | 8-character hex Audible activation bytes for AAX decryption | None |
| `--audible-key` / `--audible-iv` | AAXC decryption key and IV hex strings | None |
| `--verbose` | Enable debug logging output | `False` |

### Utility Subcommands
- `echopage probe <audio>`: Inspect audio chapters and durations.
- `echopage split <audio> -o <dir>`: Cut audiobook into chapter segments.
- `echopage to-wav <audio> <out.wav>`: Convert audio to 16 kHz mono WAV.
- `echopage decrypt <audio> --activation-bytes <hex>`: Decrypt Audible file.
- `echopage parse <epub>`: Unpack EPUB and extract chapter sentences.
- `echopage update-opf <work_dir>`: Update OPF package manifest with overlays.

---

## Audible AAX Decryption & Legal Notice

### Obtaining Activation Bytes
Audible AAX files are protected by Audible DRM. To convert titles that you own, obtain your 8-hex-character activation bytes using community utilities such as [audible-cli](https://github.com/mkb79/audible-cli) or [Audible-Activator](https://github.com/inAudible-NG/audible-activator).

### Legal Notice
> **Personal Use Only:** EchoPage is intended solely for personal, private format-shifting and accessibility augmentation of legally purchased audiobooks and eBooks that you own. Do not decrypt, reproduce, or distribute copyrighted content in violation of applicable laws or terms of service.

---

## Performance & Memory Management

Full-length audiobooks (10–30+ hours) are processed chapter-by-chapter rather than loading the entire book into memory:
- **Audio Splitting**: Audiobooks are split into chapter segments using FFmpeg stream copy (`-c copy`), avoiding full re-encoding.
- **Scratch Space**: Audio is resampled to 16 kHz mono WAV only for alignment; scratch files are automatically removed upon completion unless `--keep-temp` is specified.
- **RAM Usage**: Peak memory consumption during forced alignment is ~1.5 GB to 2.5 GB with `small` Whisper models, running efficiently on modern laptops.
- **Incremental Resumption**: Passing `--work-dir` stores the extracted sentences, chapter audio, and `alignment.json`. Subsequent runs skip alignment and take mere seconds.

---

## Edge Cases Handled

1. **Audio & Spine Item Mismatch**: EPUB spines often contain non-narrated front matter (cover, copyright, table of contents). EchoPage automatically skips chapters with 0 sentences and allows manual omission via `--skip-spine <id>`.
2. **Missing Audio Chapter Markers**: Single-file audiobooks without chapter markers are aligned as a single unit or matched to the primary chapter.
3. **EPUB 2 Upgrades**: Legacy EPUB 2 documents (`version="2.0"`) are automatically upgraded to EPUB 3 (`version="3.0"`), synthesizing an EPUB 3 navigation document (`nav.xhtml`) while preserving existing NCX tables of contents.
4. **Hardware Acceleration Fallbacks**: If `--device mps` is requested, EchoPage warns and seamlessly falls back to CPU, avoiding CTranslate2 unsupported device crashes.

---

## Troubleshooting

- **`epubcheck: command not found`**: Install EPUBCheck via `brew install epubcheck` or skip EPUBCheck validation. EchoPage still generates a structurally compliant EPUB.
- **`device 'mps' is unsupported`**: CTranslate2 (used by WhisperX) does not support Apple Silicon MPS for alignment; CPU is automatically selected and delivers optimal throughput.
- **Alignment Drifting**: Ensure the audio narration unabridged text matches the eBook edition. Preview with `--dry-run` to verify that chapter counts correspond.

## Documentation & Architecture

For deep-dive technical details, data contracts, and internal design specifications:
- [System Architecture & Specification](ARCHITECTURE.md): Detailed pipeline dataflow, `alignment.json` data contracts, SMIL 3.0 synthesis rules, and OPF metadata specifications.
- [Technical Guides & Primers](docs/): Detailed notes on audio processing, EPUB span injection, and WhisperX alignment.

---

## Testing

```sh
pytest
```
Run tests excluding slow neural alignment models:
```sh
pytest -m "not slow"
```
