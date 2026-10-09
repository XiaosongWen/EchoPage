# EchoPage

Add synced audio narration to an EPUB.

## Prerequisites

- Python 3.10+
- FFmpeg (verify with `ffmpeg -version`):

  ```sh
  brew install ffmpeg
  ```

## Install

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

> **Note:** Homebrew Python blocks system-wide `pip`/`pip3` installs (PEP 668),
> and `echopage` and `pytest` only exist inside the virtualenv. Run
> `source .venv/bin/activate` in every new terminal before using them.

## Usage

```sh
echopage --help
```

## Test

```sh
pytest
```
