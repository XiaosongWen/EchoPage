import argparse
import logging
import re
import shutil
import sys
from pathlib import Path

from echopage import aligner, audio, decryptor, packager, parser as epub_parser
from echopage.logger import format_duration, setup_logging, timed_step

log = logging.getLogger("echopage.cli")


def build_parser():
    p = argparse.ArgumentParser(
        prog="echopage",
        description="Add synced audio narration to an EPUB.",
    )
    p.add_argument("--verbose", action="store_true", help="enable debug logging")
    sub = p.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="build a narrated EPUB from an EPUB and audiobook")
    b.add_argument("--epub", required=True, help="path to the input EPUB")
    b.add_argument("--audio", required=True, nargs="+", help="one or more audiobook files")
    b.add_argument("--output", required=True, help="path of the output EPUB")
    b.add_argument("--activation-bytes", help="Audible activation bytes (8 hex characters)")
    b.add_argument("--audible-key", help="Audible AAXC key (requires --audible-iv)")
    b.add_argument("--audible-iv", help="Audible AAXC IV (requires --audible-key)")
    b.add_argument("--granularity", choices=["sentence", "word"], default="sentence",
                   help="sync granularity (default: sentence)")
    b.add_argument("--model-size", choices=["auto", "small", "medium", "large-v3", "large-v2", "base", "tiny"], default="auto",
                   help="WhisperX model size (default: auto, selects largest suitable model for hardware)")
    b.add_argument("--device", choices=["cpu", "cuda", "mps"], help="compute device")
    b.add_argument("--work-dir", help="directory for intermediate files")
    b.add_argument("--keep-temp", action="store_true", help="keep temporary intermediate files")
    b.add_argument("--force", action="store_true", help="force re-running intermediate alignment steps")
    b.add_argument("--skip-spine", help="comma-separated list of spine item IDs to skip (e.g. cover,toc)")
    b.add_argument("--auto-map", action=argparse.BooleanOptionalAction, default=True,
                   help="automatically match audio to EPUB chapters and skip non-narrated pages (default: True)")
    b.add_argument("--dry-run", action="store_true", help="parse EPUB and audio, print planned mapping without aligning")
    b.add_argument("--verbose", action="store_true", help="enable debug logging")
    # probe subcommand
    p_probe = sub.add_parser("probe", help="inspect chapters and duration of an audio file")
    p_probe.add_argument("audio", help="path to audio file")

    # split subcommand
    p_split = sub.add_parser("split", help="split audio file into chapter segments")
    p_split.add_argument("audio", help="path to audio file")
    p_split.add_argument("--out-dir", "-o", help="output directory for split chapters")

    # to-wav subcommand
    p_towav = sub.add_parser("to-wav", help="convert audio file to 16kHz mono WAV")
    p_towav.add_argument("audio", help="path to audio file")
    p_towav.add_argument("output", help="path to output WAV file")

    # decrypt subcommand
    p_dec = sub.add_parser("decrypt", help="decrypt an Audible audio file")
    p_dec.add_argument("audio", help="path to audio file")
    p_dec.add_argument("--out-dir", "-o", help="output directory for decrypted file")
    p_dec.add_argument("--activation-bytes", help="Audible activation bytes (8 hex characters)")
    p_dec.add_argument("--audible-key", help="Audible AAXC key (requires --audible-iv)")
    p_dec.add_argument("--audible-iv", help="Audible AAXC IV (requires --audible-key)")

    # parse subcommand
    p_parse = sub.add_parser("parse", help="unpack EPUB and extract chapter sentences")
    p_parse.add_argument("epub", help="path to EPUB file")
    p_parse.add_argument("--work-dir", help="working directory for unpacking")

    # align subcommand
    p_align = sub.add_parser("align", help="align EPUB sentences to audio narration")
    p_align.add_argument("epub", help="path to EPUB file")
    p_align.add_argument("audio", nargs="+", help="audio file(s)")
    p_align.add_argument("--model-size", choices=["auto", "small", "medium", "large-v3", "large-v2", "base", "tiny"], default="auto",
                         help="WhisperX model size (default: auto, selects largest suitable model for hardware)")
    p_align.add_argument("--device", choices=["cpu", "cuda", "mps"])
    p_align.add_argument("--work-dir", help="working directory")
    p_align.add_argument("--json-out", help="save alignment output JSON to file")
    p_align.add_argument("--auto-map", action=argparse.BooleanOptionalAction, default=True,
                         help="automatically match audio to EPUB chapters and skip non-narrated pages (default: True)")

    # inject-spans subcommand
    p_inject = sub.add_parser("inject-spans", help="inject sentence span IDs into XHTML documents")
    p_inject.add_argument("work_dir", help="work directory containing unpacked EPUB or XHTML files")
    p_inject.add_argument("alignment", help="path to alignment JSON file")

    # generate-smil subcommand
    p_smil = sub.add_parser("generate-smil", help="generate SMIL 3.0 Media Overlays playlists and copy audio files")
    p_smil.add_argument("work_dir", help="work directory containing unpacked EPUB")
    p_smil.add_argument("alignment", help="path to alignment JSON file")
    p_smil.add_argument("--audio", nargs="*", help="optional audio source file(s) or directory")

    # update-opf subcommand
    p_opf = sub.add_parser("update-opf", help="update OPF package manifest with Media Overlays and audio")
    p_opf.add_argument("work_dir", help="work directory containing unpacked EPUB")
    p_opf.add_argument("--alignment", help="optional path to alignment JSON file")
    p_opf.add_argument("--audio", nargs="*", help="optional audio source file(s) or directory")

    return p


def validate(args, parser):
    if args.command == "build":
        for path in [args.epub, *args.audio]:
            if not Path(path).is_file():
                parser.error(f"file not found: {path}")
        if args.activation_bytes and not re.fullmatch(r"[0-9a-fA-F]{8}", args.activation_bytes):
            parser.error("--activation-bytes must be exactly 8 hex characters")
        if bool(args.audible_key) != bool(args.audible_iv):
            parser.error("--audible-key and --audible-iv must be given together")
    elif args.command == "align":
        if not Path(args.epub).is_file():
            parser.error(f"file not found: {args.epub}")
        for path in args.audio:
            if not Path(path).is_file():
                parser.error(f"file not found: {path}")
    elif args.command in ("probe", "split", "to-wav", "decrypt"):
        if not Path(args.audio).is_file():
            parser.error(f"file not found: {args.audio}")
        if getattr(args, "activation_bytes", None) and not re.fullmatch(r"[0-9a-fA-F]{8}", args.activation_bytes):
            parser.error("--activation-bytes must be exactly 8 hex characters")
        if hasattr(args, "audible_key") and bool(args.audible_key) != bool(args.audible_iv):
            parser.error("--audible-key and --audible-iv must be given together")
    elif args.command == "parse":
        if not Path(args.epub).is_file():
            parser.error(f"file not found: {args.epub}")
    elif args.command == "inject-spans":
        if not Path(args.work_dir).is_dir():
            parser.error(f"directory not found: {args.work_dir}")
        if not Path(args.alignment).is_file():
            parser.error(f"file not found: {args.alignment}")
    elif args.command == "generate-smil":
        if not Path(args.work_dir).is_dir():
            parser.error(f"directory not found: {args.work_dir}")
        if not Path(args.alignment).is_file():
            parser.error(f"file not found: {args.alignment}")
        if getattr(args, "audio", None):
            for a in args.audio:
                if not Path(a).exists():
                    parser.error(f"audio path not found: {a}")
    elif args.command == "update-opf":
        if not Path(args.work_dir).is_dir():
            parser.error(f"directory not found: {args.work_dir}")
        if getattr(args, "alignment", None) and not Path(args.alignment).is_file():
            parser.error(f"file not found: {args.alignment}")
        if getattr(args, "audio", None):
            for a in args.audio:
                if not Path(a).exists():
                    parser.error(f"audio path not found: {a}")


_PHASE_HINTS: dict[str, str] = {
    "decrypt": "Verify that audio files exist and Audible credentials (--activation-bytes or --audible-key/--audible-iv) are correct.",
    "parse": "Check that the EPUB file is valid and contains standard EPUB 2/3 OPF package metadata.",
    "align": "Ensure WhisperX / PyTorch dependencies are installed and audio matches the book text. Try --device cpu or --model-size tiny.",
    "package": "Verify that EPUB container directories and permissions are writable.",
}


def _phase(name, fn, *a, **kw):
    with timed_step(log, f"Phase '{name}'"):
        log.info("%s: start", name)
        try:
            result = fn(*a, **kw)
            log.info("%s: done", name)
            return result
        except Exception as exc:
            log.error("Build failed in phase '%s': %s", name, exc)
            hint = _PHASE_HINTS.get(name)
            if hint:
                log.info("Fix hint (%s): %s", name, hint)
            raise


def run_build(args):
    work_dir = Path(args.work_dir) if args.work_dir else Path(f".echopage_build_{Path(args.epub).stem}")
    work_dir.mkdir(parents=True, exist_ok=True)
    epub_dir = work_dir / "epub"
    epub_dir.mkdir(parents=True, exist_ok=True)

    audio_files = _phase(
        "decrypt",
        decryptor.decrypt,
        args.audio,
        activation_bytes=args.activation_bytes,
        audible_key=args.audible_key,
        audible_iv=args.audible_iv,
        work_dir=work_dir,
    )
    book = _phase(
        "parse",
        epub_parser.parse,
        args.epub,
        work_dir=epub_dir,
    )

    skip_spine_list = (
        [s.strip() for s in args.skip_spine.split(",") if s.strip()]
        if getattr(args, "skip_spine", None)
        else None
    )
    auto_map_enabled = getattr(args, "auto_map", True)

    if getattr(args, "dry_run", False):
        print("Dry run: planned chapter-to-audio mapping:")
        chapters = book.get("chapters", [])
        if skip_spine_list:
            skip_set = set(skip_spine_list)
            chapters = [c for c in chapters if c.get("id") not in skip_set]
        chapters = [c for c in chapters if c.get("sentences")]
        audio_units = aligner.prepare_audio_units(audio_files, work_dir=work_dir, split=False)

        use_automap = auto_map_enabled and (skip_spine_list is None or len(chapters) != len(audio_units))
        pairs, skipped = aligner.map_audio_units_to_chapters(
            chapters,
            audio_units,
            auto_map=use_automap,
            return_skipped=True,
        )
        for ch, unit in pairs:
            s_count = len(ch.get("sentences", []))
            dur = max(0.0, unit.end_s - unit.start_s)
            ch_title_desc = f" ({ch.get('title')})" if ch.get("title") else ""
            audio_label = unit.title or unit.path.name
            print(f"  - Chapter '{ch['id']}'{ch_title_desc} ({ch.get('href', '')}, {s_count} sentences) -> Audio '{audio_label}' ({unit.start_s:.2f}s - {unit.end_s:.2f}s, {dur:.2f}s)")

        if skipped:
            print(f"\nAuto-skipped chapters ({len(skipped)}):")
            for ch, reason in skipped:
                ch_label = ch.get("title") or ch.get("href") or ch.get("id")
                print(f"  - Skipped '{ch_label}' ({ch['id']}): {reason}")

        model_setting = getattr(args, "model_size", "auto")
        if model_setting == "auto":
            detected_model = aligner.get_optimal_model_size(getattr(args, "device", None))
            print(f"\nModel selection: auto -> '{detected_model}'")
        else:
            print(f"\nModel selection: '{model_setting}'")
        return

    alignment_json = work_dir / "alignment.json"
    force = getattr(args, "force", False)

    if not force and alignment_json.is_file():
        log.info("align: reusing cached alignment from %s", alignment_json)
        alignment = _phase("align", aligner.load_alignment, alignment_json)
    else:
        alignment = _phase(
            "align",
            aligner.align,
            book,
            audio_files,
            granularity=args.granularity,
            model_size=args.model_size,
            device=args.device,
            work_dir=work_dir,
            skip_spine=skip_spine_list,
            auto_map=auto_map_enabled,
        )
        if alignment:
            aligner.save_alignment(alignment, alignment_json)

    # Clean up temporary scratch WAV files unless --keep-temp is set (#7)
    if not getattr(args, "keep_temp", False):
        temp_wav_dir = work_dir / "wav16k"
        if temp_wav_dir.is_dir():
            shutil.rmtree(temp_wav_dir, ignore_errors=True)
            log.debug("Cleaned up temporary WAV directory %s", temp_wav_dir)

    # Look for split audio directory in work_dir
    audio_source_for_pack = list(audio_files) if isinstance(audio_files, (list, tuple)) else [audio_files]
    if len(audio_source_for_pack) == 1:
        single_stem = Path(audio_source_for_pack[0]).stem
        split_cand = work_dir / single_stem
        if split_cand.is_dir():
            audio_source_for_pack = [split_cand]

    _phase(
        "package",
        packager.package,
        args.epub,
        audio_source_for_pack,
        alignment,
        args.output,
        work_dir=epub_dir,
    )


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(verbose=args.verbose)
    validate(args, parser)
    try:
        if args.command == "build":
            run_build(args)
        elif args.command == "probe":
            chapters = audio.probe_chapters(args.audio)
            print(f"File: {args.audio}")
            print(f"Total chapters: {len(chapters)}")
            for i, ch in enumerate(chapters, 1):
                dur = max(0.0, ch.end_s - ch.start_s)
                print(f"  [{i}] {ch.title} ({ch.start_s:.2f}s - {ch.end_s:.2f}s, duration: {dur:.2f}s)")
        elif args.command == "split":
            units = audio.split_audio(args.audio, out_dir=args.out_dir)
            print(f"Split {args.audio} into {len(units)} parts:")
            for u in units:
                print(f"  {u.path} ({u.title})")
        elif args.command == "to-wav":
            out_file = audio.to_wav16k(args.audio, args.output)
            print(f"Converted to 16kHz mono WAV: {out_file}")
        elif args.command == "decrypt":
            out_file = decryptor.decrypt_file(
                args.audio,
                out_dir=args.out_dir,
                activation_bytes=args.activation_bytes,
                audible_key=args.audible_key,
                audible_iv=args.audible_iv,
            )
            print(f"Decrypted audio: {out_file}")
        elif args.command == "parse":
            result = epub_parser.parse_epub(args.epub, work_dir=args.work_dir)
            print(f"Unpacked EPUB: {args.epub}")
            print(f"Work directory: {result['work_dir']}")
            print(f"Spine chapters ({len(result['chapters'])}):")
            for ch in result["chapters"]:
                s_count = len(ch["sentences"])
                print(f"  - {ch['id']} ({ch['href']}): {s_count} sentences")
        elif args.command == "align":
            alignment = aligner.align(
                args.epub,
                args.audio,
                model_size=args.model_size,
                device=args.device,
                work_dir=args.work_dir,
                auto_map=getattr(args, "auto_map", True),
            )
            print(f"Aligned {len(alignment)} chapters:")
            for ch in alignment:
                print(f"  Chapter '{ch.spine_item_id}' ({ch.xhtml_filename} -> {ch.audio_filename}): {len(ch.timeline)} sentences")
                for entry in ch.timeline:
                    dur_s = (entry.end_ms - entry.start_ms) / 1000.0
                    print(f"    [{entry.element_id}] {entry.start_ms}ms - {entry.end_ms}ms ({dur_s:.2f}s, conf={entry.confidence:.2f}): {entry.text[:60]}")
            if args.json_out:
                aligner.save_alignment(alignment, args.json_out)
                print(f"Saved alignment to: {args.json_out}")
        elif args.command == "inject-spans":
            results = packager.inject_alignment_spans(args.work_dir, args.alignment)
            print(f"Injected spans into {len(results)} chapters:")
            for ch_id, pth in results.items():
                print(f"  - {ch_id}: {pth}")
        elif args.command == "generate-smil":
            results = packager.generate_smil_playlists(args.work_dir, args.alignment, audio_source=args.audio)
            print(f"Generated SMIL playlists for {len(results)} chapters:")
            for ch_id, meta in results.items():
                print(f"  - {ch_id}: {meta.smil_path.name} ({meta.duration_clock}, {meta.par_count} clips)")
        elif args.command == "update-opf":
            smil_meta = None
            if getattr(args, "alignment", None):
                smil_meta = packager.generate_smil_playlists(args.work_dir, args.alignment, audio_source=args.audio)
            opf_path = packager.update_opf_manifest(args.work_dir, smil_metadata=smil_meta, audio_files=args.audio)
            print(f"Updated OPF package manifest: {opf_path}")
    except (decryptor.DecryptionError, audio.AudioError, epub_parser.EpubError, aligner.AlignmentError, packager.PackagerError, NotImplementedError, Exception) as exc:
        log.error("error: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
