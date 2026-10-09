import argparse


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="echopage",
        description="Add synced audio narration to an EPUB.",
    )
    parser.parse_args(argv)
