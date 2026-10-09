import argparse
import logging
import re
import sys
from pathlib import Path

from echopage import aligner, audio, decryptor, packager, parser as epub_parser

log = logging.getLogger("echopage")


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
    b.add_argument("--model-size", choices=["small", "medium", "large-v3"], default="small",
                   help="WhisperX model size (default: small)")
    b.add_argument("--device", choices=["cpu", "cuda", "mps"], help="compute device")
    b.add_argument("--work-dir", help="directory for intermediate files")
    b.add_argument("--keep-temp", action="store_true", help="keep temporary intermediate files")
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
    p_align.add_argument("--model-size", choices=["small", "medium", "large-v3", "base", "tiny"], default="small")
    p_align.add_argument("--device", choices=["cpu", "cuda", "mps"])
    p_align.add_argument("--work-dir", help="working directory")
    p_align.add_argument("--json-out", help="save alignment output JSON to file")

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


def _phase(name, fn, *a, **kw):
    log.info("%s: start", name)
    result = fn(*a, **kw)
    log.info("%s: done", name)
    return result


def run_build(args):
    audio_files = _phase("decrypt", decryptor.decrypt, args.audio,
                         activation_bytes=args.activation_bytes,
                         audible_key=args.audible_key, audible_iv=args.audible_iv,
                         work_dir=args.work_dir)
    book = _phase("parse", epub_parser.parse, args.epub)
    alignment = _phase("align", aligner.align, book, audio_files,
                       granularity=args.granularity, model_size=args.model_size,
                       device=args.device, work_dir=args.work_dir)
    _phase("package", packager.package, args.epub, audio_files, alignment, args.output)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s", stream=sys.stdout, force=True,
    )
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
            )
            print(f"Aligned {len(alignment)} chapters:")
            for ch in alignment:
                print(f"  Chapter '{ch.spine_item_id}' ({ch.xhtml_filename} -> {ch.audio_filename}): {len(ch.timeline)} sentences")
                for entry in ch.timeline:
                    dur_s = (entry.end_ms - entry.start_ms) / 1000.0
                    print(f"    [{entry.element_id}] {entry.start_ms}ms - {entry.end_ms}ms ({dur_s:.2f}s, conf={entry.confidence:.2f}): {entry.text[:60]}")
            if args.json_out:
                import json
                with open(args.json_out, "w", encoding="utf-8") as f:
                    json.dump(alignment, f, indent=2, ensure_ascii=False)
                print(f"Saved alignment to: {args.json_out}")
    except (decryptor.DecryptionError, audio.AudioError, epub_parser.EpubError, aligner.AlignmentError) as exc:
        log.error("error: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
