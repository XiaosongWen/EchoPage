import argparse
import logging
import re
import sys
from pathlib import Path

from echopage import aligner, decryptor, packager, parser as epub_parser

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
    b.add_argument("--verbose", action="store_true", help="enable debug logging")
    return p


def validate(args, parser):
    for path in [args.epub, *args.audio]:
        if not Path(path).is_file():
            parser.error(f"file not found: {path}")
    if args.activation_bytes and not re.fullmatch(r"[0-9a-fA-F]{8}", args.activation_bytes):
        parser.error("--activation-bytes must be exactly 8 hex characters")
    if bool(args.audible_key) != bool(args.audible_iv):
        parser.error("--audible-key and --audible-iv must be given together")


def _phase(name, fn, *a, **kw):
    log.info("%s: start", name)
    result = fn(*a, **kw)
    log.info("%s: done", name)
    return result


def run_build(args):
    audio = _phase("decrypt", decryptor.decrypt, args.audio,
                   activation_bytes=args.activation_bytes,
                   audible_key=args.audible_key, audible_iv=args.audible_iv,
                   work_dir=args.work_dir)
    book = _phase("parse", epub_parser.parse, args.epub)
    alignment = _phase("align", aligner.align, book, audio,
                       granularity=args.granularity, model_size=args.model_size,
                       device=args.device, work_dir=args.work_dir)
    _phase("package", packager.package, args.epub, audio, alignment, args.output)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s", stream=sys.stdout, force=True,
    )
    validate(args, parser)
    try:
        run_build(args)
    except decryptor.DecryptionError as exc:
        log.error("error: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
