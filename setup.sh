#!/usr/bin/env bash
# ==============================================================================
# EchoPage Environment & Dependency Setup Script
# Works on: Linux (Ubuntu/Debian, Fedora, Arch), WSL2, and macOS.
# ==============================================================================

set -e

# ANSI Color codes
BOLD="\033[1m"
GREEN="\033[0;32m"
YELLOW="\033[0;33m"
CYAN="\033[0;36m"
RED="\033[0;31m"
RESET="\033[0m"

log_info() {
    echo -e "${CYAN}${BOLD}[INFO]${RESET} $1"
}

log_success() {
    echo -e "${GREEN}${BOLD}[SUCCESS]${RESET} $1"
}

log_warn() {
    echo -e "${YELLOW}${BOLD}[WARNING]${RESET} $1"
}

log_error() {
    echo -e "${RED}${BOLD}[ERROR]${RESET} $1"
}

echo -e "\n${BOLD}=====================================================${RESET}"
echo -e "${BOLD}       EchoPage Automated Environment Setup         ${RESET}"
echo -e "${BOLD}=====================================================${RESET}\n"

# 1. Detect Python 3.10+
log_info "Checking Python version..."
PYTHON=""
for candidate in python3 python python3.12 python3.11 python3.10; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PY_VER=$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)
        MAJOR=$(echo "$PY_VER" | cut -d. -f1)
        MINOR=$(echo "$PY_VER" | cut -d. -f2)
        if [ "$MAJOR" -eq 3 ] && [ "$MINOR" -ge 10 ]; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    log_error "Python >= 3.10 is required but was not found."
    log_info "Please install Python 3.10 or newer (e.g. 'sudo apt install python3 python3-venv' or 'brew install python@3.12')."
    exit 1
fi

log_success "Found compatible Python: $($PYTHON --version) ($PYTHON)"

# 2. Check System FFmpeg Dependency
log_info "Checking system FFmpeg & ffprobe..."
HAS_FFMPEG=true
if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
    HAS_FFMPEG=false
    log_warn "FFmpeg or ffprobe is not installed on PATH."
    if [ "$(uname)" = "Darwin" ]; then
        log_info "Attempting to install via Homebrew..."
        if command -v brew >/dev/null 2>&1; then
            brew install ffmpeg
            HAS_FFMPEG=true
        else
            log_error "Homebrew not found. Please install FFmpeg manually via 'brew install ffmpeg'."
        fi
    elif [ -f /etc/debian_version ] || grep -qi "ubuntu" /etc/os-release 2>/dev/null; then
        log_info "Attempting to install via apt..."
        if command -v sudo >/dev/null 2>&1; then
            sudo apt update && sudo apt install -y ffmpeg
            HAS_FFMPEG=true
        else
            log_warn "sudo not available. Please run: apt update && apt install -y ffmpeg"
        fi
    fi
fi

if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
    log_success "FFmpeg and ffprobe are ready."
else
    log_warn "FFmpeg could not be automatically installed. Audio conversion features may fail until FFmpeg is installed."
fi

# 3. Create Virtual Environment
VENV_DIR=".venv"
if [ ! -d "$VENV_DIR" ]; then
    log_info "Creating virtual environment at '$VENV_DIR'..."
    "$PYTHON" -m venv "$VENV_DIR"
    log_success "Virtual environment created."
else
    log_info "Using existing virtual environment at '$VENV_DIR'."
fi

VENV_PYTHON="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"

# Ensure pip is up to date
log_info "Upgrading pip, setuptools, and wheel..."
"$VENV_PIP" install --upgrade pip setuptools wheel -q

# 4. Detect GPU and Install PyTorch
log_info "Detecting compute hardware..."
HAS_NVIDIA_GPU=false
if command -v nvidia-smi >/dev/null 2>&1; then
    if nvidia-smi >/dev/null 2>&1; then
        HAS_NVIDIA_GPU=true
    fi
fi

if [ "$HAS_NVIDIA_GPU" = true ]; then
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader | head -n 1)
    log_success "NVIDIA GPU detected: $GPU_NAME"
    log_info "Installing PyTorch with CUDA 12.4 support (accelerated for RTX GPUs)..."
    "$VENV_PIP" install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
else
    if [ "$(uname)" = "Darwin" ]; then
        log_info "Running on macOS (Apple Silicon / Intel). Installing PyTorch for macOS..."
    else
        log_info "No NVIDIA GPU detected. Installing CPU PyTorch..."
    fi
    "$VENV_PIP" install torch torchvision torchaudio
fi

# 5. Install EchoPage and dependencies
log_info "Installing EchoPage and alignment dependencies (WhisperX, lxml, nltk)..."
"$VENV_PIP" install -e ".[align,dev]"

# 6. Pre-cache NLTK Tokenizer Models
log_info "Pre-caching NLTK sentence tokenizers (punkt, punkt_tab)..."
"$VENV_PYTHON" -c "import nltk; nltk.download('punkt', quiet=True); nltk.download('punkt_tab', quiet=True)"

# 7. Disable Pyannote Telemetry by default
log_info "Disabling Pyannote default telemetry tracking..."
"$VENV_PYTHON" -c "
try:
    from pyannote.audio.telemetry.metrics import set_telemetry_metrics
    set_telemetry_metrics(False, save_choice_as_default=True)
except Exception:
    pass
" 2>/dev/null || true

# 8. Smoke test
log_info "Verifying installation..."
"$VENV_PYTHON" -c "
import echopage
import whisperx
print(f'EchoPage version: {echopage.__version__}')
"

echo -e "\n${BOLD}=====================================================${RESET}"
echo -e "${GREEN}${BOLD}             Setup Completed Successfully!           ${RESET}"
echo -e "${BOLD}=====================================================${RESET}\n"
echo -e "To activate your virtual environment:"
echo -e "  ${CYAN}source .venv/bin/activate${RESET}\n"
echo -e "To build a narrated EPUB:"
echo -e "  ${CYAN}echopage build --epub <path-to-epub> --audio <path-to-audio> --output <path-to-output>${RESET}\n"
