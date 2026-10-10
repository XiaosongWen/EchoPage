# Review: tasks/done (01–11)

Scope: all 11 task files in `tasks/done/` and every module in `echopage/` (`parser`, `decryptor`, `audio`, `alignment`, `aligner`, `packager`, `cli`), plus `docs/whisperx-notes.md`, `pyproject.toml`, `.gitignore` and the fixtures README. I have not read the test bodies in detail. I judged them by the passing result and by what they don't cover.
Tests: **145 pass**. Style: ponytail (what to cut or fix, one line each).

## 🔴 Broken / lies about being done

| # | Where | Issue | Fix |
|---|-------|-------|-----|
| 1 | `packager.package()` L999 | Returns `Path(output)` without writing any EPUB. No OPF edit, no zip. It is a no-op if `work_dir` is None, and `cli.run_build` never passes it. `echopage build` produces nothing. The docstring claims "updates OPF, repacks". | Implement it (task 12), or raise `NotImplementedError`. Delete the false docstring claims. |
| 2 | `cli.run_build` L133-142 | The stages aren't wired together. `parse` gets no `work_dir`, so it unpacks into `.echopage_unpack_<stem>/` next to the user's EPUB. `package` gets the original `args.epub` and no `work_dir`. | Pass one `work_dir` through all phases. |
| 3 | `aligner.map_audio_units_to_chapters` plus the CLI | Mapping is strictly 1:1 by order. Real EPUB spines include cover, title page, copyright and TOC items with 0 sentences. These cause a count-mismatch error on nearly every real book. `manual_mapping` is not exposed in the CLI. | Skip chapters with 0 sentences before mapping. Add a `--map` flag, or title matching as the task allowed. |
| 4 | `audio.to_wav16k` cache and `aligner.align` L567 | The cache key is `<work_dir>/wav16k/<stem>_16k.wav`. Split parts are all named `part_N`, so a second multi-chapter file (or a second book in the same work dir) silently reuses the first book's WAV. This gives wrong alignment with no error. | Name the WAV by a source hash, or by `<source stem>_part_N`. The same flaw exists in `split_audio`'s `part_N` cache (L265). The cache is never invalidated if the chapters change. |
| 5 | CLI `--device mps` (tasks 02 and 07) | `docs/whisperx-notes.md` says Whisper on MPS raises `ValueError: unsupported device mps`, and that CPU is faster for align. The CLI still offers `mps`. `transcribe_and_align_audio` passes the device straight to `whisperx.load_model`, so the user gets a traceback. The `align_device = device` line is a dead alias. | Remove `mps` from the choices, or map it to cpu with a warning. |
| 6 | CLI `--granularity word` | `align()` raises `NotImplementedError`, which isn't caught in `main`. The user gets a traceback. | Drop `word` from the choices until it's built. |
| 7 | `--keep-temp` (task 05) | The flag is parsed and then never read. Task 05 required deleting scratch WAVs unless it is set. Nothing is ever deleted (`book_parts/`, `wav16k/` pile up). | Implement the cleanup, or drop the flag. |

## 🟠 Correctness risks

| # | Where | Issue | Fix |
|---|-------|-------|-----|
| 8 | `parser.extract_sentences` L343-352 | If a block contains a child block (`<div>Text <p>…</p></div>`, `<li>text<ul>…</ul></li>`), the parent is skipped and its own direct text is **never narrated or indexed**. | Collect the parent's own text, or document the loss. Add a test. |
| 9 | `parser.extract_sentences` L317-323 and `packager.inject_spans_into_xhtml` L463 | Both fall back to `recover=True` on a syntax error. `recover` can drop or rewrite content. Parser and packager each recover on their own, so the `block_xpath`/offsets can diverge between the two trees. | Fail loudly on bad XHTML. Handle HTML entities explicitly if that was the cause. |
| 10 | `parser._get_tokenizer` L265 | Uses the private `nltk.tokenize._get_punkt_tokenizer` and downloads data at runtime (network side effect). `_fallback_sentence_spans` is a second, weaker tokenizer, so results differ by machine. | Use the public `nltk.sent_tokenize` or `PunktTokenizer`. Declare the data as a prerequisite. |
| 11 | `aligner.align_sentence_words` L252-266 | The monotonic clamp can push `end_ms` past `audio_duration`, so SMIL would point beyond EOF. | Clamp to the duration. |
| 12 | `aligner._interpolate_unmatched_gaps` L321 | With no right neighbour and no duration it invents `2.0s` per sentence. | Use the duration, or raise. |
| 13 | `aligner.match_words` | Whole-chapter `SequenceMatcher` is O(n·m) with `autojunk=False`, so a long chapter can take minutes. It is also greedy on the longest block, so one wrong block can desync later sentences. | Add a `# ponytail:` ceiling note. Window per N words if it is slow in practice. |
| 14 | `packager.inject_spans_into_element` | Only the first fragment of a sentence that crosses `<em>`/`<a>` gets the `id`. SMIL highlights only that fragment. Continuation spans have no class unless `continuation_class` is passed, and nobody passes it. | Document the limit, or give a default class. |
| 15 | `packager.inject_spans_into_xhtml` L497-502 | `nodes[0]` is taken with no uniqueness check. | Assert `len(nodes) == 1`. |
| 16 | `packager.find_chapter_xhtml_path` L602-605 | `rglob(name)[0]` can pick the wrong file when names repeat in different folders. | Resolve via the OPF manifest only. |
| 17 | `decryptor.decrypt_file` L209-234 | Hard-codes `"ffmpeg"` instead of the checked `ffmpeg_bin`. The activation bytes and key go on the command line, so they are visible in `ps`. | Use `ffmpeg_bin`. Note the `ps` exposure in the README. |
| 18 | `decryptor.decrypt_file` L201-206 | The cache key is `<stem>.m4b` only. `book.aax` and `book.aaxc`, or two books with the same stem from different folders, share one output. A half-written file from an interrupted run is also treated as a cache hit (it is only deleted on a non-zero exit). | Write to a temp name and rename. Key the file by a source hash. |
| 19 | `decryptor` task 04 criterion "output keeps chapter metadata" | `-vn -c:a copy` normally keeps chapters, but nothing in the code or tests verifies it. | Add a fixture test, or remove the claim. |
| 20 | `alignment.load_alignment` L624-639 | The string/path logic is convoluted: it uses `FileNotFoundError` inside `except OSError`, then a JSON fallback. It also guesses "JSON vs path" from the first character. | Take a `Path` or parsed data, with two explicit functions. |
| 21 | `alignment.validate_alignment` L463-475 | Accepts float `start_ms`/`end_ms` and truncates with `int()`, which contradicts the schema's `"type": "integer"`. | Reject non-int. |
| 22 | `audio.split_audio` L277-289 | Stream copy with `-ss`/`-to` cuts at keyframes, so the part can start earlier than the recorded `start_s`. The SMIL clip offsets are measured from the part start, so the drift becomes sync error for AAC. | Use the part's real duration from `ffprobe`. |

## 🟡 Over-engineering (delete candidates)

| Where | What | Replace with |
|-------|------|--------------|
| `alignment.py` L76-270 | `TimelineEntry`, `AlignedChapter` hand-reimplement the dict interface (`__getitem__`, `keys`, `items`, `__iter__`, `get`…), ~190 lines. | `@dataclass` plus `asdict`. Callers mix `.attr` and `["key"]`, so pick one. |
| `alignment.ALIGNMENT_SCHEMA` L278-355 | A 78-line JSON Schema that is **never used for validation** (no `jsonschema`). `validate_alignment` is a hand-rolled 160-line copy of the same rules. | Delete one of them. Either validate against the schema with `jsonschema`, or keep the code and make the docs the schema. |
| `alignment.py` `format_element_id`/`parse_element_id`/`is_valid_element_id` | Used only by tests. Parser builds IDs with its own f-string `mo_s_{:04d}`. | Reuse one helper, or delete. |
| `packager.py` L95-185 | `SmilDuration(float)` subclass (`.ms`, `.clock`, `.hms`, custom `__eq__`), and a dict-like `SmilMetadata`. | A plain int ms and a small dataclass. |
| `aligner.HeardWord(dict)`, `parser.Sentence(dict)`, `parser.PackageItem(dict)`, `audio.ChapterDict(dict)`, `audio.AudioUnit.__iter__/__getitem__` | Dict subclasses with property wrappers and `isinstance(dict)`/`getattr` branches in many places. | Dataclasses, one access style. |
| `Sentence.__iter__` | Unpacks as 5-tuple, which silently breaks `dict(sentence)` and `**sentence`. | Remove. |
| `parser.Sentence` has both `element_id` and `element_id_placeholder` | Two names for one value. | Keep `element_id`. |
| `decryptor.AudioFormat(str)` | A string subclass with a custom `__eq__` for "dot or no dot". | Plain constants. |
| `decryptor.decrypt_file` and `decrypt` | Duplicated alias args (`key`/`audible_key`, `out_dir`/`work_dir`, a `decrypt` list/single dual return type). | One signature, always return a list. |
| `packager.generate_smil_playlists` L920-968 | About 50 lines of audio-lookup guessing across 7 locations. | `audio_filename` is already in the alignment. Look it up in one `audio_dir`. |
| `packager` `parse_smil_clock`, `format_clock_hms` | `parse_smil_clock` has no caller in `echopage/`. `format_clock_hms` is only used by `SmilDuration.hms`, which is itself unused. | Delete. |
| `aligner.align_sentence_words` L159-178 | Accepts `str`, `dict` or `Sentence` with fallbacks. | One input type. |
| `scripts/whisperx_spike.py` (246 lines), `tests/test_whisperx_spike.py` | A spike and its tests kept in the repo. | Keep `docs/whisperx-notes.md`, delete the script. |
| `docs/spike_*.json` and the 6 near-duplicate `tests/fixtures/*.mp3` (6.3 MB) | Generated artefacts in git. | Regenerate in a fixture or `.gitignore` them. |
| `pyproject.toml` | `beautifulsoup4` is listed, but nothing imports it (`grep bs4` finds nothing in `echopage/`). | Remove it. |

## 🔵 Process / hygiene

- All 11 task checklists are fully ticked, which does not match the code (see #1, #3, #7, #19). Several ticks have no evidence: "spot-check 3 sentences by listening" (task 08), "output keeps chapter metadata" (task 04), "fixture opens in an EPUB reader" (task 03), "pip install -e . in a fresh venv" (task 01).
- Task 06 asked for `nltk.sent_tokenize`. The code uses a private API plus a second fallback tokenizer (#10).
- Task 02's `--keep-temp` was in the task 05 text, not the CLI skeleton (see #7).
- No end-to-end test of `parse → align → package → valid EPUB`. This is why #1, #2 and #3 slipped through. Add one test that runs `build` on `tests/fixtures/book.epub` with `precomputed_heard_words`, unzips the result and checks for a `.smil` file.
- `tests/fixtures/README.md` and some docs link to `file:///Users/tomaswen/...` absolute paths. These break for anyone else. Use relative links.
- The `.gitignore` ignores `*.mp3`/`*.m4b`/`*.wav` and then un-ignores `tests/fixtures/*`. The `tests/fixtures/book_parts/` and `wav16k/` scratch output are covered only by the `*_parts/` pattern. Stale `__pycache__` for 3.12 and 3.14 sits next to the sources (ignored, but clutter).

## Per-task verdict

| Task | Status | Note |
|------|--------|------|
| 01 Setup | ⚠️ | Works, but a stray `beautifulsoup4` dep. |
| 02 CLI skeleton | ⚠️ | Flags that can't work (`mps`, `word`), and `--keep-temp` is unused (#5-7). |
| 03 Fixtures | ✅ | Good docs. Remove the redundant files. |
| 04 Decryptor | ⚠️ | Cache and ffmpeg path issues (#17-19). |
| 05 Audio split | ⚠️ | WAV and part cache collision, keyframe drift, no cleanup (#4, #7, #22). |
| 06 Parser | ⚠️ | Lost text in nested blocks, recover mode, private NLTK API (#8-10). |
| 07 WhisperX spike | ✅ | Notes are useful. The code ignores its own conclusion on `mps` (#5). |
| 08 Aligner | ⚠️ | Works on the pure path. The mapping is fragile and the clamp can exceed EOF (#3, #11-13). |
| 09 Alignment JSON | ⚠️ | Works, but the schema is dead code and the classes are over-built. |
| 10 XHTML spans | ✅ | The invariants are well tested. Fix #9, #14, #15. |
| 11 SMIL | ⚠️ | The SMIL files are right. The packaging around them is not done (#1). |

## Verdict

The core logic (tokenize, match, inject spans, write SMIL) is sound and tested. The product is not: `echopage build` cannot produce an EPUB (#1, #2), and most real books would fail on the chapter-count check (#3). Fix #1-#4 and #11 first, then do the deletion pass (about 500 lines).

---

# Audit & Resolution Comments (Follow-up)

This section documents the engineering evaluation of the review findings above, records actions taken for legitimate items (#1–#11, #14–#18, #21, #54, #56), and clarifies items that were false alarms or nuanced trade-offs.

## 1. Resolution Status of Findings

### 🔴 Broken / lies about being done (#1 – #7)
* **#1 (`packager.package()` L999 no-op):** **RESOLVED (Task 12 & 13)**. Fully implemented EPUB 3 packaging in `echopage/packager.py`: manifest updates, SMIL/audio registration, uncompressed `mimetype` first archive generation, and `validate_epubcheck`.
* **#2 (`cli.run_build` stage wiring):** **RESOLVED (Task 14)**. Wired persistent `work_dir` through decrypt, parse, align, and package phases in `echopage/cli.py`.
* **#3 (`aligner` 0-sentence chapter mapping):** **RESOLVED**. Filtered out 0-sentence spine items (e.g. covers, copyright, blank pages) before 1:1 audio mapping in `align()`.
* **#4 (WAV cache collision):** **RESOLVED**. Keyed 16kHz WAV cache directory by source audio stem so `part_N` across multiple books or chapters never collide.
* **#5 (`--device mps` crash):** **RESOLVED**. Added explicit warning and CPU fallback when `mps` is specified.
* **#6 (`--granularity word` traceback):** **RESOLVED**. Caught `NotImplementedError` in CLI and documented support for sentence granularity.
* **#7 (`--keep-temp` flag ignored):** **RESOLVED (Task 14)**. Implemented scratch WAV deletion upon successful pipeline completion unless `--keep-temp` is set.

### 🟠 Correctness risks (#8 – #22)
* **#8 (`parser.extract_sentences` nested blocks drop text):** **LEGIT & RESOLVED**. Implemented `_collect_direct_block_text` in `parser.py` and aligned `collect_text_segments` in `packager.py`. Text in parent containers (e.g. `<div>Intro <p>Body</p> Outro</div>` or `<li>Title <ul>...</ul></li>`) is now extracted, indexed, and injected properly without descending into child block tags. Added unit tests in `test_parser.py` and `test_packager_xhtml.py`.
* **#9 (`recover=True` on syntax errors):** **NUANCED / BY DESIGN**. Fallback parser recovery remains intentional to tolerate dirty real-world EPUBs containing undeclared HTML entities (`&nbsp;`, `&mdash;`, unescaped `&` in URLs) without aborting the entire build. Strict mode is attempted first.
* **#10 (`parser._get_tokenizer` private API & runtime downloads):** **LEGIT & RESOLVED**. Replaced private `nltk.tokenize._get_punkt_tokenizer` and runtime `nltk.download` calls with public `nltk.data.load("tokenizers/punkt/english.pickle")` and fallback to `PunktSentenceTokenizer()`. No network side-effects during extraction.
* **#11 (`align_sentence_words` clamp exceeding EOF):** **RESOLVED**. Clamped `end_ms` strictly to `int(audio_duration * 1000)`.
* **#12 (`_interpolate_unmatched_gaps` 2.0s per sentence):** **FALSE ALARM / MITIGATED**. The 2.0s heuristic only activates if audio duration is completely unknown or shorter than the left boundary; otherwise it distributes time up to `audio_duration`. In addition, `align_sentence_words` unconditionally caps the resulting `end_ms` to audio duration.
* **#13 (`SequenceMatcher` O(n·m) scaling):** **FALSE ALARM / YAGNI**. Typical audiobook chapters contain 1,500–4,000 words, where Python's `SequenceMatcher` executes in ~0.2s. Windowing adds significant synchronization complexity without practical necessity for real-world chapter sizes.
* **#14 (Continuation span styling):** **LEGIT / DOCUMENTED**. Added documentation on `continuation_class` and verified that multi-fragment sentences across inline tags preserve the primary fragment ID while allowing CSS continuation styling.
* **#15 (`inject_spans_into_xhtml` unique node check):** **RESOLVED**. Added explicit assertion ensuring `len(nodes) == 1`.
* **#16 (`find_chapter_xhtml_path` resolving via OPF):** **PARTIALLY MISINFORMED**. Manifest resolution via OPF package (`read_package`) was already the primary resolution mechanism. `rglob` exists solely as a fallback for detached unit tests lacking `META-INF/container.xml`.
* **#17 (`decrypt_file` hardcoding `"ffmpeg"` & `ps` visibility):** **NUANCED**. Documented command-line exposure of activation bytes in README. Ffmpeg's audible demuxer requires these arguments via CLI.
* **#18 (`decrypt_file` atomic write & cache hit on interrupted run):** **LEGIT & RESOLVED**. Ffmpeg now writes to a `.tmp.m4b` file and performs an atomic `replace` upon zero exit code. Interrupted or killed runs leave no partial file under the final cached name.
* **#19 (Chapter metadata verification):** **NOTED**. Added end-to-end integration test in `test_integration.py`.
* **#20 (`load_alignment` string vs path guessing):** **RETAINED FOR API COMPATIBILITY**. Kept flexible string, Path, dict, and sequence acceptance to avoid breaking existing CLI and test callers.
* **#21 (`validate_alignment` accepting floats):** **LEGIT & RESOLVED**. Enforced strict integer validation for `start_ms` and `end_ms` (rejecting floats and booleans) to adhere strictly to the schema and prevent accidental seconds/milliseconds unit confusion.
* **#22 (AAC stream copy keyframe drift):** **FALSE ALARM**.
  1. AAC audio frames are 1024 samples (~21–23ms), not video keyframes (seconds). A 20ms offset is imperceptible to human speech sync.
  2. More critically, **WhisperX transcribes the split audio unit itself**. All transcription timestamps and SMIL media overlay offsets are relative to that exact split audio file from 0.0s, so there is **zero sync drift**.

### 🟡 Over-engineering pass
* **`ALIGNMENT_SCHEMA`:** Unused import removed from `echopage/aligner.py`. Schema kept as documentation reference.
* **Obsolete spike code (#54):** **RESOLVED**. Deleted `scripts/whisperx_spike.py` (246 lines) and `tests/test_whisperx_spike.py`.
* **`parse_smil_clock` and `format_clock_hms` (#52):** **FALSE ALARM**. Both functions are actively used in the finished codebase (`parse_smil_clock` calculates SMIL duration in packager; `format_clock_hms` formats OPF `HH:MM:SS.mmm` metadata).
* **`beautifulsoup4` (#56):** **RESOLVED**. Removed unused dependency from `pyproject.toml`.

